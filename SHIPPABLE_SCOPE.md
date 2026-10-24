# SuperDoka v1 — Shippable Scope

**Product:** SuperDoka (the product name for VFM). Code identifiers may stay `vfm_*`. Do not rename in v1.
**Status date:** 2026-10-03
**Builder:** Varun, solo, bootstrapped
**Companion docs:** PROJECT_BRIEF.md, ARCHITECTURE_VERBALIZED.md, ARCHITECTURE_RATIONALE.md, BACKEND_EVOLUTION.md, SANDBOX_INTEGRATION.md

## 0. How to use this document

This document decides what ships in v1. Where it conflicts with BACKEND_EVOLUTION.md or SANDBOX_INTEGRATION.md on priority, this document wins. The invariants in ARCHITECTURE_VERBALIZED.md ("What Claude Code must never do") still bind every change. Section 14 adds v1-specific invariants.

If a task is not traceable to one of the five pillars in section 3, it is out of scope for v1.

The testable breakdown of this document lives in `docs/` (specs, ADRs and a traceability matrix). Start at `docs/README.md`.

---

## 1. Product in one paragraph

Operators chat with a Telegram bot (text or voice note) the way they would tell a foreman. SuperDoka understands the update in the context of that machine and shift, confirms or asks one question, and writes an immutable, traceable record. From those records the owner automatically receives a completed waybill-style record (a digital ЭСМ-2) and a daily digest. The operator learns nothing new and changes no behaviour.

**Positioning:** a digital ЭСМ-2 that fills itself from conversation, plus a supervisor that notices what the paper form never could.

**Wording rule:** until legal acceptability is verified (section 13), say "waybill companion" or "digital waybill record". Never claim it replaces or is legally equivalent to the official form.

**Non-goals for v1:** enterprise features, a dashboard product, multi-channel parity, fine-tuned models, self-tuning policy.

---

## 2. Where things stand today

From this project's own history, corrected 2026-10-24 against a direct code audit.
See `docs/proposals/SCOPE_SECTION2_EDITS.md` for the evidence behind each change below.
Verify against the repo before relying on any line.

**Working**
- Sandbox pipeline end to end through `POST /api/v1/vfm/update`
- Intent and entity extraction — **LLM-only** (see below; not the ONNX classifier/NER
  pair this section previously claimed)
- T1/T2 template replies for the common paths (confirmations, single-field clarification)
- Machine state tracking (fuel, hours, issues), basic anomaly flag
- Standalone state-graph runner (7 scenarios) and a 14-day fleet simulation script

**Not working or not built**
- Telegram and MAX integrations were "in progress", not live. No real user has used the system.
- No voice, no tenant isolation, no onboarding, no waybill output, no digest, no scheduler.
  The watcher process runs, but its nudge delivery is an unimplemented stub
  (`watcher.py:194`, `# TODO: send via adapter`; `_get_owner_settings` always returns
  `None`, `watcher.py:189-191`).
- **No ONNX classifier or NER model files exist in the repo.** `model_loader.py`
  defaults to `llm_only` mode (`model_loader.py:219`) unless `CLASSIFIER_MODEL_PATH`/
  `NER_MODEL_PATH` point at directories that don't exist here. Extraction runs
  entirely through the LLM.
- **T5–T8 (proactive insight, proactive suggestion, owner shift summary, owner alert)
  are fully coded but unreachable.** `task_route()` has exactly one caller, which
  hardcodes `recipient="operator"` (`intelligence_router.py:530`) and never passes
  `is_proactive=True` anywhere. Only T1–T4 fire in production.
- `fuel_today` and `hours_today` have **no reset mechanism at all**, not merely a
  missing date filter — they are incremented with `+=` on every log and never
  cleared (`event_processor.py:511,515`), so they accumulate across calendar days
  indefinitely. `fuel_baseline` is null/0.0 whenever a machine has under 30 days of
  history, so anomaly comparison cannot fire until then.
- **Operator corrections are written but never read back.** `POST /correct/{event_id}`
  writes an immutable `CORRECTION` event; nothing reads that event type back to adjust
  confidence, thresholds, or flag unreliable extractions. Audit trail only.
