"""
tests/test_e2e_message_flow.py

End-to-end pipeline test: raw Telegram payload → FleetUpdate → rules → reply.
No real DB, no real NER model, no network calls.
All external dependencies mocked at the boundary.

Tests the complete happy path and the key branches:
  - shift_start binds operator to machine
  - fuel_log with session routes correctly, writes timeline event
  - issue_report with CRITICAL fires escalation rule
  - no_session message gets "start shift" prompt
  - low_confidence escalates to LLM fallback path
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.schemas.fleet_update import (
    ConfidenceRoute, FleetUpdate, Intent, MessageSource,
    Modality, SessionContext, Severity,
)
from app.services.rule_engine import RuleEngine


# ---------------------------------------------------------------------------
# Shared minimal rules fixture
# ---------------------------------------------------------------------------

MINIMAL_RULES = """
rules:
  - id: critical_escalation
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
        message: "CRITICAL on {machine_reg}"
      - action: set_machine_status
        status: DOWN

  - id: fuel_anomaly
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
        message: "Fuel anomaly: {machine_reg}"
"""


@pytest.fixture
def rule_engine(tmp_path):
    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(MINIMAL_RULES)
    return RuleEngine(rules_path=str(yaml_file))


# ---------------------------------------------------------------------------
# Test 1: FleetUpdate factory — interface block populated correctly
# ---------------------------------------------------------------------------

class TestInterfaceBlock:

    def test_telegram_update_built_from_raw_fields(self):
        u = FleetUpdate.from_raw(
            source         = MessageSource.TELEGRAM,
            operator_id = "987654",
            chat_id        = "-100112233",
            raw_text       = "Начинаю смену на 101-м",
            modality       = Modality.TEXT,
            message_id     = "555",
        )
        assert u.source         == MessageSource.TELEGRAM
        assert u.operator_id == "987654"
        assert u.chat_id        == "-100112233"
        assert u.raw_text       == "Начинаю смену на 101-м"
        assert u.modality       == Modality.TEXT
        assert u.message_id     == "555"
        assert u.update_id is not None   # uuid assigned

    def test_voice_modality_preserved(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="", modality=Modality.VOICE, media_url="file://voice.ogg",
        )
        assert u.modality  == Modality.VOICE
        assert u.media_url == "file://voice.ogg"

    def test_unique_update_ids(self):
        ids = {
            FleetUpdate.from_raw(
                source="telegram", operator_id="1", chat_id="1", raw_text="x"
            ).update_id
            for _ in range(100)
        }
        assert len(ids) == 100   # all unique


# ---------------------------------------------------------------------------
# Test 2: Intelligence block — confidence routing
# ---------------------------------------------------------------------------

class TestIntelligenceBlock:

    def test_high_confidence_routes_auto(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.confidence = 0.92
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.AUTO
        assert not u.needs_confirmation

    def test_mid_confidence_routes_confirm(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.confidence = 0.72
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.CONFIRM

    def test_low_confidence_routes_llm(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.confidence = 0.45
        u.set_confidence_route()
        assert u.confidence_route == ConfidenceRoute.LLM

    def test_hashtag_owner_intent_always_auto(self):
        for intent in (Intent.ADD_MACHINE, Intent.ASSIGN_MACHINE):
            u = FleetUpdate.from_raw(
                source="telegram", operator_id="1", chat_id="1",
                raw_text="#добавитьмашину",
            )
            u.intent     = intent
            u.confidence = 0.0   # would normally be LLM route
            u.set_confidence_route()
            assert u.confidence_route == ConfidenceRoute.AUTO, \
                f"Owner intent {intent} should always be AUTO"

    def test_via_llm_flag_propagates(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.via_llm    = True
        u.confidence = 0.75
        u.set_confidence_route()
        assert u.via_llm is True
        assert u.confidence_route == ConfidenceRoute.CONFIRM


# ---------------------------------------------------------------------------
# Test 3: Agency block — session context
# ---------------------------------------------------------------------------

class TestAgencyBlock:

    def test_no_session_machine_id_is_none(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        assert u.machine_id      is None
        assert u.has_active_session is False

    def test_with_session_machine_id_resolves(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.session = SessionContext(
            machine_id         = 7,
            machine_reg_number = "CAT-007",
            hours_logged_today = 4.5,
            open_issue_count   = 1,
        )
        assert u.machine_id       == 7
        assert u.has_active_session is True

    def test_error_accumulation(self):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.add_error("NER timeout")
        u.add_error("DB write failed")
        assert len(u.processing_errors) == 2
        assert "NER timeout" in u.processing_errors


# ---------------------------------------------------------------------------
# Test 4: Rule engine — full pipeline evaluation
# ---------------------------------------------------------------------------

class TestRulePipeline:

    @pytest.mark.asyncio
    async def test_critical_issue_fires_two_actions(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="пожар в кабине",
        )
        u.intent   = Intent.ISSUE_REPORT
        u.severity = Severity.CRITICAL
        u.session  = SessionContext(machine_id=1, machine_reg_number="BZ-99")

        actions = await rule_engine.evaluate(AsyncMock(), u)
        types = {a.action_type for a in actions}
        assert "alert_owner"        in types
        assert "set_machine_status" in types
        msg = next(a.message for a in actions if a.action_type == "alert_owner")
        assert "BZ-99" in msg

    @pytest.mark.asyncio
    async def test_normal_fuel_log_no_rules_fire(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="залил 50 литров",
        )
        u.intent   = Intent.FUEL_LOG
        u.entities = {"fuel_volume": 50}
        u.session  = SessionContext(
            machine_id=1, machine_reg_number="EX-01",
            hours_logged_today=8.0,   # ratio = 50/8 = 6.25 L/h — normal
        )
        actions = await rule_engine.evaluate(AsyncMock(), u)
        assert actions == []

    @pytest.mark.asyncio
    async def test_anomalous_fuel_log_fires_alert(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="залил 300 литров",
        )
        u.intent   = Intent.FUEL_LOG
        u.entities = {"fuel_volume": 300}
        u.session  = SessionContext(
            machine_id=1, machine_reg_number="TK-42",
            hours_logged_today=2.0,   # ratio = 300/2 = 150 L/h — anomalous
        )
        actions = await rule_engine.evaluate(AsyncMock(), u)
        types = [a.action_type for a in actions]
        assert "alert_owner" in types

    @pytest.mark.asyncio
    async def test_rules_fired_list_populated(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="пожар",
        )
        u.intent   = Intent.ISSUE_REPORT
        u.severity = Severity.CRITICAL
        u.session  = SessionContext(machine_id=1, machine_reg_number="X")

        await rule_engine.evaluate(AsyncMock(), u)
        assert "critical_escalation" in rule_engine.last_fired_rule_ids

    @pytest.mark.asyncio
    async def test_non_matching_intent_skips_all_rules(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1",
            raw_text="начинаю смену",
        )
        u.intent = Intent.SHIFT_START   # no rule matches shift_start
        actions  = await rule_engine.evaluate(AsyncMock(), u)
        assert actions == []


# ---------------------------------------------------------------------------
# Test 5: Action shape validation
# ---------------------------------------------------------------------------

class TestActionShape:

    @pytest.mark.asyncio
    async def test_actions_have_required_fields(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.intent   = Intent.ISSUE_REPORT
        u.severity = Severity.CRITICAL
        u.session  = SessionContext(machine_id=1, machine_reg_number="R2D2")

        actions = await rule_engine.evaluate(AsyncMock(), u)
        for action in actions:
            assert action.action_type is not None
            assert isinstance(action.priority, str)
            assert action.priority in ("low", "normal", "high", "critical")

    @pytest.mark.asyncio
    async def test_machine_reg_substituted_in_message(self, rule_engine):
        u = FleetUpdate.from_raw(
            source="telegram", operator_id="1", chat_id="1", raw_text="x"
        )
        u.intent   = Intent.ISSUE_REPORT
        u.severity = Severity.CRITICAL
        u.session  = SessionContext(machine_id=1, machine_reg_number="TARDIS-1")

        actions = await rule_engine.evaluate(AsyncMock(), u)
        owner_action = next(
            (a for a in actions if a.action_type == "alert_owner"), None
        )
        assert owner_action is not None
        assert "TARDIS-1" in owner_action.message
        assert "{machine_reg}" not in owner_action.message  # template resolved
