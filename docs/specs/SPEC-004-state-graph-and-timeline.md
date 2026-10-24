---
id: SPEC-004
title: State graph, timeline events, corrections, derived signals
status: Ready
phase: 0
pillar: foundation
scope_refs: ["§2", "§3 Pillar 4", "§6 H1", "§8", "§15.1", "§15.2"]
adrs: [ADR-0004, ADR-0005, ADR-0008]
depends_on: [SPEC-011]
---

# SPEC-004: State graph, timeline events, corrections, derived signals

## 1. Purpose
The state graph is the source of truth. Confirmed operational events are stored append-only, state and derived signals are projections of those events, and every consumer (replies, waybill, digest, trace) reads the same corrected view.

## 2. Scope and non-goals
**In:** event types, session lifecycle, immutability, corrections, projections, the date-filter fix, fuel-rate baseline and anomaly signal, rebuildability.
**Out:** deciding what to say (SPEC-005), rendering (SPEC-008, SPEC-009), general trend detection (later).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-004-R01 | Every confirmed operational event MUST create exactly one `timeline_event` with `source_conversation_id`, and set `conversation_log.timeline_event_id` in the same transaction. | MUST |
| SPEC-004-R02 | Only confirmed events enter the timeline. Off-topic messages, clarification turns, expired or rejected voice echoes and unconfirmed values MUST NOT create events. | MUST |
| SPEC-004-R03 | v1 event types: `shift_start`, `hours_log`, `fuel_log`, `shift_end`, `issue_open`, `issue_resolved`. Each payload is validated against a versioned schema (`schema_version`). Issue types are a proposal to verify against the existing code (OQ-004-1). | MUST |
| SPEC-004-R04 | A `shift_session` MUST have a machine and an operator. At most one open session per operator. At most one open session per machine unless the owner configures otherwise (OQ-004-2). | MUST |
| SPEC-004-R05 | The application database role MUST have no UPDATE or DELETE privilege on `timeline_event`. | MUST |
| SPEC-004-R06 | A correction MUST be a new event with `corrects_event_id` referencing an event in the same org and machine. The correction carries the full corrected payload. A correction of a correction points to the event it supersedes. | MUST |
| SPEC-004-R07 | A single function `effective_events(scope, range)` MUST resolve correction chains to the chain tip. State, waybill, digest, trace and metrics MUST use it, never raw `timeline_event` reads. | MUST |
| SPEC-004-R08 | A trigger on `timeline_event` MUST raise on UPDATE or DELETE as defence in depth. `/trace` MUST show both the original and its corrections. | MUST |
| SPEC-004-R09 | Canonical state per machine MUST expose: status, current session, last shift summary, fuel today, hours today, open issues, last event timestamp. | MUST |
| SPEC-004-R10 | "Today" values MUST be computed within the org-local calendar day, using the org timezone. This fixes the known bug where `fuel_today` and `hours_today` accumulate across days. | MUST |
| SPEC-004-R11 | Derived signals in v1 are limited to: fuel rate per shift (litres per hour), baseline, and issue recurrence. Baseline is the rolling per-machine average once at least M shifts exist (starting value M = 5), otherwise a machine-type default labelled as default. | MUST |
| SPEC-004-R12 | A `fuel_rate_anomaly` signal MUST be set when the current rate deviates from baseline beyond a configured threshold, and cleared when a later shift returns within it. | MUST |
| SPEC-004-R13 | All state and derived signals MUST be rebuildable from the timeline. A rebuild command followed by a diff against live projections MUST show no differences. | MUST |
| SPEC-004-R14 | Shift-start recall data (previous shift fuel, hours, open issues) MUST be available from the state graph without calling the LLM. | MUST |

## 4. Interfaces and data
Tables: `shift_session`, `timeline_event`, `finding` (SPEC-009) in SPEC-011. Functions: `effective_events`, `machine_state(machine, at)`, `fuel_rate(machine, session)`, `baseline(machine)`.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-004-01 | Given a confirmed fuel message, then one event exists and the log row points to it. A second message that is off-topic creates a log row and no event. | R01, R02 | integration |
| AC-004-02 | Given a session cannot start without a machine, then opening a session with null machine fails at the database. | R04 | integration |
| AC-004-03 | Given the application role, when it runs UPDATE or DELETE on `timeline_event`, then the database raises. | R05, R08 | integration |
| AC-004-04 | Given fuel 150 then a correction to 105, then `effective_events` returns 105, `/trace` shows both, and a correction of the correction resolves to the tip. | R06, R07, R08 | integration |
| AC-004-05 | Given events on two calendar days, then `fuel_today` counts only today in the org timezone, including near midnight in a non-UTC timezone. | R10 | unit, integration |
| AC-004-06 | Given fewer than M shifts, then baseline equals the machine-type default and is labelled default. After M shifts it is the rolling average. | R11 | unit |
| AC-004-07 | Given a shift rate 50% above baseline, then `fuel_rate_anomaly` is set. A later normal shift clears it. | R12 | unit |
| AC-004-08 | Given a populated database, when state is rebuilt from the timeline, then it equals the live projections. | R13 | integration |
| AC-004-09 | Given an event payload that fails its schema or lacks `schema_version`, then it is rejected before insert. | R03 | unit |
| AC-004-10 | Given a machine with a session and events, then `machine_state` returns status, current session, last shift summary, fuel today, hours today, open issues and last event timestamp. | R09 | unit |
| AC-004-11 | Given the LLM client is absent, then shift-start recall data is still produced from the state graph. | R14 | unit |

## 6. Open questions
- **OQ-004-1:** Reconcile event types and payloads with the existing `logbuk-backend` models. Freeze in an appendix.
- **OQ-004-2:** Can two operators hold open sessions on one machine at once (overlapping shifts)? Ask the pilot owner.
- **OQ-004-3:** Baseline window and anomaly threshold values. Start conservative and tune on pilot data.
- **OQ-004-4:** The scope notes `fuel_baseline` is currently null in the sandbox. Confirm the cause when implementing R11.

## 7. Traceability
Scope §2, §3 Pillar 4, §6, §8, §15. ADR-0004, ADR-0005, ADR-0008. Invariants 1 and 9. Related specs: SPEC-001, SPEC-005, SPEC-008, SPEC-009, SPEC-011.
