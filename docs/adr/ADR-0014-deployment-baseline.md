---
id: ADR-0014
title: Single VPS with Docker Compose and Postgres, no new infrastructure in v1
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§9"]
specs: [SPEC-012]
---

# ADR-0014: Single VPS with Docker Compose and Postgres, no new infrastructure in v1

## Context
Solo, bootstrapped, two-week pilot with a handful of operators. The existing sandbox already runs under Docker Compose with Postgres and ONNX models on CPU.

## Decision
One VPS, Docker Compose, Postgres. Add Redis only if the current code already uses it. No Kubernetes, queues or managed services beyond what the pilot needs. Operational baseline: nightly encrypted `pg_dump` copied off the server with one tested restore, health and error alerts to the builder's own Telegram chat, structured logs with correlation id, manual invoicing. Measure RAM with all models loaded before choosing a plan.

## Consequences
**Good:** minimal ops load and cost.
**Costs and risks:** single point of failure. Acceptable for a pilot; the restore test is mandatory.

## Alternatives considered
| Option | Why not |
|---|---|
| Managed Postgres and container platform | Cost and data-location questions (ADR-0016) with no pilot-scale benefit. |

## Revisit when
Pilot succeeds and a second paying customer arrives.

## Enforced by
SPEC-012-R01 to R08.
