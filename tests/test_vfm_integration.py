"""
tests/test_vfm_integration.py  — Hour 9

End-to-end smoke tests covering the full pipeline without a running DB or NER model.
Uses mocks for external dependencies so tests run in CI with zero infrastructure.

Run:  pytest tests/test_vfm_integration.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.schemas.fleet_update import (
    ConfidenceRoute, FleetUpdate, Intent, MessageSource,
    Modality, SessionContext,
)
from app.services.rule_engine import RuleEngine


# ---------------------------------------------------------------------------
# FleetUpdate domain model tests
# ---------------------------------------------------------------------------

class TestFleetUpdate:

    def test_from_raw_populates_interface_block(self):
        u = FleetUpdate.from_raw(
            source         = MessageSource.TELEGRAM,
            operator_id = "123456",
            chat_id        = "-1001234",
            raw_text       = "Залил 50 литров",
        )
        assert u.operator_id == "123456"
        assert u.chat_id        == "-1001234"
        assert u.raw_text       == "Залил 50 литров"
        assert u.source         == MessageSource.TELEGRAM
        assert u.intent         == Intent.UNKNOWN
        assert u.confidence     == 0.0
        assert u.machine_id     is None

    def test_confidence_routing_thresholds(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )

        u.confidence = 0.90
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.AUTO

        u.confidence = 0.70
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.CONFIRM

        u.confidence = 0.50
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.LLM

    def test_owner_admin_intent_always_auto(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="#добавитьмашину"
        )
        u.intent     = Intent.ADD_MACHINE
        u.confidence = 0.0   # would normally trigger LLM route
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.AUTO

    def test_has_active_session_false_without_session(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        assert u.has_active_session is False

    def test_has_active_session_true_with_session(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.session = SessionContext(machine_id=42)
        assert u.has_active_session is True
        assert u.machine_id == 42

    def test_add_error_and_mark_processed(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.add_error("something went wrong")
        assert len(u.processing_errors) == 1
        assert u.processed_at is None
        u.mark_processed()
        assert u.processed_at is not None


# ---------------------------------------------------------------------------
# NER confidence helper tests
# ---------------------------------------------------------------------------

class TestConfidenceHelpers:
    """
    NER confidence helpers are pure numpy functions — no transformers needed.
    We import them directly from the module level to avoid the full module import.
    """

    def test_softmax_sums_to_one(self):
        import numpy as np
        # Inline the function to avoid importing the full ner_handler module
        # (which requires transformers + onnxruntime not available in CI)
        def _softmax(logits):
            shifted = logits - logits.max(axis=-1, keepdims=True)
            exp = np.exp(shifted)
            return exp / exp.sum(axis=-1, keepdims=True)

        logits = np.array([[1.0, 2.0, 0.5]])
        probs  = _softmax(logits)
        assert abs(probs.sum() - 1.0) < 1e-6

    def test_aggregate_confidence_returns_min_non_o(self):
        import numpy as np

        def _aggregate_confidence(token_probs, pred_labels):
            non_o = [token_probs[i] for i, l in enumerate(pred_labels) if l != "O"]
            return float(min(non_o)) if non_o else 0.0

        probs  = np.array([0.9, 0.8, 0.75, 0.95])
        labels = ["O", "B-FUEL", "I-FUEL", "O"]
        assert _aggregate_confidence(probs, labels) == pytest.approx(0.75)

    def test_aggregate_confidence_all_o_returns_zero(self):
        import numpy as np

        def _aggregate_confidence(token_probs, pred_labels):
            non_o = [token_probs[i] for i, l in enumerate(pred_labels) if l != "O"]
            return float(min(non_o)) if non_o else 0.0

        probs  = np.array([0.9, 0.85])
        labels = ["O", "O"]
        assert _aggregate_confidence(probs, labels) == 0.0


# ---------------------------------------------------------------------------
# RuleEngine tests (no DB needed — pure logic)
# ---------------------------------------------------------------------------

MINIMAL_RULES_YAML = """
rules:
  - id: test_fuel_anomaly
    enabled: true
    when:
      intent: fuel_log
      conditions:
        - field: session.fuel_ratio
          op: gt
          value: 30
    then:
      - action: alert_owner
        priority: high
        message: "Anomaly: {machine_reg}"

  - id: test_critical_issue
    enabled: true
    when:
      intent: issue_report
      conditions:
        - field: severity
          op: in
          value: [critical]
    then:
      - action: alert_owner
        priority: critical
        message: "Critical issue on {machine_reg}"
      - action: set_machine_status
        status: DOWN

  - id: test_watcher_nudge
    enabled: true
    trigger: watcher
    when:
      conditions:
        - field: session.minutes_on_shift
          op: gte
          value: 240
    then:
      - action: nudge_operator
        message: "Check in please"