- T4 off-topic replies from the unfine-tuned local LLM were inconsistent. T4 stays
  template-only (section 4). Three separate code paths can currently produce a
  T4-shaped reply (`task_router._build_t4_reply`, the T4 branch of
  `_build_agency_prompt`, `event_processor._agency_reply`) — a structural reason to
  expect this independent of model quality.
- The LLM is `qwen2.5:3b-instruct` via Ollama, prompt-only. The fine-tuning run never completed.

**Accuracy caveat.** The reported 99.3% intent accuracy came from a held-out split of
data we generated. **No evaluation script or test set exists anywhere in this repo** —
the number cannot currently be reproduced or audited, not merely "unvalidated on real
operator language." Do not quote it externally as real-world accuracy until an eval
set and script exist.

---

## 3. The five pillars

### Pillar 1 — Digital ЭСМ-2 (the wedge)

**Why:** the paper waybill is mandatory, mostly blank in practice, and understood instantly by both operator and owner.

**Scope**
- Per-shift record built only from logged events.
- A period export (date range) as PDF, since one paper waybill can cover 1 to 10 days on the same site.
- Fields to render come from the form in the photo the owner shared (Типовая межотраслевая форма № ЭСМ-2): organisation, customer, machine and state number, operator, date, object name and address, departure time and meter reading, return time and meter reading, fuel (type, issued, remainder), and the sign-off blocks. **Map against the official form when building the template. Do not trust this list as exact.**
- Chat-to-field mapping: `shift_start` gives departure time, machine and object. `hours_log` gives readings. `fuel_log` gives fuel issued. `shift_end` gives return time.
- **Fields chat cannot legitimately fill** (medical exam, mechanic sign-off, customer or foreman signature) print as "не зафиксировано". Never leave them looking complete. This applies "never appears smarter than its evidence" to the document itself.

**Definition of done**
- `/waybill <machine> <date|range>` (owner) returns a PDF.
- Every filled value is traceable to a `conversation_log` id. Every unfilled value says "не зафиксировано".
- Each export is recorded in `waybill_export` with the event ids it included.

**Candidate after first pilot:** one-tap foreman or customer confirmation in Telegram to replace the stamp.

### Pillar 2 — Telegram interface with voice

**Scope**
- Telegram Bot API via webhook, **private 1:1 chats only**. Group chats mix actors and break the session-to-operator mapping. Decision flagged in section 13.
- MAX is deferred (registration friction). Keep the channel adapter thin so MAX can be added later.
- Operator binding by deep link: `t.me/<bot>?start=<invite_token>` links `chat_id` to operator and org.
- Idempotent handling: unique key on inbound `(channel, update_id)`. A retried webhook must never double-log fuel.
- Corrections: "не 150, а 105" appends a correction event (`corrects_event_id`). History is never edited.
- Voice: download the voice note (typically OGG/Opus), convert, run Russian speech-to-text, then treat the transcript like any other message with `source=voice`.
  - **Always echo the transcript back** with inline ✅ / ✏️ buttons before any numeric entity (fuel, hours) is committed. Noisy cabin audio will produce errors, and confirming is cheaper than silent corruption.
  - Store the Telegram `file_unique_id` and STT metadata in `conversation_log` for traceability. Audio retention is an open decision.
- STT choice is decided by testing on real cabin audio from the pilot, scoring number accuracy, latency, cost and data location. Candidates: local `faster-whisper` on CPU, or Russian-hosted APIs such as Yandex SpeechKit or SberDevices SaluteSpeech (verify current terms).

**Definition of done**
- A new operator is onboarded in under two minutes using only a link.
- A voice note "залил сто пятьдесят литров" produces an echo, a confirm tap, a logged event and a reply.
- Replaying the same webhook payload twice creates one event.

### Pillar 3 — A sticky agent, not a dumb bot

**Why:** the first-day impression is the moat. The agent must feel like it knows the machine and takes initiative, even when its capability is narrow.

Most of that feel comes from the **state graph plus deterministic templates**, not from the LLM. Example reply: "Вчера 22 л/ч, сегодня 34 — что-то изменилось?" is a template filled with derived signals.

