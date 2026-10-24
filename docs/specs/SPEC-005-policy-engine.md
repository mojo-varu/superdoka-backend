---
id: SPEC-005
title: Policy engine and the three day-one behaviours
status: Ready
phase: 0
pillar: 3
scope_refs: ["§3 Pillar 3", "§4", "§7", "§11 phase 0"]
adrs: [ADR-0002, ADR-0010]
depends_on: [SPEC-003, SPEC-004]
---

# SPEC-005: Policy engine and the three day-one behaviours

## 1. Purpose
The policy engine decides what happens next, deterministically, from the understood message and the state graph. The "sticky" feel comes from three behaviours implemented here as rules, not from the LLM.

## 2. Scope and non-goals
**In:** the `PolicyDecision` object, action set, rule table, shift-start recall, sanity challenge, close-out prompt, escalation, clarification limits.
**Out:** wording (SPEC-006), scheduling of proactive triggers (SPEC-007), understanding (SPEC-003).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-005-R01 | The engine MUST be a pure function of `(Understanding, state snapshot, config, now)` returning a `PolicyDecision`. No I/O, no randomness, no LLM calls. | MUST |
| SPEC-005-R02 | `PolicyDecision` MUST be a typed, schema-validated object: `action` in {CONFIRM, CLARIFY, ALERT, NUDGE, ESCALATE}, `task_type`, `commit` in {now, after_confirm, never}, `reason_codes[]`, `payload` (facts for the reply), optional `suppression_key`, `rules_version`. Tier 1 outputs are inputs only. | MUST |
| SPEC-005-R03 | **Shift-start recall.** On `shift_start` for a machine with a previous shift, the reply MUST state the previous shift's fuel, hours and open issues from the state graph and ask how things are now. For example: "Вчера на CAT-101: 150 л, 6 ч, открыта течь гидравлики. Как сейчас?" | MUST |
| SPEC-005-R04 | **Sanity challenge.** When `implausible=true`, the decision MUST be CONFIRM with `commit=after_confirm` and the value shown back. It MUST NOT be a silent log. | MUST |
| SPEC-005-R05 | **Close-out prompt.** At shift end with fuel or hours missing for the session, the decision MUST be CLARIFY for exactly the missing item and nothing else. | MUST |
| SPEC-005-R06 | Escalation conditions MUST be a versioned rules table. v1 contains: a `fuel_rate_anomaly` flagged to the owner (with the symptom question to the operator), and an issue at or above a configured severity. | MUST |
| SPEC-005-R07 | CLARIFY MUST ask one question per turn. After K unresolved turns (starting value K = 2) the engine MUST stop asking, log the turn as unclear, and tell the operator what is missing. | MUST |
| SPEC-005-R08 | Rules MUST carry a `rules_version` that is stamped into every `conversation_log` row (SPEC-010-R02). | MUST |
| SPEC-005-R09 | Every `PolicyDecision` MUST be persisted on the conversation log row. | MUST |
| SPEC-005-R10 | For decisions originating from the scheduler, the engine MUST consult the suppression table and quiet hours (SPEC-007) before returning an outbound action. | MUST |
| SPEC-005-R11 | Every rule MUST have at least one golden-set case (SPEC-010-R09, R10). | MUST |
| SPEC-005-R12 | When the LLM is disabled the decision, payload and chosen template MUST be identical. | MUST |

## 4. Interfaces and data
Input: `Understanding`, `MachineState`, `SessionContext`, `OrgConfig`. Output: `PolicyDecision`. Rules live in a versioned module with a rules table for escalation.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-005-01 | Same inputs run twice yield identical `PolicyDecision` objects. A property test varies `now` only through the argument. | R01 | unit |
| AC-005-02 | A decision missing a required field fails schema validation. | R02 | unit |
| AC-005-03 | Given yesterday 150 L, 6 h and an open hydraulic leak on CAT-101, when the operator starts a shift, then the reply payload contains those facts and a question. | R03 | golden |
| AC-005-04 | Given "залил 5000 литров", then CONFIRM with `commit=after_confirm`, no event yet. After the operator confirms, the event is written. | R04 | golden |
| AC-005-05 | Given shift end with hours present and fuel missing, then CLARIFY asks only for fuel. | R05 | golden |
| AC-005-06 | Given `fuel_rate_anomaly` set, then the decision includes a symptom question for the operator and a flag for the owner. | R06 | integration |
| AC-005-07 | Given two unresolved clarification turns, then the engine stops asking and tells the operator what is missing. | R07 | integration |
| AC-005-08 | Given the LLM disabled, then decisions equal those with it enabled for the same inputs. | R12 | integration |
| AC-005-09 | Given any processed message, then its log row holds the serialised `PolicyDecision` and `rules_version`. | R08, R09 | integration |
| AC-005-10 | Given a scheduler-originated decision during quiet hours or with an active suppression key, then no outbound action is returned. | R10 | unit |
| AC-005-11 | Given the rule registry, then a CI check fails if any rule id has no golden case. | R11 | unit (static) |

## 6. Open questions
- **OQ-005-1:** Confirm the CONFIRM semantics against existing code. This spec treats CONFIRM as "acknowledge a recorded fact or ask to confirm one", separated by the `commit` field.
- **OQ-005-2:** Issue severity scale and the escalation threshold. Needs the pilot owner's view of what is urgent.
- **OQ-005-3:** The task types T1, T2 and T8 are not defined in the scope document. Enumerate from `ARCHITECTURE_VERBALIZED.md` and the code and freeze them in an appendix.

## 7. Traceability
Scope §3 Pillar 3, §4, §7, §11 phase 0. ADR-0002, ADR-0010. Invariants 4, 5, 6. Related specs: SPEC-003, SPEC-004, SPEC-006, SPEC-007.
