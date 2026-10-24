---
id: SPEC-006
title: Supervisor execution, templates, bounded LLM verbaliser, validator, kill switch
status: Ready
phase: 6
pillar: 3
scope_refs: ["§4", "§11 gate", "§14 inv. 3, 6, 10"]
adrs: [ADR-0002, ADR-0003, ADR-0016]
depends_on: [SPEC-005, SPEC-010]
---

# SPEC-006: Supervisor execution, templates, bounded LLM verbaliser, validator, kill switch

Templates and the validator are built early (phase 1 and phase 5). **LLM go-live is phase 6 and is gated** (R14, ADR-0016).

## 1. Purpose
Turn a `PolicyDecision` into a Russian reply. Templates produce every reply. The LLM may only rephrase a small allowlist of reply types, and any LLM text that adds a fact is replaced by the template.

## 2. Scope and non-goals
**In:** template engine, LLM verbaliser, response validator, timeout, kill switch, call logging, digest headline flag.
**Out:** choosing actions (SPEC-005), hosting decision (ADR-0016), fine-tuned models (not in v1).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-006-R01 | A registry MUST map each task type to `template_only` or `llm_allowed`. T1, T2, T4 and T8 MUST be `template_only`. The LLM MUST NOT be invoked for them, enforced in code. | MUST |
| SPEC-006-R02 | Every task type MUST have at least one Russian template with named slots filled from the decision payload. A missing slot MUST cause a safe generic fallback and an error log. A raw placeholder MUST never reach a user. | MUST |
| SPEC-006-R03 | The LLM verbaliser input MUST be a structured payload only. It MUST NOT receive raw conversation history. | MUST |
| SPEC-006-R04 | LLM output MUST be one or two sentences in Russian. | MUST |
| SPEC-006-R05 | The response validator MUST run on every LLM output. Every number and named entity in the output MUST exist in the input payload. On failure the template reply is sent silently and the verdict is logged. | MUST |
| SPEC-006-R06 | The live path MUST time out (starting value 4 s) and then send the template reply. | MUST |
| SPEC-006-R07 | Proactive and digest paths are asynchronous and MAY wait longer (configured limit), still falling back to the template on timeout. | MUST |
| SPEC-006-R08 | A kill switch MUST exist as a config flag and as an automatic trip when the validator rejection rate exceeds a threshold over a rolling window. A tripped switch stays off until manually reset and alerts the builder. | MUST |
| SPEC-006-R09 | Every LLM call MUST be logged with model id, prompt version, latency, validator verdict and `reply_source` (`template`, `llm`, `fallback`). | MUST |
| SPEC-006-R10 | With the LLM disabled or unreachable every reply path MUST still produce a valid reply. The full test suite MUST pass with the LLM disabled. | MUST |
| SPEC-006-R11 | LLM payloads SHOULD be minimised: no chat ids, no free-text history, only the facts needed for phrasing. | SHOULD |
| SPEC-006-R12 | The LLM MUST be called through an `LlmClient` interface. The hosting option is decided in ADR-0016. | MUST |
| SPEC-006-R13 | The optional digest headline MUST sit behind a feature flag that defaults to off. Its numbers MUST come from computed facts and pass the validator. | MUST |
| SPEC-006-R14 | **Go-live gate.** The LLM verbaliser MUST NOT be enabled in production until the validator, kill switch and replay CLI exist with passing tests. | MUST |
| SPEC-006-R15 | The validator MUST also reject output that introduces a command, a link, or an instruction not in the payload. | MUST |

## 4. Interfaces and data
`Template` registry, `Verbaliser.render(decision) -> Reply(text, reply_source)`, `Validator.check(output, payload) -> Verdict`. Columns `reply_source`, `validator_verdict`, `latency_ms` on `conversation_log`.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-006-01 | Given a T4 decision, then the LLM client is never called (mock asserts zero calls). | R01 | unit |
| AC-006-02 | Given a template with a missing slot, then a generic fallback is sent and an error is logged, never "{fuel}". | R02 | unit |
| AC-006-03 | Given LLM text with a number not in the payload, then the template is sent, `reply_source=fallback`, verdict `rejected`. | R05 | unit |
| AC-006-04 | Given the LLM takes longer than the timeout, then the template is sent within the timeout plus overhead. | R06 | integration |
| AC-006-05 | Given the rejection rate exceeds the threshold over the window, then the kill switch trips, the builder is alerted, and later replies are template-only. | R08 | integration |
| AC-006-06 | Given every LLM call, then a log row has model id, prompt version, latency and verdict. | R09 | integration |
| AC-006-07 | Given LLM text with an invented link, then it is rejected. | R15 | unit |
| AC-006-08 | Given the suite is run with the LLM disabled, then all tests pass. | R10 | integration |
| AC-006-09 | Given the validator, kill switch or replay CLI is missing in config or code, then the LLM-enabled flag cannot be set in production. | R14 | integration |
| AC-006-10 | Given the `Verbaliser` input type, then it has no field for conversation history (contract test). | R03 | unit |
| AC-006-11 | Given LLM output of three sentences or non-Russian text, then the template is sent and the verdict is `rejected`. | R04 | unit |
| AC-006-12 | Given a digest or proactive path with a slow LLM, then it waits up to the async limit and then sends the template. | R07 | integration |
| AC-006-13 | Given an LLM payload, then it contains no chat id and no free-text history. | R11 | unit |
| AC-006-14 | Given the test suite, then no provider SDK is imported outside the `LlmClient` adapter, and a fake client is swapped in tests. | R12 | unit (static) |
| AC-006-15 | Given the headline flag off, then no LLM call occurs for the digest. Given on, then headline numbers match computed facts or the headline is dropped. | R13 | integration |

## 6. Open questions
- **OQ-006-1:** LLM hosting (ADR-0016). Blocks phase 6.
- **OQ-006-2:** Rejection-rate threshold and window. Tune from real data; start conservative.
- **OQ-006-3:** Entity matching in the validator for Russian inflection (for example machine alias with case endings). Use normalised forms and test with golden cases.

## 7. Traceability
Scope §4, §11 gate, §14. ADR-0002, ADR-0003, ADR-0016. Invariants 3, 6, 10. Related specs: SPEC-005, SPEC-009, SPEC-010.