**Three behaviours that must work on day one**
1. **Shift-start recall:** "Вчера на CAT-101: 150 л, 6 ч, открыта течь гидравлики. Как сейчас?"
2. **Sanity challenge:** an implausible value (for example 5000 L, or 50 hours) gets a confirming question, not a silent log.
3. **Close-out prompt:** at shift end with fuel or hours missing, the agent asks for exactly the missing item.

Decision stack and LLM role are in section 4. The proactive rules are in section 7.

**Definition of done**
- All three behaviours pass in the golden set.
- The proactive rule list (section 7) is implemented with suppression and quiet hours.
- Turning the LLM off entirely leaves a fully working product.

### Pillar 4 — Minimal fleet intelligence and immutable traceability

**Why:** the digital ЭСМ-2 gets the first yes. ROI keeps the customer.

**Scope**
- **Daily digest** pushed to the owner in Telegram. A "needs attention" block comes first (anomalies, unresolved issues, missing logs), then per-machine lines (status, hours, fuel, rate versus baseline, open issues), then fleet totals.
- Every digest line is traceable: an inline "Откуда?" button shows the source operator messages and timestamps.
- On-demand owner commands: `/today`, `/machine <alias>`, `/waybill`, `/trace`.
- A per-org **findings log**: each anomaly or issue caught early, with timestamp and what was done. This is the ROI evidence for pilot reviews and pricing conversations.
- Baseline: rolling per-machine average once enough history exists. Until then a machine-type default, labelled as default in the digest.
- **Immutability is enforced in the database,** not by convention. The application role has no UPDATE or DELETE on `timeline_event` (revoke grants or use a trigger that raises).
- The existing `logbuk-neo.html` sandbox stays as a demo surface only. No further UI work in v1.

**Definition of done**
- Digest arrives daily at the org's configured local time.
- Any number in the digest can be traced to a source message in two taps.
- An attempted UPDATE or DELETE on `timeline_event` fails at the database.

### Pillar 5 — Minimal, foundational harness

Specified in section 6. It is the foundation for later learning, not a learning system.

---

## 4. Decision stack and the LLM's bounded role

**Tier 0 — deterministic.** State machine, rules, templates, schema validation, the policy engine. Decides what happens.

**Tier 1 — learned but constrained.** Intent classifier and NER (existing ONNX), and optionally a decision model (section 5). Produces typed outputs with probabilities. **Policy rules consume these outputs. Tier 1 never writes state and never decides actions.**

**Tier 2 — LLM, bounded.** Adapts language only.

**LLM allowlist for v1**

| Use | Notes |
|---|---|
| Verbalise T3, T5, T6, T7 (contextual clarification, anomaly question, proactive phrasing, shift summary) | Receives a structured payload. Writes one or two sentences. |
| Optional one-line headline for the owner digest | Numbers come from computed facts. Feature flag, default off until validated. |

**LLM exclusions (unchanged):** T1, T2, T4, T8 are template-only. The LLM never selects a policy action, never reads raw history, never produces a number not in its payload.

**Guardrails (all required before the LLM goes live)**
- Response validator on every LLM output. Numbers and named entities must exist in the input payload. On failure, silently fall back to a template.
- Live-path timeout (starting value 4 s), then template fallback. Proactive and digest paths are asynchronous, so a slow local model is acceptable there.
- Kill switch: a config flag plus an automatic trip when the validator rejection rate exceeds a threshold over a rolling window (tune from real data).
- Every LLM call is logged with model id, prompt version, latency, validator verdict.

**Hosting options (decision in section 13)**
- Local small model on the VPS. Data stays put, latency is poor on CPU, workable only with the timeout and fallback above.
- Russian-hosted LLM API (for example GigaChat or YandexGPT; verify terms). Better latency, data stays in-country.
- Foreign API. Conflicts with the data-location question. Avoid unless verified acceptable.

---

## 5. Decision models evaluated

The user pointed at two sources. Findings below come from reading both articles on 2026-10-03.

