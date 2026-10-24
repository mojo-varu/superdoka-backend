---
id: ADR-0026
title: Interim understanding backend — keep LLM-only extraction, add numeric grounding
status: Proposed
date: 2026-10-24
deciders: Varun
scope_refs: ["§4", "§5", "§13"]
specs: []
---

# ADR-0026: Interim understanding backend — keep LLM-only extraction, add numeric grounding

**Do not implement this ADR in this task.** This document records the decision and
its options for the human to approve; no code in Step 3 of the current build task
touches extraction backend selection.

## Context
No ONNX classifier or NER model files exist in this repo (re-verified 2026-10-24:
`find . -iname "*.onnx" -o -iname "*distilbert*"` returns nothing). Extraction runs
entirely through the LLM (`app/core/context_llm.py`), via `model_loader.py`'s
`llm_only` fallback mode (`model_loader.py:219`). `SHIPPABLE_SCOPE.md` §5 evaluated
two decision-model candidates: GLiNER2.5-Decide (open-weight, 340M params, CPU-local,
no stated Russian-language support — `SHIPPABLE_SCOPE.md` §5, OQ-013 item "GLiNER2.5-
Decide Russian support") and Jev (hosted API, already rejected in
`SHIPPABLE_SCOPE.md` §5 — "operator message text leaves your infrastructure," no
Russian evidence). ADR-0012 already gates GLiNER2.5-Decide adoption on a Russian
eval set that does not exist yet.

## Decision (pending)
**Recommendation:** keep LLM-only extraction for the Telegram bot validation slice,
and add one deterministic guardrail now, independent of which backend eventually
wins: every numeric entity the LLM extracts (fuel volume, hours) MUST appear in the
operator's raw message, after number-word normalisation ("сто пятьдесят" → `150`).
If a numeric entity in the LLM's output cannot be matched back to the raw text, the
system MUST NOT auto-commit it — it routes to CLARIFY instead of CONFIRM or AUTO,
regardless of the LLM's self-reported confidence. This directly targets the known
failure mode where the LLM over-reports confidence on fabricated or malformed numbers
(`context_llm.py:293-294`'s own comment: "The LLM tends to over-report confidence").

**Options recorded for the human to choose among, not decided here:**
1. **Restore the ONNX classifier/NER pair.** Fastest to re-enable if the original
   training artifacts still exist somewhere outside this repo; unknown current
   accuracy on real (non-synthetic) Russian operator messages — the 99.3% figure has
   no eval script backing it (see `SCOPE_SECTION2_EDITS.md`).
2. **Spike GLiNER2.5-Decide or a similar typed decision model** (per ADR-0012's
   existing gate): build a 200–300 message hand-labelled Russian eval set first;
   Russian support is unconfirmed and must be checked against the model card before
   investing further.
3. **Keep LLM-only, add numeric grounding** (the recommendation above). Lowest
   implementation cost; does not resolve the underlying question of whether LLM-only
   extraction is accurate enough at pilot scale, only bounds its failure mode on
   numbers specifically.

**Data residency, deliberately not decided here:** where the LLM actually runs
(local Ollama on the VPS vs. a Russian-hosted API vs. a foreign API) is ADR-0016's
question, already Proposed and open. This ADR's recommendation is backend-agnostic
on that axis — the numeric-grounding guardrail applies regardless of where the LLM
runs.

## Consequences
**Good (of the recommendation, if approved):** closes a known, named failure mode
(fabricated numbers) with a small, independently testable check, without blocking on
a model-selection decision that needs real pilot data to make well.
**Costs and risks:** does not improve intent or non-numeric entity accuracy at all;
if LLM-only extraction turns out to be the real accuracy bottleneck, this ADR's
recommendation only hides the most dangerous symptom (wrong numbers written as fact),
not the underlying cause.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Decide the backend now, before any real operator message exists | ADR-0012 already requires a Russian eval set with real pilot messages before adopting GLiNER2.5-Decide; deciding earlier would be a guess dressed as a decision. |
| Ship LLM-only with no additional guardrail | Leaves the known over-confidence-on-fabricated-numbers failure mode completely unmitigated going into a pilot where wrong fuel/hours numbers directly corrupt the waybill (Pillar 1). |

## Revisit when
A Russian eval set exists (per ADR-0012's gate) and real pilot message volume is
enough to measure LLM-only accuracy against it — at that point, options 1–3 above
can be compared on actual numbers instead of priors.

## Enforced by
Not yet — no spec owns this requirement today. If approved, it belongs in SPEC-003
(Understanding pipeline, existing Ready spec) as a new requirement; see
`docs/proposals/AMENDMENTS.md` for the proposed addition.
