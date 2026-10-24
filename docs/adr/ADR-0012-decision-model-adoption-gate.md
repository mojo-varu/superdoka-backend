---
id: ADR-0012
title: Decision-model adoption is gated by a Russian eval set, Jev is not adopted
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§5", "§11 phase 2b"]
specs: [SPEC-003]
---

# ADR-0012: Decision-model adoption is gated by a Russian eval set, Jev is not adopted

## Context
Two recent sources point at constrained decision models. Findings from reading both on 2026-10-03:
- **GLiNER2.5-Decide** (Fastino): 340M parameters, Apache 2.0, runs on CPU, typed-question schemas with joint constrained decoding, LoRA supported, 167.3 ms p50 on a 48-vCPU Xeon, 60.1% on Fastino's own internal 17-dataset suite. **Russian support is not stated.**
- **Jev** (TypeSafe AI): typed decision model, accessed through a hosted API; probably not open weight (an inference). Operator text would leave our infrastructure.

## Decision
1. **GLiNER2.5-Decide** gets a time-boxed spike (phase 2b) after the Pillar 2 text flow works. Adopt it only if it matches or beats the current ONNX stack on numeric-entity exactness and intent accuracy on a hand-labelled Russian eval set (start around 200 to 300 messages, including real pilot messages and voice transcripts), **and** fits RAM and latency on the target VPS. Compare three arms: current stack, zero-shot, LoRA.
2. First step before any work: read the model card and run a zero-shot Russian smoke test. If Russian clearly fails, close the spike.
3. **Jev** is not adopted in v1. Borrow the pattern only: a cheap typed decision step before generation, with probabilities that code acts on.
4. Whatever model is used stays Tier 1 (ADR-0002).

## Consequences
**Good:** no commitment before evidence. The eval set is reusable for the golden set.
**Costs and risks:** the eval set costs labelling time. Latency measured on a different machine may mislead; measure on the target VPS.

## Alternatives considered
| Option | Why not |
|---|---|
| Adopt now on benchmark claims | The benchmark is internal and not Russian. |
| Fine-tune our own classifier further | Not in v1 beyond the optional LoRA spike (§10). |

## Revisit when
The eval set exists, or a Russian-capable open model appears.

## Enforced by
SPEC-003-R10 to R13. Test AC-003-07.