### GLiNER2.5-Decide (Fastino, post dated 2026-09-24)

**Stated facts**
- 340M parameters, open weight, Apache 2.0, runs locally on CPU, deployable air-gapped.
- Input is text plus a schema of typed questions (single answer, multi answer, or ordered value). Output is the answer per question with probabilities, confidence, and feasibility metadata.
- Joint constrained decoding: schemas can declare implications, exclusions, cardinality limits and ordinal bounds, and the decoder returns the best assignment that satisfies them.
- Also extracts spans (with character offsets), relations and structured records in the same pass.
- Supports full fine-tuning or LoRA.
- Latency: 167.3 ms p50 on a 48-vCPU Xeon (64 tokens, batch 1); 38.3 ms on a V100.
- Benchmark: 60.1% average on Fastino's own internal 17-dataset suite. That is an internal benchmark, not an independent one, and its categories are customer ops, banking, clinical, travel and general content.

**Not stated:** Russian-language support. Neither article mentions Russian. **Check the model card (huggingface.co/fastino/GLiNER2.5-Decide) before investing.** The latency figure is from a 48-vCPU machine. Expect slower on a small VPS and measure.

**Where it could fit.** The Understanding layer, next to the existing classifier. One pass could return intent, severity, needs-clarification and entities with cross-question constraints (for example `fuel_log` requires a numeric fuel entity; `severity=critical` implies escalate). That matches our schema-validation step and strengthens it.

**Adoption gate (time-boxed spike after Pillar 2 text flow works)**
1. Build a hand-labelled Russian eval set, starting around 200 to 300 messages, including real pilot messages and voice transcripts.
2. Compare current ONNX classifier + NER, GLiNER2.5-Decide zero-shot, and GLiNER2.5-Decide with LoRA.
3. Adopt only if it matches or beats the current stack on numeric-entity exactness and intent accuracy, and fits memory and latency on the target VPS. Otherwise keep the current stack.

### Jev (TypeSafe AI, via the LangChain post dated 2026-09-17)

**Stated facts**
- A "System One" model: it does not generate text. It takes a state plus typed questions (choice, score, yes/no) and returns probabilities.
- Accessed in the article through a hosted API with an API key (`TypeSafeClassifier` in `langchain-typesafe`).
- Company-reported "up to 200x faster and 400x cheaper than comparable LLMs on classification tasks".
- The article shows two uses: model routing and a tool-risk guardrail ("auto mode").
- The Fastino post calls JevK5 "an open reproduction rather than TypeSafe's Jev". This suggests Jev itself is not open weight (an inference, not stated).

**Decision for v1:** not adopted. Reasons: hosted API means operator message text leaves your infrastructure (data-location question), no Russian-language evidence, and no need that the local stack does not already cover.

**What to borrow from it:** the pattern. A cheap typed decision step before any generation, with probabilities that code (not a model) acts on. That is exactly Tier 1 feeding Tier 0.

### Note on the word "harness"

The LangChain article uses "harness" for agent-loop scaffolding (routing and guardrail middleware). Our harness (section 6) is different: logging, replay and measurement. Neither article describes replay or evaluation infrastructure, so section 6 is our own design.

---

## 6. Minimal foundational harness

**Principle:** observe and measure everything now, tune nothing automatically. The diagram's memory and KPI write-back arrows are v2.

**H1 — ConversationLog.** One row per inbound message and one per outbound reply, linked. Columns: org, session, operator, machine, channel, raw text, `source` (text or voice), STT metadata, intent, confidence, confidence route, entities (JSON), policy action, task type, reply text, `reply_source` (template, llm, fallback), validator verdict, latency, `timeline_event_id` (nullable), `corrected_by` (nullable), correlation id, pipeline version.

**H2 — Version stamp.** Every row records: classifier hash, NER hash, decision-model hash (if used), template-set version, rules version, prompt version, LLM model id. Without this, replays cannot be compared.

**H3 — Replay CLI.** `replay --from <ts> --to <ts> [--org <id>]` re-feeds logged inbound messages through the current pipeline in a scratch database and diffs intent, entities, policy action and reply. Rules:
- It never calls Telegram and never touches production tables.
- Deterministic stages must reproduce exactly. LLM turns compare only the validator verdict and fallback behaviour.
- Output is a report of changed decisions. Use it before shipping any change to rules, templates, models or prompts.

