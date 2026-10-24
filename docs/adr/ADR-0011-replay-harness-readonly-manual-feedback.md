---
id: ADR-0011
title: Replay harness is read-only and the KPI and memory feedback loop is human-reviewed
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§6", "§10", "§14 inv. 8", "§15.3"]
specs: [SPEC-010]
---

# ADR-0011: Replay harness is read-only and the KPI and memory feedback loop is human-reviewed

## Context
The pitch diagram shows arrows from the replay harness back to State ("mem") and Policy ("KPI"). v1 has no real traffic yet and a solo builder. Automatic write-back would mean the system changes its own behaviour on unvalidated data, which contradicts "never appears smarter than its evidence".

## Decision
We will build the harness to **observe and measure everything and tune nothing automatically**. The replay CLI runs against a scratch database, never calls Telegram, never touches production tables. The builder reviews replay diffs and golden-set results, edits rules, thresholds or templates by hand and ships a new version stamp. The only automatic behaviour change is the LLM kill switch, driven by the validator rejection rate.

## Consequences
**Good:** a safe foundation for later learning, and a clear story for pitch accuracy ("human-reviewed feedback", not "self-improving").
**Costs and risks:** tuning is manual labour for the builder.

## Alternatives considered
| Option | Why not |
|---|---|
| Auto-tuned thresholds | Premature; no validated data. |
| No harness until later | Version drift and unreproducible decisions start on day one. |

## Revisit when
There is a validated golden set from real pilot messages and a concrete tuning candidate with a measured benefit.

## Enforced by
SPEC-010-R04 to R07, R13. Test AC-010-02, AC-010-03. Invariant 8.
