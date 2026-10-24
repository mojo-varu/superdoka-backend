---
id: SPEC-010
title: Minimal foundational harness (log, version stamps, replay, golden set, metrics)
status: Ready
phase: 0
pillar: 5
scope_refs: ["§6", "§10", "§14 inv. 8", "§15.3"]
adrs: [ADR-0004, ADR-0011, ADR-0003]
depends_on: [SPEC-011]
---

# SPEC-010: Minimal foundational harness (log, version stamps, replay, golden set, metrics)

Phase 0 builds H1 and H2. Phase 5 builds H3 to H5.

## 1. Purpose
Observe and measure everything now, tune nothing automatically. Every decision can be replayed and compared across versions, and the metrics that guard the LLM are computed from the log.

## 2. Scope and non-goals
**In:** ConversationLog, version stamps, replay CLI, golden set, metrics, kill-switch input.
**Out:** automatic write-back to state or policy, auto-tuned thresholds, memory compression (all later).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-010-R01 | **H1.** `conversation_log` MUST hold one row per inbound message and one per outbound reply, linked, with the columns listed in SPEC-011-R03. | MUST |
| SPEC-010-R02 | **H2.** Every row MUST record the version stamp: classifier hash, NER hash, decision-model hash (nullable), template-set version, rules version, prompt version, LLM model id. | MUST |
| SPEC-010-R03 | A correlation id MUST flow from the webhook through the pipeline into every log row and structured log line. | MUST |
| SPEC-010-R04 | **H3.** `replay --from <ts> --to <ts> [--org <id>]` MUST re-feed logged inbound messages through the current pipeline in a scratch database and diff intent, entities, policy action and reply against the log. | MUST |
| SPEC-010-R05 | The replay MUST NOT call Telegram, MUST NOT touch production tables, and MUST read the source log through a read-only role. | MUST |
| SPEC-010-R06 | Deterministic stages MUST reproduce exactly. Any difference is reported as a changed decision. | MUST |
| SPEC-010-R07 | LLM turns MUST be compared only on validator verdict and fallback behaviour. | MUST |
| SPEC-010-R08 | The replay report MUST list changed decisions with before and after, plus summary counts, and MUST support a `--fail-on-diff` flag for use before shipping. | MUST |
| SPEC-010-R09 | **H4.** A golden set of regression cases (input, expected intent, entities, policy action) MUST exist in version control and run on every change to rules, models or templates. It is seeded from the sandbox simulation and extended with real, anonymised pilot messages. | MUST |
| SPEC-010-R10 | The three day-one behaviours (shift-start recall, sanity challenge, close-out prompt) MUST be mandatory golden cases. Corrections, voice echo-confirm, idempotent retry and off-topic SHOULD also have cases. | MUST |
| SPEC-010-R11 | Real messages MUST be anonymised before entering the golden set (operator names, state numbers) and collected only with consent (SPEC-013-R02). | MUST |
| SPEC-010-R12 | **H5.** The following metrics MUST be computed from the logs: LLM fallback rate, validator rejection rate, operator correction rate (corrections divided by confirmed events), clarification depth, voice confirm-reject rate. A CLI command MUST print them for an org and date range. | MUST |
| SPEC-010-R13 | The harness MUST NOT write to rules, thresholds, models, templates or state. The only automatic behaviour change allowed is the LLM kill switch driven by the validator rejection rate (SPEC-006-R08). | MUST |
| SPEC-010-R14 | Definition of done: replaying a day of pilot traffic produces a report with one command, and a deliberate rules change appears in the report. | MUST |

## 4. Interfaces and data
CLI: `replay`, `metrics`, `golden`. Golden file format: one case per entry with `id`, `input`, `context` (state fixture), `expected`. Tables: `conversation_log` (SPEC-011).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-010-01 | Given a message, then inbound and outbound rows exist, linked, with a populated version stamp and correlation id. | R01, R02, R03 | integration |
| AC-010-02 | Given a day of logged traffic, when `replay` runs, then the report is produced, production tables are unchanged, and no Telegram call is made. | R04, R05 | integration |
| AC-010-03 | Given a deliberate rules change, then the replay report lists the changed decisions. Given no change, then zero diffs on deterministic stages. | R06, R14 | integration |
| AC-010-04 | Given an LLM turn in the log, then replay compares only the validator verdict and fallback. | R07 | integration |
| AC-010-05 | Given a rules change that breaks a golden case, then the golden run fails. | R09, R10 | integration |
| AC-010-06 | Given a day of logs with known counts, then each metric equals the hand-computed value. | R12 | unit |
| AC-010-07 | Given a static scan of harness code, then no write paths target rules, models, templates or state. | R13 | unit (static) |
| AC-010-08 | Given a replay with and without differences, then `--fail-on-diff` exits non-zero only when differences exist. | R08 | integration |
| AC-010-09 | Given a fixture with names and state numbers, then the anonymiser removes them, and a message without consent is not added to the golden set. | R11 | unit |

## 6. Open questions
- **OQ-010-1:** Golden file format (YAML versus JSONL) and where it lives. Pick one in phase 0.
- **OQ-010-2:** Anonymisation procedure details for state numbers and names. Document before the pilot.
- **OQ-010-3:** How to scratch-restore LLM-dependent state for replay if prompts change. The scope compares verdicts only, which sidesteps it.

## 7. Traceability
Scope §6, §10, §14, §15.3. ADR-0003, ADR-0004, ADR-0011. Invariant 8. Related specs: SPEC-003, SPEC-005, SPEC-006, SPEC-011, SPEC-013.
