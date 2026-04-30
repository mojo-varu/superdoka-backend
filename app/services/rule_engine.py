"""
app/services/rule_engine.py  — Hour 6

Loads fleet_rules.yaml at startup and evaluates rules against a FleetUpdate.
Rules are data — changing a threshold does NOT require a deployment.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.fleet_update import Action, FleetUpdate, Intent, Severity

logger = logging.getLogger(__name__)

RULES_PATH = Path(os.getenv("RULES_PATH", "app/rules/fleet_rules.yaml"))


class RuleEngine:

    def __init__(self, rules_path: Optional[str] = None):
        self._rules: List[Dict[str, Any]] = []
        self.last_fired_rule_ids: List[str] = []
        self._rules_path = Path(rules_path) if rules_path else RULES_PATH
        self._load_rules()

    def _load_rules(self) -> None:
        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._rules = [r for r in data.get("rules", []) if r.get("enabled", True)]
            logger.info(f"RuleEngine: loaded {len(self._rules)} rules from {self._rules_path}")
        except FileNotFoundError:
            logger.warning(f"Rules file not found at {self._rules_path} — no rules loaded")
            self._rules = []
        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            self._rules = []

    def reload(self) -> None:
        """Hot-reload rules without restarting. Call via admin endpoint."""
        self._load_rules()

    async def evaluate(
        self,
        db:     AsyncSession,
        update: FleetUpdate,
    ) -> List[Action]:
        """
        Evaluate all message-triggered rules against the FleetUpdate.
        Returns list of Actions to execute.
        """
        self.last_fired_rule_ids = []
        actions: List[Action] = []

        ctx = self._build_context(update)

        for rule in self._rules:
            if rule.get("trigger") == "watcher":
                continue   # Watcher rules fired separately

            if not self._intent_matches(rule, update):
                continue

            if self._conditions_met(rule.get("when", {}).get("conditions", []), ctx):
                logger.info(f"Rule fired: {rule['id']}")
                self.last_fired_rule_ids.append(rule["id"])
                actions.extend(self._build_actions(rule.get("then", []), ctx))

        return actions

    async def evaluate_watcher_rules(
        self,
        context: Dict[str, Any],
    ) -> List[Action]:
        """Called by the Watcher for time-based rules."""
        actions: List[Action] = []
        for rule in self._rules:
            if rule.get("trigger") != "watcher":
                continue
            if self._conditions_met(rule.get("when", {}).get("conditions", []), context):
                logger.info(f"Watcher rule fired: {rule['id']}")
                actions.extend(self._build_actions(rule.get("then", []), context))
        return actions

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_context(self, update: FleetUpdate) -> Dict[str, Any]:
        """Flatten FleetUpdate into a dot-accessible dict for condition evaluation."""
        ctx: Dict[str, Any] = {
            "intent":   update.intent,
            "severity": update.severity,
            "entities": update.entities,
            "session":  {},
        }

        if update.session:
            s = update.session
            fuel_vol    = float(update.entities.get("fuel_volume") or 0)
            hours_today = float(s.hours_logged_today) if s.hours_logged_today else 0.0
            fuel_ratio  = (fuel_vol / hours_today) if hours_today > 0 else 0.0

            ctx["session"] = {
                "machine_id":          s.machine_id,
                "machine_reg":         s.machine_reg_number or "",
                "machine_reg_number":  s.machine_reg_number or "",
                "open_issue_count":    s.open_issue_count,
                "fuel_logged_today":   s.fuel_logged_today,
                "hours_logged_today":  hours_today,
                "minutes_on_shift":    s.minutes_on_shift or 0,
                "fuel_ratio":          fuel_ratio,   # pre-computed here for condition checks
            }

        return ctx

    def _intent_matches(self, rule: Dict, update: FleetUpdate) -> bool:
        rule_intent = rule.get("when", {}).get("intent")
        if rule_intent is None:
            return True   # no intent filter → matches all
        try:
            return update.intent == Intent(rule_intent)
        except ValueError:
            return False

    def _conditions_met(
        self,
        conditions: List[Dict],
        ctx:        Dict[str, Any],
    ) -> bool:
        for cond in conditions:
            field    = cond["field"]
            op       = cond["op"]
            expected = cond.get("value")

            actual = self._resolve_field(field, ctx)

            if not self._evaluate_op(actual, op, expected):
                return False
        return True

    @staticmethod
    def _resolve_field(field: str, ctx: Dict[str, Any]) -> Any:
        """Dot-notation field access: 'session.open_issue_count' → ctx['session']['open_issue_count']"""
        parts = field.split(".")
        val   = ctx
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
            else:
                return None
        return val

    @staticmethod
    def _evaluate_op(actual: Any, op: str, expected: Any) -> bool:
        if actual is None:
            return op == "is_null"
        try:
            if op == "eq":       return actual == expected
            if op == "ne":       return actual != expected
            if op == "gt":       return float(actual) > float(expected)
            if op == "lt":       return float(actual) < float(expected)
            if op == "gte":      return float(actual) >= float(expected)
            if op == "lte":      return float(actual) <= float(expected)
            if op == "in":       return actual in expected
            if op == "contains": return str(expected).lower() in str(actual).lower()
            if op == "not_null": return actual is not None
        except (TypeError, ValueError):
            pass
        return False

    def _build_actions(
        self,
        then_clauses: List[Dict],
        ctx:          Dict[str, Any],
    ) -> List[Action]:
        actions = []
        for clause in then_clauses:
            action_type = clause.get("action")
            message     = clause.get("message", "")
            priority    = clause.get("priority", "normal")
            payload     = {k: v for k, v in clause.items()
                          if k not in ("action", "message", "priority")}

            # Template substitution
            try:
                message = message.format(**self._flatten_ctx(ctx))
            except KeyError:
                pass   # template has a key not in context — leave as-is

            actions.append(Action(
                action_type = action_type,
                message     = message.strip(),
                priority    = priority,
                payload     = payload,
            ))
        return actions

    @staticmethod
    def _flatten_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested context for string formatting with safe defaults."""
        flat: Dict[str, Any] = {}
        for k, v in ctx.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    flat[sk] = sv
            else:
                flat[k] = v

        # Safe numeric helpers — never let a missing field crash float()
        def _f(key: str, default: float = 0.0) -> float:
            val = flat.get(key, default)
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        # Convenience aliases so YAML message templates resolve cleanly
        flat.setdefault("machine_reg",       flat.get("machine_reg_number") or "")
        flat.setdefault("operator_name",     flat.get("operator_name") or "оператор")
        flat.setdefault("issue_description", flat.get("description") or flat.get("notes") or "")
        flat.setdefault("open_issue_count",  flat.get("open_issue_count", 0))
        flat.setdefault("fuel_logged",       flat.get("fuel_logged_this_shift", 0))
        flat.setdefault("hours_logged",      flat.get("hours_logged_this_shift", 0))
        flat.setdefault("checkin_count",     flat.get("checkin_count", 0))

        # fuel_volume and hours_today — safe numeric conversion
        fuel_vol    = _f("fuel_volume")
        hours_today = _f("hours_logged_today") or _f("hours_today")
        flat["fuel_volume"] = fuel_vol
        flat["hours_today"] = hours_today

        # fuel_ratio: prefer the pre-computed session value; compute as fallback
        if "fuel_ratio" not in flat:
            flat["fuel_ratio"] = (fuel_vol / hours_today) if hours_today > 0 else 0.0

        return flat


rule_engine = RuleEngine()