**H4 — Golden set.** Regression cases (input, expected intent, entities, policy action). Seed from the sandbox simulation, then replace and extend with real, anonymised pilot messages. Runs on every change to rules, models or templates. The three day-one behaviours (section 3) are mandatory cases.

**H5 — Metrics computed from logs**
- LLM fallback rate
- Validator rejection rate
- Operator correction rate (corrections divided by confirmed events)
- Clarification depth (turns to resolve)
- Voice confirm-reject rate

The validator rejection rate feeds the LLM kill switch. Nothing else auto-changes behaviour.

**Definition of done:** replaying a day of pilot traffic produces a report in one command, and a deliberate rules change shows up in that report.

---

## 7. Proactive layer (fixed list, deliberate ceiling)

A scheduler plus deterministic rules. Five rules. Adding a sixth requires an explicit decision and removing or deferring another.

| # | Trigger | Action | Suppression key |
|---|---|---|---|
| R1 | No shift start by the expected time | One nudge to the operator | org, machine, date, R1 |
| R2 | Shift closing with fuel or hours missing | Ask for exactly the missing item | session, R2 |
| R3 | Open issue from the previous shift | Follow up at next shift start | issue id, shift |
| R4 | Fuel rate anomaly versus baseline | Symptom question to operator, flag to owner | machine, R4, until state changes |
| R5 | Daily digest time | Send digest to owner | org, date |

**Requirements**
- **Quiet hours** per org timezone (starting value 21:00 to 06:00). A 3 a.m. nudge ends adoption.
- **Expected shift start** is an org-level default, configurable per operator. The sample waybill suggests an 08:00 to 19:00 day. Confirm with the pilot.
- **Suppression table** with unique `(org, machine, rule, window_key)`. A rule re-arms only when the underlying state changes.
- All proactive output goes through the policy engine, the response validator and the normal reply path.

---

## 8. Data model (v1 minimum)

`org_id` on every table.

- `org` (name, timezone, digest_time, quiet_hours)
- `app_user` (org, role owner|operator, channel chat id unique, name, locale)
- `invite` (token, org, role, operator, expires_at, used_at)
- `machine` (org, alias, reg_number, type, class)
- `shift_session` (org, operator, machine, object name/address, started_at, ended_at). **A session cannot open without a machine.**
- `conversation_log` (H1). Unique `(channel, update_id)` on inbound rows.
- `timeline_event` (org, session, machine, operator, event type, payload JSON, schema version, `source_conversation_id`, `corrects_event_id` nullable). **Append-only, enforced at database level.**
- `suppression` (section 7)
- `digest_log` (org, date, content hash, sent_at)
- `waybill_export` (org, machine, range, generated_at, event ids included, content hash)
- `finding` (org, machine, kind, detected_at, resolved_at, note)

Onboarding: owner registers via a bot command (`/start <owner code>`), uploads machines as a CSV or adds them by chat command, then generates operator invite links.

---

## 9. Infrastructure and operations

- One VPS, Docker Compose, Postgres. Add Redis only if already in use. No new infrastructure for v1.
- ONNX models on CPU. Measure RAM with everything loaded before choosing a plan.
- Nightly encrypted `pg_dump` copied off the server. Test a restore once.
- Error and health alerts to your own Telegram chat. Structured logs with the correlation id.
- Billing: manual invoicing for the first customers.
- **Pricing needs re-validation.** The tiered model (₽8,000 base plus per-machine) was written for the accelerator pitch. Test what a 10 to 30 machine SME will pay for "digital waybill record plus daily digest" before treating it as final.

---

## 10. Explicitly not in v1

- MAX integration
- Group chat support
- Web dashboard work beyond the existing sandbox demo
- Fine-tuned agency LLM (Kaggle run) and any model training beyond the optional LoRA spike in section 5
- Replay harness write-back, auto-tuned policy, cross-shift memory compression
- Hosted decision models (Jev) and any foreign API that receives operator text
- Photo or OCR of paper waybills
- Payments and automated billing
- Languages other than Russian

