---
id: SPEC-009
title: Daily digest, owner commands, trace, findings log
status: Ready
phase: 2
pillar: 4
scope_refs: ["§3 Pillar 4", "§9 pricing note", "§12", "§15.1"]
adrs: [ADR-0008, ADR-0003]
depends_on: [SPEC-004, SPEC-006, SPEC-011]
---

# SPEC-009: Daily digest, owner commands, trace, findings log

## 1. Purpose
The waybill gets the first yes. This spec keeps the customer: a daily digest the owner can trust because every number is traceable, on-demand views, and a findings log that records the ROI evidence.

## 2. Scope and non-goals
**In:** digest, `/today`, `/machine`, `/trace`, "Откуда?" drill-down, findings log, baseline labelling.
**Out:** web dashboard work, general analytics, pricing (SPEC-013 collects evidence), `/waybill` (SPEC-008).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-009-R01 | The digest MUST start with a "needs attention" block (anomalies, unresolved issues, missing logs), then one line per machine (status, hours, fuel, rate versus baseline, open issues), then fleet totals. | MUST |
| SPEC-009-R02 | The digest MUST be delivered at the org's configured local time, once per org and date, enforced by a unique `(org, date)` in `digest_log`. A retry after failure MUST NOT send a second digest. | MUST |
| SPEC-009-R03 | Where the baseline is a machine-type default it MUST be labelled as default in the digest. | MUST |
| SPEC-009-R04 | The digest MUST state its time window in the header. | MUST |
| SPEC-009-R05 | Every digest line MUST have an inline "Откуда?" button. The callback MUST show the source operator messages with timestamps. Any number MUST be traceable to its source message in at most two taps. | MUST |
| SPEC-009-R06 | A derived number (rate, total) MUST list its inputs on drill-down. Facts with no evidence appear as "не зафиксировано". | MUST |
| SPEC-009-R07 | Owner commands MUST include `/today` (current day so far, same format), `/machine <alias>` (state, recent shifts, open issues, rate versus baseline) and `/trace <machine> [date]` (events with sources and corrections). `/waybill` is in SPEC-008. | MUST |
| SPEC-009-R08 | Commands MUST be owner-only and scoped to the owner's org. | MUST |
| SPEC-009-R09 | A `finding` row MUST be created when an anomaly is flagged or an issue is opened, with `detected_at`, and updated with `resolved_at` and a note when it is closed. The note records what was done. | MUST |
| SPEC-009-R10 | A `/findings [period]` command SHOULD list findings for pilot reviews. | SHOULD |
| SPEC-009-R11 | The digest MUST be split into several messages if it exceeds the Telegram message size limit (4096 characters), with the needs-attention block first. | MUST |
| SPEC-009-R12 | The digest MUST be complete and correct with the LLM disabled. The optional LLM headline (SPEC-006-R13) is the only LLM element. | MUST |
| SPEC-009-R13 | Each sent digest MUST be recorded in `digest_log` with a content hash. | MUST |
| SPEC-009-R14 | No further work on `logbuk-neo.html` in v1. It stays a demo surface. | MUST |

## 4. Interfaces and data
Tables: `digest_log`, `finding`, reads `effective_events`, derived signals (SPEC-004). Telegram inline callbacks for "Откуда?".

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-009-01 | Given an anomaly, an open issue and a missing log, then the needs-attention block lists all three first. | R01 | integration |
| AC-009-02 | Given the digest job runs twice for the same org and date, then one digest is delivered. | R02 | integration |
| AC-009-03 | Given a digest line "CAT-101: 12 ч", when the owner taps "Откуда?", then the source operator messages with timestamps are shown, reachable in at most two taps. | R05 | integration |
| AC-009-04 | Given a default baseline, then the line is labelled as default. | R03 | unit |
| AC-009-05 | Given a 25-machine fleet, then the digest is split below the message size limit and the needs-attention block is in the first message. | R11 | integration |
| AC-009-06 | Given an anomaly later resolved by an issue closure, then the finding has `detected_at`, `resolved_at` and a note. | R09 | integration |
| AC-009-07 | Given the LLM disabled, then the digest content is unchanged except for the absent headline. | R12 | integration |
| AC-009-08 | Given an operator sends `/today`, then a refusal. Given owner of org A, `/machine` for org B's alias, then not found. | R08 | integration |
| AC-009-09 | Given a digest, then its header states the time window. | R04 | unit |
| AC-009-10 | Given a derived rate, when the owner drills down, then its inputs are listed. A fact without evidence shows "не зафиксировано". | R06 | integration |
| AC-009-11 | Given `/today`, `/machine <alias>` and `/trace <machine> [date]`, then each output contains the elements listed in R07. | R07 | integration |
| AC-009-12 | Given findings in a period, then `/findings` lists them. | R10 | integration |
| AC-009-13 | Given a sent digest, then `digest_log` holds a content hash. | R13 | integration |
| AC-009-14 | Given the v1 diff, then `logbuk-neo.html` is unchanged. | R14 | manual |

## 6. Open questions
- **OQ-009-1:** Digest time and window (previous day versus today so far). Confirm with the pilot owner.
- **OQ-009-2:** How "what was done" gets into a finding note: from the operator's issue-resolution message, or an owner reply. Decide with the pilot owner.
- **OQ-009-3:** Whether `/trace` needs arguments beyond machine and date.
- **OQ-009-4:** Telegram does not expose read receipts, so "owner opens the digest" in the pilot success criteria needs a proxy (SPEC-013-R04).

## 7. Traceability
Scope §3 Pillar 4, §12, §15.1. ADR-0003, ADR-0008. Invariant 1. Related specs: SPEC-004, SPEC-006, SPEC-007, SPEC-008, SPEC-013.
