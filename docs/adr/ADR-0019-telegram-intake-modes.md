---
id: ADR-0019
title: Telegram intake modes — webhook and polling, selected by TELEGRAM_MODE
status: Accepted
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 2", "§13"]
specs: [SPEC-014]
---

# ADR-0019: Telegram intake modes — webhook and polling, selected by TELEGRAM_MODE

## Context
Inbound webhook reachability from Telegram to the VPS is **not yet verified** (fact
from the human, build prompt §"Facts from the human"). The bot token works outbound
from the VPS, but `getWebhookInfo`'s current state and `last_error_message` are
unknown. Local development has no public HTTPS endpoint for Telegram to call, so
webhook-only would block all local iteration.

## Decision
We will support **both** intake modes, selected by `TELEGRAM_MODE=polling|webhook`,
sharing the same handler code for both (SPEC-014-R01). Polling is the default for
local development. Webhook is the target for the VPS once reachability is verified.
The admin CLI (SPEC-014-R06) refuses to start polling in `BOT_ENV=prod` while a
webhook is currently registered, to prevent the two modes running against the same
token simultaneously (Telegram allows only one consumer per token at a time).

## Consequences
**Good:** local development never blocks on inbound HTTPS reachability; the webhook
path can be adopted on the VPS incrementally, with polling as an immediate fallback
if `getWebhookInfo` reachability testing fails.
**Costs and risks:** two code paths (poller loop vs. webhook route) must both stay
correct against the same handler; a misconfigured environment could run both at once
against the same token if the admin-CLI guard (SPEC-014-R06) is bypassed or broken.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Webhook only | Blocks local development entirely until a tunnel (ngrok or similar) is set up for every contributor; also risky given reachability is unverified. |
| Polling only, even in prod | Works regardless of reachability, but higher latency and an extra always-running process; webhook is the better production target once verified. |

## Revisit when
Inbound webhook reachability is verified on the VPS (`getWebhookInfo` shows no
`last_error_message` and a successful delivery is observed) — at that point, prod
defaults to webhook and polling becomes dev-only by convention, not by removing the
capability.

## Enforced by
SPEC-014-R01, R06. Tests AC-014-06.
