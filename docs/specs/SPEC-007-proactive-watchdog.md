---
id: SPEC-007
title: Proactive watchdog, five fixed rules, suppression and quiet hours
status: Ready
phase: 4
pillar: 3
scope_refs: ["§3 Pillar 3", "§7", "§14 inv. 4, 10"]
adrs: [ADR-0010]
depends_on: [SPEC-004, SPEC-005, SPEC-006, SPEC-011]
---

# SPEC-007: Proactive watchdog, five fixed rules, suppression and quiet hours

## 1. Purpose
A scheduler plus deterministic rules gives the agent initiative: nudging a missing shift start, asking for the one missing item, following up on open issues, flagging a fuel anomaly and sending the daily digest. It never repeats itself and never writes at night.

## 2. Scope and non-goals
**In:** scheduler, the five rules, suppression, quiet hours, expected shift start.
**Out:** any sixth rule (needs an ADR-0010 update), wording (SPEC-006), digest content (SPEC-009).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-007-R01 | A scheduler MUST evaluate the rules at a fixed interval (starting value 1 minute) as a deterministic function of `(state, now, config)`. It MUST be idempotent: running twice in the same minute produces no duplicate message. | MUST |
| SPEC-007-R02 | **Rule R1.** If no `shift_start` exists by the expected start time plus a grace period (starting value 30 minutes) for an operator on a working day, send one nudge to the operator. Suppression key: `(org, machine, date, R1)`. | MUST |
| SPEC-007-R03 | **Rule R2.** When a shift is closing with fuel or hours missing, ask for exactly the missing item. Suppression key: `(session, R2)`. | MUST |
| SPEC-007-R04 | **Rule R3.** At the next shift start, if an open issue exists from the previous shift, follow up on it, included in the shift-start recall (SPEC-005-R03). Suppression key: `(issue_id, shift)`. | MUST |
| SPEC-007-R05 | **Rule R4.** On `fuel_rate_anomaly`, send the operator a symptom question and flag the owner. Suppression key: `(machine, R4)` until state changes. | MUST |
| SPEC-007-R06 | **Rule R5.** At the org's digest time send the digest to the owner (SPEC-009). Suppression key: `(org, date)`. | MUST |
| SPEC-007-R07 | The `suppression` table MUST have a unique key `(org, machine, rule, window_key)`. A rule re-arms only when the underlying state changes, never on a timer. | MUST |
| SPEC-007-R08 | Quiet hours MUST be configured per org timezone (starting value 21:00 to 06:00). Operator-bound proactive messages MUST NOT be sent during quiet hours. Owner-bound alerts are deferred to the end of quiet hours. Configuration MUST reject a digest time inside quiet hours. | MUST |
| SPEC-007-R09 | Expected shift start MUST be an org-level default, configurable per operator. The sample waybill suggests an 08:00 to 19:00 day. Confirm with the pilot (OQ-007-1). | MUST |
| SPEC-007-R10 | All proactive output MUST pass through the policy engine, the response validator and the normal reply path. The scheduler MUST NOT send text directly. | MUST |
| SPEC-007-R11 | The rule list is closed. Adding a rule requires updating ADR-0010 and this spec first and removing or deferring another. | MUST |
| SPEC-007-R12 | Every proactive send and every suppression decision MUST be logged with rule id, key and reason. | MUST |

## 4. Interfaces and data
Tables: `suppression`, `digest_log` (SPEC-011). Config: `expected_shift_start`, `grace_minutes`, `quiet_hours`, `digest_time` per org, optional per operator.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-007-01 | Given no shift start by 08:30 on a working day, then exactly one nudge is sent. Running the scheduler again sends nothing. | R01, R02, R07 | integration |
| AC-007-02 | Given shift close with hours present and fuel missing, then one question asks for fuel only, once per session. | R03 | golden |
| AC-007-03 | Given an open issue from yesterday, when the shift starts, then the follow-up appears once. | R04 | golden |
| AC-007-04 | Given a fuel anomaly, then the operator gets one symptom question and the owner one flag. No repeat until a new shift, hours entry or cleared anomaly. | R05, R07 | integration |
| AC-007-05 | Given 03:00 in the org timezone, then operator nudges are not sent and the owner alert is held until 06:00. | R08 | integration |
| AC-007-06 | Given a digest time of 22:00 with quiet hours from 21:00, then configuration is rejected. | R08 | unit |
| AC-007-07 | Given the scheduler code, then no path sends text without passing the policy engine and validator. | R10 | unit (static) |
| AC-007-08 | Given the digest time, then one digest is sent per org per date even if the scheduler restarts. | R06, R07 | integration |
| AC-007-09 | Given a per-operator expected start time, then it overrides the org default for Rule R1. | R09 | unit |
| AC-007-10 | Given the rule registry, then a test asserts it has exactly five entries and names ADR-0010 in its failure message. | R11 | unit (static) |
| AC-007-11 | Given any proactive send or suppression decision, then a log entry with rule id, key and reason exists. | R12 | integration |

## 6. Open questions
- **OQ-007-1:** Expected shift start and grace period for the pilot. Confirm with the pilot owner (also §13).
- **OQ-007-2:** Working days. Rule R1 would nudge on days off. Candidate fix: fire only for operators with a shift in the previous N days, or a quick "выходной" reply that suppresses the day. Decide before the pilot.
- **OQ-007-3:** Can a critical escalation override quiet hours? Default no.
- **OQ-007-4:** How shift close is detected when the operator never says "закончил". Candidate: R2 also fires at a configured expected end time. Needs the owner's view.

## 7. Traceability
Scope §3 Pillar 3, §7, §14. ADR-0010. Invariants 4 and 10. Related specs: SPEC-004, SPEC-005, SPEC-006, SPEC-009.
