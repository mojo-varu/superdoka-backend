---
id: ADR-0006
title: Idempotent inbound handling keyed on channel and update id
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§8"]
specs: [SPEC-001, SPEC-011]
---

# ADR-0006: Idempotent inbound handling keyed on channel and update id

## Context
Telegram retries webhooks on timeouts or non-2xx responses. A retried "залил 150 литров" must never log fuel twice, because fuel totals feed the waybill and anomaly rules.

## Decision
Inbound `conversation_log` rows have a unique key on `(channel, update_id)`. The webhook handler inserts the inbound row first; on a unique violation it returns 200 immediately without running the pipeline. Outbound replies for a retried update are not re-sent.

## Consequences
**Good:** exactly-once effect from an at-least-once channel.
**Costs and risks:** a crash after the inbound insert but before the pipeline completes leaves a "received but unprocessed" row. The handler must mark processing state so a recovery job can finish or flag it.

## Alternatives considered
| Option | Why not |
|---|---|
| Dedupe in Redis with TTL | Loses guarantees after TTL or restart; the database already exists. |
| Dedupe at event level by payload hash | Two real identical messages ("150" twice) would collide. |

## Revisit when
A second channel with different id semantics is added (the key already includes `channel`).

## Enforced by
SPEC-001-R08 to R10, SPEC-011-R04. Test AC-001-05.
