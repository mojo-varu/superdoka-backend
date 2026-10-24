---
id: ADR-0024
title: Callback data contract — versioned, expiring, bound, idempotent
status: Proposed
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 3"]
specs: [SPEC-015]
---

# ADR-0024: Callback data contract — versioned, expiring, bound, idempotent

## Context
Telegram's inline-keyboard `callback_data` is a short opaque string with a platform
size limit, round-tripped back to the bot verbatim when tapped. Today's
`telegram_adapter._confirmation_keyboard` encodes callback data as a bare
`"confirm:{event_id}"` / `"correct:{event_id}"` string (`telegram_adapter.py:106-114`)
with no version marker, no expiry, and — critically — the `"correct"` branch of
`handle_callback_query` never actually calls the correction logic
(`telegram_adapter.py:143-147`), so even this minimal contract is not fully honoured
by its own handler today. ADR-0023 introduces `pending_confirmation` rows that
callbacks need to reference safely across double taps, staleness, and (once ADR-0023
ships) rows that may no longer exist.

## Decision
**Recommendation:** callback data is a short, versioned string of the form
`v<schema_version>:<action>:<pending_id>:<nonce>`, where:
- `schema_version` lets a future format change be rejected cleanly by old buttons
  still floating in a chat history, instead of mis-parsed;
- `action` is one of a small closed set (`confirm`, `correct`, ...);
- `pending_id` references exactly one `pending_confirmation` row (ADR-0023);
- `nonce` is bound to that row at creation time (not globally unique by itself) so a
  copied or replayed callback from a different context cannot act on someone else's
  pending item.

A tap is resolved by looking up `pending_id`, checking the row has not expired and
has not already been resolved, checking the `nonce` matches, and checking the
tapping chat owns the row. Any failure of these checks answers the callback with a
short, safe message and performs no state change (SPEC-015-R07) rather than raising
or silently no-op-ing. A second tap on an already-resolved `pending_id` is answered
"already recorded" (SPEC-015-R06), not reprocessed.

## Consequences
**Good:** double-tap and stale-tap safety become a single lookup-and-check function
reused by every button type, not re-implemented per action; the version prefix means
a future callback-format change does not need to purge every chat's existing inline
keyboards.
**Costs and risks:** the string must stay within Telegram's current callback-data
size limit — verify the exact byte limit against current Bot API documentation before
implementation, since this ADR does not pin an unverified number; adds one lookup
per callback tap, which is cheap but is a dependency the UI path did not have before.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Keep the current bare `"confirm:{event_id}"` format | No expiry, no ownership check, no version marker — exactly the gaps that let the current `"correct"` branch silently fail to do anything real. |
| Encode the full payload in `callback_data` (no DB lookup) | Telegram's size limit makes this infeasible for anything beyond a bare id, and it would duplicate `pending_confirmation`'s data in two places that could drift. |
| A signed/HMAC token instead of a DB-bound nonce | More cryptographic machinery than this scale needs; a DB-bound nonce with an ownership check is simpler and sufficient at ~50 operators. |

## Revisit when
The pilot shows callback round-trip latency (DB lookup per tap) is a real UX problem,
or a second action type needs cross-referencing multiple pending rows at once (the
single-`pending_id` design would need to generalise).

## Enforced by
SPEC-015-R05, R06, R07. Not yet implemented. Tests AC-015-04, AC-015-05 once built.
