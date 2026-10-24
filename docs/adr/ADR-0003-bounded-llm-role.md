---
id: ADR-0003
title: LLM restricted to a verbalisation allowlist behind validator, timeout and kill switch
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§4", "§11 gate", "§14 inv. 3, 6, 10"]
specs: [SPEC-006, SPEC-010, SPEC-009]
---

# ADR-0003: LLM restricted to a verbalisation allowlist behind validator, timeout and kill switch

## Context
The LLM is kept in the product so replies can sound natural in context, but it must not invent facts or choose actions. A small local model on CPU is slow and variable.

## Decision
The LLM may only **verbalise** a structured payload that policy and templates have already decided.

**Allowlist (v1):**
1. The T3, T5, T6 and T7 families: contextual clarification, anomaly question, proactive phrasing, shift summary.
2. An optional one-line owner-digest headline, behind a feature flag that defaults to off.

**Exclusions:** T1, T2, T4 and T8 are template-only. The LLM never selects a policy action, never reads raw history, never emits a number absent from its payload.

**Guardrails, all required before go-live:**
- every output passes the response validator (numbers and named entities must exist in the payload); failure means silent template fallback;
- live path timeout (starting value 4 s) then template fallback; proactive and digest paths are asynchronous;
- kill switch: config flag plus automatic trip when the validator rejection rate exceeds a threshold over a rolling window;
- every call logged with model id, prompt version, latency and validator verdict.

The LLM verbaliser does **not** go live until the validator, kill switch and replay CLI exist.

## Consequences
**Good:** natural language where it helps, with a hard ceiling on harm. Turning the LLM off leaves a working product.
**Costs and risks:** fallback templates must exist for every allowlisted type, so template work is not optional. Threshold values are unknown until real traffic exists.

## Alternatives considered
| Option | Why not |
|---|---|
| No LLM at all | Rejected by the product owner; templates alone feel robotic for clarification and summaries. |
| LLM for understanding too | Moves decision-relevant extraction into a non-auditable component. |
| Fine-tuned agency LLM | Not in v1 (§10); the run never completed. |

## Revisit when
Real transcripts exist and a fine-tuned verbaliser is proposed (post-pilot candidate), or the allowlist needs a new entry. Either requires updating this ADR first (invariant 10).

## Enforced by
SPEC-006-R03 to R10, SPEC-010-R12. Test AC-006-03 to AC-006-07.
