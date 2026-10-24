---
id: ADR-0005
title: Immutability enforced in Postgres, corrections are new events
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 4", "§3 Pillar 2", "§14 inv. 9"]
specs: [SPEC-004, SPEC-011]
---

# ADR-0005: Immutability enforced in Postgres, corrections are new events

## Context
"Immutable, traceable record" is a core claim. A convention in application code can be broken by one bad migration or one tired late-night fix. Operators also make mistakes ("не 150, а 105") and the history must show both the mistake and the fix.

## Decision
1. The application database role has **no UPDATE and no DELETE** on `timeline_event`. Enforce with revoked grants and, as defence in depth, a trigger that raises on UPDATE or DELETE.
2. A correction is a **new event** whose `corrects_event_id` references the original. Projections (state, waybill, digest) read the latest event in a correction chain. The original stays visible in `/trace`.
3. Migrations that alter `timeline_event` run under a separate migration role, never the application role.

## Consequences
**Good:** immutability is a property of the database, testable in one line.
**Costs and risks:** fixing a bad row requires a compensating event, never an edit. Projection queries must resolve correction chains and need an index on `corrects_event_id`.

## Alternatives considered
| Option | Why not |
|---|---|
| Soft-delete flag | Still an UPDATE; the claim becomes convention again. |
| Hash-chained log | Stronger tamper evidence, but extra complexity for v1. Revisit if a customer asks for tamper evidence. |

## Revisit when
A customer or auditor needs cryptographic tamper evidence.

## Enforced by
SPEC-004-R05 to R08, SPEC-011-R05. Test AC-004-03, AC-004-04. Invariant 9.
