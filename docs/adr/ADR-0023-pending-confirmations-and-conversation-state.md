---
id: ADR-0023
title: Pending confirmations and conversation state persisted in the database
status: Proposed
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 3", "§8"]
specs: [SPEC-004, SPEC-011, SPEC-015]
---

# ADR-0023: Pending confirmations and conversation state persisted in the database

## Context
`event_processor._write_events` currently commits a `TimelineEvent` and its specific
log row **before** checking whether `confidence_route == CONFIRM`, only setting
`needs_confirmation=True` afterward (`event_processor.py:426-430`, confirmed in
`MVP_ASSESSMENT_FOR_CLAUDE.md` §4). The record exists as fact before the operator has
agreed to it — a direct deviation from the commit-after-confirm model SPEC-004-R01/R02
already specify ("only confirmed events enter the timeline"). Separately,
`telegram_adapter.handle_callback_query`'s `"correct"` branch does not link to the
real correction endpoint at all (`telegram_adapter.py:143-147`) — it just asks the
operator to retype, so corrections never actually reference the original event via
this path. Both are the same underlying gap: there is nowhere today to hold a
proposed-but-unconfirmed value, or a chat's "I'm waiting for a correction" state,
other than the timeline itself or process memory.

## Decision
We will not write `TimelineEvent` until the operator confirms. CONFIRM-route and
implausible results are stored in a short-lived, mutable `pending_confirmation` table
(org, session, operator, machine, event type, payload, `source_conversation_id`,
`proposed_at`, `expires_at`). ✅ promotes the row to a real `TimelineEvent` by calling
the existing SPEC-004 write path; ✏️ stores `awaiting_correction` in a `chat_state`
table (org, chat_id, state_key, state_payload, `updated_at`) referencing the pending
or already-committed item — never in process memory. This keeps `timeline_event`
append-only (ADR-0005 is unaffected — nothing is ever written to it provisionally)
while fixing the commit-before-confirm deviation.

## Consequences
**Good:** `timeline_event` only ever holds confirmed facts, matching SPEC-004-R01/R02
and ADR-0005 for real, not just on paper; a worker or process restart does not lose a
pending confirmation or an in-progress correction, because neither lives in memory.
**Costs and risks:** `event_processor._write_events` needs a non-trivial refactor to
support two write paths (auto-commit vs. stage-then-promote); abandoned
`pending_confirmation` rows need an expiry/cleanup policy or they accumulate forever
(same class of bug as the `fuel_added_today` counter that never resets).

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Keep writing to `timeline_event` immediately and add a `confirmed` boolean column | Breaks "append-only, immutable" as the actual guarantee readers can rely on — a boolean flip is still a mutation of a supposedly immutable row, and `effective_events` (SPEC-004-R07) would need to filter on it everywhere, which is easy to forget once. |
| Hold pending state in Redis with a TTL | Redis is already in the stack as a cache, not a source of truth; losing a pending confirmation on a Redis restart is a worse failure mode than a Postgres row with an explicit expiry. |
| Hold `chat_state` in process memory | Explicitly ruled out by the build prompt and by SPEC-015-R13 — a worker restart would silently drop an in-progress correction and the operator would get no explanation. |

## Revisit when
The `pending_confirmation`/`chat_state` pattern needs to generalise to multi-step
flows beyond confirm/correct (for example a multi-field clarification wizard) — at
that point a more general conversation-state machine may be warranted instead of two
single-purpose tables.

## Enforced by
SPEC-015-R04, R06, R08, R13. SPEC-004 amendment (`docs/proposals/AMENDMENTS.md`) for
the `pending_confirmation` write path. Not yet implemented — this ADR and the
requirements above record the decision; Step 3 of the build process implements the
code and tests (AC-015-03, AC-015-04, AC-015-06, AC-015-09).