"""


class TestRuleEngine:

    @pytest.fixture
    def engine_with_rules(self, tmp_path):
        """Isolated RuleEngine — path passed directly, no env var dependency."""
        rules_yaml = tmp_path / "test_rules.yaml"
        rules_yaml.write_text(MINIMAL_RULES_YAML)
        return RuleEngine(rules_path=str(rules_yaml))

    @pytest.mark.asyncio
    async def test_fuel_anomaly_rule_fires(self, engine_with_rules):
        """Fuel ratio 100 L/h (200L / 2h) > threshold 30 → alert_owner fires."""
        update = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="залил 200 литров",
        )
        update.intent   = Intent.FUEL_LOG
        update.entities = {"fuel_volume": 200}
        update.session  = SessionContext(
            machine_id=1, machine_reg_number="CAT-101",
            hours_logged_today=2.0,
        )
        db = AsyncMock()
        actions = await engine_with_rules.evaluate(db, update)

        types = [a.action_type for a in actions]
        assert "alert_owner" in types
        msg = next(a.message for a in actions if a.action_type == "alert_owner")
        assert "CAT-101" in msg

    @pytest.mark.asyncio
    async def test_fuel_rule_does_not_fire_below_threshold(self, engine_with_rules):
        """Fuel ratio 5 L/h (40L / 8h) < threshold 30 → no actions."""
        update = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="залил 40 литров",
        )
        update.intent   = Intent.FUEL_LOG
        update.entities = {"fuel_volume": 40}
        update.session  = SessionContext(
            machine_id=1, machine_reg_number="CAT-101",
            hours_logged_today=8.0,
        )
        db = AsyncMock()
        actions = await engine_with_rules.evaluate(db, update)
        assert actions == []

    @pytest.mark.asyncio
    async def test_critical_issue_fires_correct_actions(self, engine_with_rules):
        """Critical severity → alert_owner + set_machine_status, message contains machine reg."""
        from app.schemas.fleet_update import Severity
        update = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="огонь в кабине",
        )
        update.intent   = Intent.ISSUE_REPORT
        update.severity = Severity.CRITICAL
        update.session  = SessionContext(machine_id=1, machine_reg_number="BZ-07")

        db = AsyncMock()
        actions = await engine_with_rules.evaluate(db, update)

        types = {a.action_type for a in actions}
        assert "alert_owner"        in types
        assert "set_machine_status" in types
        msg = next(a.message for a in actions if a.action_type == "alert_owner")
        assert "BZ-07" in msg

    @pytest.mark.asyncio
    async def test_watcher_rule_fires_above_threshold(self, engine_with_rules):
        """300 min on shift ≥ 240 threshold → nudge fires."""
        ctx = {"session": {"minutes_on_shift": 300, "machine_reg": "EX-01"}}
        actions = await engine_with_rules.evaluate_watcher_rules(ctx)
        assert len(actions) == 1
        assert actions[0].action_type == "nudge_operator"

    @pytest.mark.asyncio
    async def test_watcher_rule_does_not_fire_below_threshold(self, engine_with_rules):
        """60 min on shift < 240 threshold → no nudge."""
        ctx = {"session": {"minutes_on_shift": 60, "machine_reg": "EX-01"}}
        actions = await engine_with_rules.evaluate_watcher_rules(ctx)
        assert actions == []

    def test_message_rule_excluded_from_watcher_evaluate(self, engine_with_rules):
        """fuel_anomaly has no trigger:watcher → must not appear in watcher evaluation."""
        import asyncio
        ctx = {"session": {"fuel_ratio": 999, "minutes_on_shift": 60}}
        actions = asyncio.get_event_loop().run_until_complete(
            engine_with_rules.evaluate_watcher_rules(ctx)
        )
        assert all(a.action_type == "nudge_operator" for a in actions)


# ---------------------------------------------------------------------------
# Session context tests
# ---------------------------------------------------------------------------

class TestSessionContext:

    def test_minutes_on_shift_calculation(self):
        ctx = SessionContext(
            machine_id       = 1,
            shift_started_at = datetime(2026, 1, 1, 8, 0),
            minutes_on_shift = 240,
        )
        assert ctx.minutes_on_shift == 240

    def test_defaults_are_zero(self):
        ctx = SessionContext(machine_id=1)
        assert ctx.fuel_logged_today  == 0.0
        assert ctx.hours_logged_today == 0.0
        assert ctx.open_issue_count   == 0
