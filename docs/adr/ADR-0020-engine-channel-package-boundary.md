---
id: ADR-0020
title: Engine/channel package boundary — one-directional, one entry point
status: Accepted
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 2", "§15.4"]
specs: [SPEC-014, SPEC-018]
---

# ADR-0020: Engine/channel package boundary — one-directional, one entry point

## Context
`app/adapters/telegram_adapter.py` exists today, but it is a function-style adapter
with no bot process behind it, and it currently both returns a result and performs
the send itself (`telegram_adapter.py:92-101`, confirmed in
`MVP_ASSESSMENT_FOR_CLAUDE.md` §4). The Telegram bot is logically an interface layer
on top of the engine, deployed together with it for now, but the boundary needs to be
strict enough that the bot could later be split into its own service by moving one
package and replacing a function call with an HTTP call, without touching engine
logic.

## Decision
We will add a new `app/channels/` package, in the same repo and process as the
existing FastAPI app for now. The boundary is one-directional and goes through
exactly one entry point:
- the engine exposes **one** function, `handle_inbound(NormalisedInbound) ->
  list[OutboundMessage]`, which returns neutral replies and **never sends anything
  itself**;
- `app/channels/*` may call only that entry point, and may import only
  `app/channels/base.py` from the engine side;
- the engine (`app/core`, `app/services`, `app/db`, `app/rules`) MUST NEVER import
  `app/channels` or aiogram;
- a static import-boundary test enforces both directions (SPEC-014-R13, owned as a
  test by SPEC-018-R06).

The webhook is a route inside the same FastAPI app; polling is a separate entry point
(`python -m app.channels.telegram.polling`) sharing the same handler. The existing
`telegram_adapter.process_telegram_message` keeps working for the sandbox (its
`send_message_fn` side effect is not removed in this phase) until the human
explicitly retires it.

## Consequences
**Good:** the engine stays testable and reusable without any Telegram dependency
(REST sandbox and future MAX adapter use the same `handle_inbound`); splitting the
bot into its own service later is a deployment change, not a rewrite.
**Costs and risks:** two adapters (`telegram_adapter.py` for the sandbox,
`app/channels/telegram/` for the real bot) coexist for a transition period, which is
exactly the kind of duplication that caused the three-T4-reply-path problem this
project already has (`MVP_ASSESSMENT_FOR_CLAUDE.md` §5 item 7) — the retirement of
the old adapter must not be forgotten.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Split the bot into a separate service/process now | Premature — no pilot traffic yet to justify independent scaling or deployment; adds operational surface for a ~5-owner pilot. |
| Let `app/channels` import engine internals directly (no single entry point) | Exactly what makes a later split expensive, and what the import-boundary test exists to prevent. |

## Revisit when
Pilot scale or reliability needs (e.g. the bot needing independent restarts from the
API) justify actually splitting `app/channels` into its own deployable, at which
point this ADR's "same process" clause is superseded, not the entry-point contract.

## Enforced by
SPEC-014-R13. SPEC-018-R06. Tests AC-014-11, AC-018-05.