**Candidates after the first pilot:** foreman one-tap confirmation, photo of the paper ЭСМ-2 to pre-fill, MAX adapter, group chats, fine-tuned verbaliser trained on real transcripts.

---

## 11. Build sequence

Size is a rough relative guess (S, M, L), not a time estimate.

| Phase | Work | Size | Exit criterion |
|---|---|---|---|
| 0 | Foundation: date-filter fix, formal `PolicyDecision` object, schema validation, `org_id`, idempotency, append-only enforcement, ConversationLog plus version stamps (H1, H2) | M | One day of simulated traffic logs fully and replays |
| 1 | Telegram text end to end: webhook, invite onboarding, machine registration, templates, corrections | M | Real operator completes a shift by chat |
| 2 | Outputs: waybill PDF, digest, `/trace`, findings log | M | Owner receives digest and a PDF with provenance |
| 2b | Spike (time-boxed): decision-model evaluation (section 5) | S | Adopt or reject on eval-set numbers |
| 3 | Voice: STT, echo-confirm flow | M | Voice shift completes with confirm taps |
| 4 | Proactive rules R1 to R5, suppression, quiet hours | M | Rules fire once, never repeat |
| 5 | Harness: replay CLI, golden set, metrics, kill switch (H3 to H5) | M | One-command day replay report |
| 6 | Bounded LLM verbaliser live behind flags | S | Only after phases 5 and the validator exist |
| 7 | Pilot | | Section 12 |

**Gate:** the LLM verbaliser does not go live until the validator, kill switch and replay CLI exist.
Golden-set seeding starts in phase 1 as soon as real messages exist.

---

## 12. Pilot and success criteria

**Pilot #1:** the fleet owner who described the shift process. Two weeks, real operators, real machines.

**Proposed targets (adjust with the owner)**
- At least 80% of shifts have start, fuel, hours and end captured
- Operator correction rate trends down across the two weeks
- Owner opens the digest on most days
- At least three findings logged that the owner confirms were useful
- Owner states whether they would pay, and how much

**Collect during the pilot:** every real message (with consent), voice samples for the STT test, owner's edits to the waybill template, and anything that confused an operator.

---

## 13. Open decisions and things to verify before building

| Item | Why it matters | How to resolve |
|---|---|---|
| Legal acceptability of a chat-generated ЭСМ-2 | Decides "companion" versus "alternative" wording | Ask the pilot owner's accountant; consult a Russian lawyer |
| 152-ФЗ personal data (operator names, chat ids) | May constrain hosting and which STT or LLM APIs are allowed | Verify with a Russian lawyer or hosting provider. This is not legal advice. |
| Telegram reachability for pilot operators | Whole channel strategy rests on it | Test on the pilot operators' actual phones and networks |
| Private chats only versus groups | Operators may already coordinate in groups | Ask the pilot owner |
| STT provider | Number accuracy on cabin audio | Record real samples, score candidates |
| LLM hosting | Latency, cost, data location | Decide after RAM and latency measurements |
| Voice audio retention | Traceability versus privacy | Decide with the pilot owner |
| GLiNER2.5-Decide Russian support | Determines whether the spike is worth running | Read the model card; run the zero-shot test |
| Pricing | Current tiers came from pitch work | Test with the pilot owner |
| Expected shift start and quiet hours | Drives R1 and nudge tone | Confirm per org |

---

## 14. v1 invariants for Claude Code

These add to the ten in ARCHITECTURE_VERBALIZED.md. Invariant 11 is in section 15.5.

1. Every value printed on a waybill or digest has provenance (a `conversation_log` id) or is shown as "не зафиксировано".
2. Voice-sourced numeric entities are never committed without an operator confirm.
3. Every outbound LLM text passes the response validator. No bypass flag in production.
4. Proactive messages always respect suppression and quiet hours.
5. Decision-model and classifier outputs feed policy rules. They never mutate state or choose actions.
6. Turning the LLM off must leave a fully working product.
7. No operator text goes to a foreign API without an explicit, documented decision.
8. The replay CLI never writes to production tables and never sends messages.
9. Corrections are new events that reference the original. No edits, ever.
10. Do not expand the proactive rule list or the LLM allowlist without updating this document first.

