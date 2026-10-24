---
id: ADR-0025
title: Outbound delivery policy — minimal send wrapper now, outbox later
status: Proposed
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 2", "§9"]
specs: [SPEC-014]
---

# ADR-0025: Outbound delivery policy — minimal send wrapper now, outbox later

## Context
Today's `telegram_adapter.process_telegram_message` sends a reply via a bare
`send_message_fn(...)` call with no splitting, no `retry_after` handling, no
blocked-user handling, and no timeout (`telegram_adapter.py:92-101`). At ~5 owners /
~50 operators, message volume is low enough that a full transactional outbox
(durable queue, exactly-once delivery guarantees, dead-letter handling) is more
machinery than the problem currently needs, but *zero* resilience is not acceptable
either — a rate-limited or blocked-user send must not crash the worker or silently
vanish without a log trace.

## Decision
**Recommendation:** build one minimal send wrapper now (SPEC-014-R08 to R12): split
long text at paragraph boundaries under the platform limit, escape or avoid
`parse_mode` injection, retry on `retry_after` up to a small fixed cap and then log
and drop, mark the user unreachable on a blocked-user error, and apply a timeout
shorter than the pipeline timeout. This wrapper does **not** persist outbound
messages durably before sending — a crash between "pipeline decided the reply" and
"send succeeded" can lose that one reply, logged but not retried after a restart.
Defer a full transactional outbox (an `outbox` table, at-least-once delivery with
idempotent re-send, explicit dead-letter queue) until pilot traffic volume or
reliability requirements justify the added complexity.

## Consequences
**Good:** ships the resilience that actually matters at this scale (rate limits,
blocked users, oversized text) without building durable-queue machinery no one has
needed yet; the wrapper is a single, testable function (SPEC-018-R02's fake Bot API
exercises exactly this).
**Costs and risks:** a reply genuinely can be lost on a crash mid-send with no
automatic retry after restart — acceptable at pilot scale (an operator can always
just send the message again and get a fresh reply) but must not be described as
"resilient" in any pilot-facing material it is not.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Full transactional outbox now | Build prompt explicitly defers this ("A full outbox is deferred"); no evidence yet that pilot scale needs it. |
| No resilience at all (bare send call, as today) | Already known to be insufficient — a single rate-limit response or blocked user currently has no defined handling and risks crashing the worker. |

## Revisit when
Pilot traffic shows reply loss on crash is actually happening and mattering (not
hypothetically), or delivery volume grows past what a few owners/operators generate,
at which point SPEC-014 should be amended to add a proper `outbox` table per
SPEC-011's conventions.

## Enforced by
SPEC-014-R08 to R12. Tests AC-014-08, AC-014-09, AC-014-10.
