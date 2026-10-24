---
id: SPEC-003
title: Understanding pipeline and decision-model spike
status: Ready
phase: 1
pillar: 3
scope_refs: ["§4", "§5", "§11 phase 2b", "§15.1"]
adrs: [ADR-0002, ADR-0012]
depends_on: [SPEC-011]
---

# SPEC-003: Understanding pipeline and decision-model spike

## 1. Purpose
Turn a raw message (text, or a transcript) into a typed, validated `Understanding` object with a confidence route. This is Tier 1. It informs the policy engine and never acts.

## 2. Scope and non-goals
**In:** Signal normaliser, intent classification, entity extraction, schema validation, confidence scoring, plausibility flag, the time-boxed decision-model spike.
**Out:** deciding actions (SPEC-005), writing events (SPEC-004), speech-to-text (SPEC-002).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-003-R01 | The Signal normaliser MUST normalise safety (control characters, length cap), format (unicode, whitespace) and language (Russian is supported; other languages get a template reply asking for Russian). | MUST |
| SPEC-003-R02 | Russian number words ("сто пятьдесят", "двенадцать с половиной") MUST be normalised to numeric values before or during entity extraction. | MUST |
| SPEC-003-R03 | Intent classification MUST use the Tier 1 ONNX classifier and return a label and a probability. The intent set is the existing set in code (see OQ-003-1). | MUST |
| SPEC-003-R04 | Entity extraction MUST return typed slots: fuel (litres), hours or meter reading, machine alias, issue description, time reference. Units MUST be normalised. | MUST |
| SPEC-003-R05 | Each intent MUST declare required slots in a schema. Missing or invalid required slots MUST set `needs_clarification` and the missing slot names. For example `fuel_log` requires a numeric fuel entity. | MUST |
| SPEC-003-R06 | A plausibility check MUST compare numeric slots with per-machine-class bounds from configuration and set `implausible=true` with the reason. The check only flags. Policy decides the question. | MUST |
| SPEC-003-R07 | The Understanding package MUST be free of side effects. It MUST NOT write `timeline_event`, change state or choose actions. A static check MUST enforce that it imports no state writers. | MUST |
| SPEC-003-R08 | Confidence scoring MUST route to `accept`, `clarify` or `route_other` using configurable thresholds. Thresholds are tuned against the golden set and stamped in the version stamp. | MUST |
| SPEC-003-R09 | Off-topic messages MUST resolve to intent `off_topic`, receive a T4 template reply, and create no event. They are still logged in `conversation_log`. | MUST |
| SPEC-003-R10 | The decision-model spike MUST start with a model-card read and a zero-shot Russian smoke test. If Russian clearly fails, the spike is closed and recorded in ADR-0012. | MUST |
| SPEC-003-R11 | An eval set of hand-labelled Russian messages (starting around 200 to 300) MUST exist in version control with labels for intent, exact numeric entities and clarification need, including real pilot messages and voice transcripts when available. | MUST |
| SPEC-003-R12 | The spike MUST compare three arms: the current stack, GLiNER2.5-Decide zero-shot, and GLiNER2.5-Decide with LoRA. Metrics: numeric-entity exactness, intent accuracy, latency p50 and p95, and RAM on the **target VPS**. | MUST |
| SPEC-003-R13 | Adopt only if the candidate matches or beats the current stack on numeric-entity exactness and intent accuracy and fits RAM and latency. The decision and numbers MUST be recorded as an amendment to ADR-0012. | MUST |
| SPEC-003-R14 | If adopted, the model MUST sit behind the same `Understanding` interface so policy and storage are unchanged, and its hash MUST be added to the version stamp (SPEC-010-R02). | MUST |

## 4. Interfaces and data
`Understanding {intent, intent_prob, entities[], route, needs_clarification, missing_slots[], implausible, reasons[], model_hashes}`. Persisted into `conversation_log` columns (SPEC-011-R03).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-003-01 | "залил сто пятьдесят литров" yields fuel 150 L. "двенадцать с половиной часов" yields 12.5 h. | R02, R04 | unit, golden |
| AC-003-02 | "заправился" with no amount yields intent `fuel_log`, `needs_clarification`, missing `fuel`. | R05 | unit |
| AC-003-03 | "залил 5000 литров" yields `implausible=true`. | R06 | unit |
| AC-003-04 | "как дела у Васи?" yields `off_topic`, a T4 template reply, no event, one log row. | R09 | integration |
| AC-003-05 | A message in English gets a Russian-only reply template. | R01 | unit |
| AC-003-06 | A static check shows no import of timeline writers inside the understanding package. | R07 | unit (static) |
| AC-003-07 | A spike report exists with the three-arm table, VPS RAM and latency, and an adopt-or-reject line in ADR-0012. | R10 to R13 | manual |
| AC-003-08 | Given classifier probabilities above and below the configured thresholds, then the route is `accept` or `clarify`, and thresholds appear in the version stamp. | R03, R08 | unit |
| AC-003-09 | Given a decision model is adopted behind the interface, then policy and storage tests pass unchanged and its hash appears in the version stamp. Not applicable if the spike rejects it. | R14 | integration |

## 6. Open questions
- **OQ-003-1:** List the current intents and entity types from the repo (`NER handler`, `context_prompt.py`) and freeze them in an appendix of this spec. Owner: Varun, before Ready review.
- **OQ-003-2:** Plausibility bounds per machine class. Start with generous bounds and tighten from real data.
- **OQ-003-3:** Confidence thresholds. Tune after the golden set has real messages.
- **OQ-003-4:** Does GLiNER2.5-Decide support Russian? Read the model card first (huggingface.co/fastino/GLiNER2.5-Decide). Blocks the spike.

## 7. Traceability
Scope §4, §5, §11 phase 2b, §15.1. ADR-0002, ADR-0012. Invariant 5. Related specs: SPEC-002, SPEC-005, SPEC-010.