---

## 15. Pitch → build map

The accelerator-pitch architecture (`vfm_architecture_final.svg`) is the **target** architecture. v1 is a thin vertical slice through it. `vfm_architecture_v1_status.svg` is the same diagram coloured by build status. Claude Code may build blocks marked **v1** or **minimal**. It must not build blocks marked **later**.

### 15.1 Layer-by-layer status

| Pitch layer | v1 status | What v1 means |
|---|---|---|
| Interfaces | v1 | Telegram and REST. MAX is later (see section 10). |
| Signal normaliser | v1 | Safety, format, language, plus voice-to-text and the echo-confirm step (pillar 2). |
| Intent + entity extraction | v1 | Tier 0 rules, then Tier 1 classifier and NER. The GLiNER2.5-Decide spike stays gated on a Russian eval set. |
| Confidence scoring | v1 | Accept or clarify. |
| Canonical state | v1 | Status per machine. |
| Derived signals | **minimal** | Fuel-rate baseline and recurring issues only (needed for R3 and R4). General anomaly and trend detection is later. |
| Event timeline | v1, core | Append-only, enforced at the database level. Confirmed operational events only. |
| Session context, workflow rules, thresholds | v1 | Shift sessions, suppression keys, quiet hours. |
| Policy engine | v1 | CONFIRM, CLARIFY, ALERT, NUDGE, ESCALATE. A fixed action set. |
| Template engine | v1 | T1, T2, T4, T8 are template-only. |
| LLM verbaliser | v1, **gated** | Live only after the validator, kill switch and replay CLI exist (section 11 gate). |
| Response validator | v1, required | No bypass flag in production. |
| Reply to channels | v1 | |
| Fleet intelligence | **minimal** | Daily digest, `/today`, `/machine`. |
| Owner alert | **minimal** | R4 anomaly flag and the R5 digest. |
| Machine log | v1 | `/trace`. |
| ЭСМ-2 waybill export | v1, **wedge** | See 15.2. |
| Proactive watchdog | v1, capped | Exactly five rules, R1 to R5 (section 7). |
| Replay harness | **minimal** | Replay CLI, golden set, version stamps, metrics (H1 to H5). |
| Replay harness → State ("mem") | **later** | Human-reviewed only. See 15.3. |
| Replay harness → Policy ("KPI") | **later** | Human-reviewed only. See 15.3. |

### 15.2 What the pitch diagram does not show

1. **ЭСМ-2 waybill is a fifth output.** It is the wedge, but the Response output row has no box for it. It is a read-only derived view of `timeline_event`. A field with no evidence prints "не зафиксировано". It never writes back to the timeline.
2. **ConversationLog is not drawn.** It records every turn, including off-topic ones. `timeline_event` holds only confirmed operational events. ConversationLog belongs to the harness and is the source for provenance (invariant 1).
3. **Voice sits in the Signal normaliser.** Speech-to-text output is untrusted input like any other text, and numeric entities from voice are confirmed before commit (invariant 2).

### 15.3 KPI and memory feedback: human-reviewed in v1

In the pitch diagram the "mem" and "KPI" arrows write back into State and Policy. In v1 that loop is manual: the owner of the system reviews replay results and golden-set regressions, then edits rules, thresholds or templates by hand and ships a new version stamp. There is no automatic write-back, no auto-tuned policy and no memory compression (section 10). This is a deliberate fit with "never appears smarter than its evidence". Do not describe v1 as self-improving in the pitch or the docs.

### 15.4 Roadmap spine

Build along the data path in the simple flow: **Field signals → Understanding → State graph → Policy → Outputs**. Each phase in section 11 should leave one more block of that path working end to end, with the waybill export as the first visible output.

### 15.5 Additional invariant

11. Do not build any block marked **later** in this section without updating this document first. Blocks marked **minimal** are built only to the slice described in 15.1.
