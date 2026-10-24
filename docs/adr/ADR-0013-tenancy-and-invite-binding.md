---
id: ADR-0013
title: Multi-tenancy by org_id on every table, operators bound through invite deep links
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§8"]
specs: [SPEC-001, SPEC-011]
---

# ADR-0013: Multi-tenancy by org_id on every table, operators bound through invite deep links

## Context
There is no tenant isolation today. A second customer cannot be onboarded safely without it. Operators must be onboarded in under two minutes using only a link, with no behaviour change.

## Decision
1. Every table carries `org_id`, and every query is scoped by it through a single data-access layer. Cross-org reads are impossible by construction in application code, and covered by a test that attempts them.
2. The owner registers with `/start <owner code>`. The owner adds machines by CSV or chat command, then generates operator invites.
3. An invite is a deep link `t.me/<bot>?start=<invite_token>` linking a `chat_id` to an operator and org. Tokens are single-use and expire.
4. A session cannot open without a machine.

## Consequences
**Good:** safe to onboard customer two. Binding is one tap.
**Costs and risks:** the owner code needs a secure issuance channel (manual for the first customers). Row-level security in Postgres is an option if application-layer scoping proves error-prone.

## Alternatives considered
| Option | Why not |
|---|---|
| Schema per tenant | Operational overhead for a solo builder. |
| Phone-number login | Needs extra permissions and friction. |

## Revisit when
More than a handful of tenants, or any cross-org data leak in tests.

## Enforced by
SPEC-001-R04 to R07, SPEC-011-R01, R02, R10. Test AC-001-03, AC-011-01.
