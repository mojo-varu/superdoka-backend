---
id: ADR-0021
title: Deployment environments and bot tokens — separate dev/prod, deployed twice
status: Accepted
date: 2026-10-24
deciders: Varun
scope_refs: ["§9", "§13"]
specs: [SPEC-014, SPEC-016]
---

# ADR-0021: Deployment environments and bot tokens — separate dev/prod, deployed twice

## Context
Target scale is small — about 5 fleet owners and about 50 operators (fact from the
human). There are already two running surfaces referenced by the build prompt: the
existing demo sandbox at `https://demo.superdoka.ru/sandbox.html` (must not be
touched by this work) and the production instance for real pilot operators. Using
one bot token across both would let local development or demo traffic reach real
operators' chats, or vice versa.

## Decision
We will use **separate dev and prod bot tokens** (`TELEGRAM_BOT_TOKEN_DEV`,
`TELEGRAM_BOT_TOKEN_PROD` — both already present as keys in `.env`, confirmed to
exist without reading their values). The same codebase is **deployed twice**: the
existing demo instance and a new production instance, each with its own database and
Docker Compose project, with no shared running process between them. `BOT_ENV`
(`dev`|`prod`) selects which token and database a given deployment uses; it is never
inferred from `TELEGRAM_MODE`, since a dev token can run in either polling or
webhook mode locally.

## Consequences
**Good:** a bug or load spike in demo/dev traffic cannot reach real operators; token
rotation (SPEC-016-R08) is scoped per environment; the admin CLI's prod/polling guard
(SPEC-014-R06) has a reliable signal (`BOT_ENV`) to check.
**Costs and risks:** two Compose projects and two databases to operate instead of
one; migrations and config changes must be applied twice, in sequence, not assumed
to propagate automatically.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| One token, feature-flagged "test mode" | A single token is still one Telegram-side identity; a flag does not stop a misconfigured dev deploy from webhooking against real operator chats. |
| One shared database with an environment column | Breaks the "disposable local database only" rule for dev work (build prompt ground rules) and risks a dev migration touching real pilot data. |

## Revisit when
A second fleet owner or a genuinely multi-tenant hosting need arises — at that point
tenancy (ADR-0013) plus this environment split need to be reconciled explicitly,
not assumed compatible by default.

## Enforced by
SPEC-014-R06 (prod/polling guard uses `BOT_ENV`). SPEC-016-R08 (token rotation per
environment). No new acceptance scenario beyond those two — this ADR is primarily an
operational/deployment decision, verified by the deploy runbook (SPEC-017-R05).
