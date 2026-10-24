---
id: ADR-0002
title: Tiered decision stack, deterministic core decides
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§4", "§5", "§14 inv. 5"]
specs: [SPEC-003, SPEC-005, SPEC-006]
---

# ADR-0002: Tiered decision stack, deterministic core decides

## Context
The product promise is "never appears smarter than its evidence". Learned components are useful for understanding messy language but are not auditable as decision makers. The LLM prototype (`qwen2.5:3b-instruct`, prompt-only) was inconsistent on off-topic replies.

## Decision
We will use three tiers with a strict direction of authority.
- **Tier 0, deterministic:** state machine, rules, templates, schema validation, the policy engine. Decides what happens.
- **Tier 1, learned but constrained:** ONNX intent classifier and NER, and optionally a decision model (ADR-0012). Emits typed outputs with probabilities.
- **Tier 2, bounded LLM:** adapts language only (ADR-0003).

Tier 1 outputs are **inputs to policy rules**. Tier 1 never writes state and never selects an action.

## Consequences
**Good:** every action is explainable by a rule and a logged input. The product works with Tiers 1 and 2 degraded.
**Costs and risks:** rules need maintenance, and wrong Tier 1 output still causes wrong rule inputs, which is why confidence routing and the golden set exist.

## Alternatives considered
| Option | Why not |
|---|---|
| LLM-orchestrated agent loop | Not auditable, not replayable, conflicts with the closed-domain design. |
| Classifier writes state directly | Removes the human-readable decision point. |

## Revisit when
Never for authority direction. Individual Tier 1 models may change (ADR-0012).

## Enforced by
SPEC-003-R07, SPEC-005-R01, R02, SPEC-006-R01. Invariant 5.
