# Prompt for Claude Code: build the SuperDoka Telegram bot from scratch, spec-driven

Paste everything below the line into Claude Code at the `superdoka-backend` repo root.

**Before you paste (human checklist):**
1. Unzip `superdoka_docs.zip` into the repo root so `docs/` exists, and copy `SHIPPABLE_SCOPE.md` and `ARCHITECTURE_VERBALIZED.md` (and the other architecture documents from the same folder) to the repo root.
2. Keep `MVP_ASSESSMENT_FOR_CLAUDE.md` in the repo root. It is evidence for this task.
3. Work on a new branch, for example `feat/telegram-bot`.
4. Create a **separate dev bot** in BotFather and keep its token in your local `.env`. Do not use the production token locally.

---

## Role and ground rules

You are building the Telegram channel for SuperDoka **from scratch**. There is no existing bot process. The repo only contains `app/adapters/telegram_adapter.py`, a function-style adapter meant to be called from a bot that does not exist. Work spec-first: documents first, then a checkpoint, then code.

Read, in this order, before doing anything:
1. `docs/README.md` and `docs/CLAUDE_MD_SNIPPET.md` (the process rules you must follow)
2. `MVP_ASSESSMENT_FOR_CLAUDE.md` (the evidence about the current code)
3. `SHIPPABLE_SCOPE.md` and `ARCHITECTURE_VERBALIZED.md`
4. Every file in `docs/adr/` and `docs/specs/`

**If `docs/` or any of these files is missing, stop immediately and tell the human exactly what is missing.**

Rules:
- **Evidence or UNKNOWN.** Cite `path:line` for claims about code.
- **Secrets:** never read, print, log or commit `.env` values or any token. Do not hard-code tokens. Add `.env` to `.gitignore` if missing.
- **No live calls.** Tests must never call the real Telegram API. Do not execute anything on the VPS. If a live check would help, write the command for the human.
- **Databases:** use a disposable local database only. If `DATABASE_URL` points anywhere that is not local, stop. Migrations must be reversible, follow the repo's alembic naming, and never be run against a real database.
- **Do not touch:** the demo sandbox (`https://demo.superdoka.ru/sandbox.html` runs on the same VPS), the dormant T5 to T8 code, the watcher, and the legacy group-chat code (`GroupMessage`, `groups_patch.py`). Leave them working and mark them dormant or deprecated in docs only.
- **Do not edit Accepted ADRs** (ADR-0001 to ADR-0014). Add new ones that supplement or supersede.
- **Stay in v1 scope** (`SHIPPABLE_SCOPE.md`). Out-of-scope ideas go to `docs/proposals/OUT_OF_SCOPE.md`.
- Keep the wording rule: the waybill is a "companion" or "digital waybill record" until legal acceptability is verified.
- Commit in small steps on the current branch. Commit messages reference requirement IDs, for example `SPEC-001-R08: dedupe inbound updates`. **Do not push.**
- Ask questions only at the checkpoint or the end, in one batch.

## Decisions already approved by the human

Treat these as decided and record them as Accepted ADRs, dated 2026-10-24, decider Varun:
1. **Library:** aiogram 3. Check the current documentation before pinning a version. All aiogram imports live under `app/channels/telegram/`, nowhere else (SPEC-001-R03).
2. **Intake modes:** both, selected by `TELEGRAM_MODE=polling|webhook`. Polling for local development, webhook on the VPS. The same handler code serves both.
3. **Where the code lives, and the engine/bot boundary:** the Telegram bot is an **interface layer on top of the engine**. It is logically decoupled but deployed together for now: a new `app/channels/` package inside the existing FastAPI app, in the same repo and process. The webhook is a route in that app. Polling is a separate entry point (`python -m app.channels.telegram.polling`) that shares the handler. The boundary is strict and one-directional:
   - the engine exposes **one** entry point, `handle_inbound(NormalisedInbound) -> list[OutboundMessage]`, which returns neutral replies and **never sends anything itself**;
   - `app/channels/*` may call only that entry point and import only `app/channels/base.py` from the engine side;
   - the engine (`app/core`, `app/services`, `app/db`, `app/rules`) must **never import** `app/channels` or aiogram;
   - add an import-boundary test that enforces all of this, so the bot can later be split into its own service by moving the package and replacing the function call with an HTTP call, without touching engine logic.
4. **Environments:** separate dev and prod bot tokens. The same codebase is **deployed twice**: a demo instance (existing sandbox) and a production instance for real operators, each with its own database and compose project and no shared running process. Expected size to design for: about 5 fleet owners and about 50 operators.
5. **Chats:** private 1:1 chats only for the first validation. Group, supergroup and channel updates are ignored with one polite reply. Note for the ADR: the earlier rationale in ADR-0001 was too strong, because Telegram does give a sender id for group messages. The real reasons are group privacy mode, replies visible to everyone, and off-topic chatter. Write a supplementary ADR that corrects this and states the revisit trigger: operators refuse private chats.
6. **Dormant code:** T5 to T8, the watcher and the owner paths stay dormant for the validation slice.
7. **Tenancy:** add an `org` table and `org_id` with a single default org. A single default org is enough only for the two-machine validation. **Before a second customer is onboarded, tenant scoping through one data-access layer plus a cross-org isolation test (AC-011-01) is required.** Record this as a gate in the delivery notes, and design the new tables so that enforcement can be added without another schema change.
8. **Facts from the human:** the bot token works from the VPS (outbound to Telegram is verified). Inbound webhook reachability from Telegram to the VPS is **not yet verified**. The current `getWebhookInfo` state of the token is unknown. Never assume either.

## Step 1: integrate the docs and fix them against reality

- Update `CLAUDE.md` to point at `docs/README.md` and include the rules from `docs/CLAUDE_MD_SNIPPET.md`. Keep existing useful content. Note that `CLAUDE.md` currently misses the second architecture layer (`task_router.py`, `context_graph.py`, `intelligence_router.py`, `rephraser.py`) and add a short pointer to it.
- Propose edits to `SHIPPABLE_SCOPE.md` §2 so it matches the assessment (ONNX classifier and NER files are absent and extraction runs through the LLM in `llm_only` mode; T5 to T8 are dead code; the watcher send is a TODO; the date counters never reset; corrections are written but never read; the 99.3% claim is unsupported). Write the proposed edits to `docs/proposals/SCOPE_SECTION2_EDITS.md` and apply them to the scope file only if the change is purely a factual correction.

## Step 2: write the specs and ADRs (documents only)

Use `docs/templates/`. Continue numbering from the next free IDs (check the folders). Keep front matter so `docs/tools/check_docs.py` passes. Every requirement needs at least one acceptance scenario.

**New specs (status Draft):**
- *SPEC: Telegram bot runtime and delivery resilience.* Intake modes, secret-token verification, webhook lifecycle commands, graceful shutdown, per-chat ordering, message splitting at the platform limit, escaping, `retry_after` handling with a retry cap, blocked-user handling, outbound timeouts. A full outbox is deferred.
- *SPEC: Bot interaction design and copy.* Command menu, `/start <token>` binding flow, consent notice and record, welcome and help copy in Russian, ✅ / ✏️ confirmations, correction flow, versioned expiring callback data, double-tap safety, stale-callback behaviour, voice and photo replies for the validation slice, persisted conversation state, error messages. All Russian strings in one module.
- *SPEC: Bot security, privacy and consent.* Webhook secret, bound-user allowlist, unbound-user onboarding reply, simple per-chat flood limit, log redaction (never log tokens, log ids rather than message text at INFO), consent record, data export and deletion on request, token rotation.
- *SPEC: Bot observability and operations (light).* Structured logs with correlation id, health endpoint, minimum alerts, deployment and rollback runbook.
- *SPEC: Bot test harness.* Real update fixtures, a fake Bot API, end-to-end tests through the webhook route, duplicate and retry tests.

**New ADRs.** Accepted: the five approved decisions above (framework, intake modes, package placement, environments and tokens, private-chat-first supplement to ADR-0001). **Proposed** (options, recommendation, consequences, revisit trigger):
- *Pending confirmations and conversation state persisted in the database.* Recommendation: do not write `TimelineEvent` until the operator confirms. Keep proposed events in a short-lived mutable `pending_confirmation` table, and conversation state (for example "awaiting correction") in a `chat_state` table, never in process memory. This keeps the timeline append-only (ADR-0005) while fixing commit-before-confirm.
- *Callback data contract.* Versioned, within the platform's size limit, expiring, owned by the bound user, idempotent.
- *Outbound delivery policy.* Minimal send wrapper now, transactional outbox later.
- *Interim understanding backend.* Extraction currently runs entirely on the LLM because no classifier files exist. Recommend keeping LLM extraction for now with a deterministic check: every numeric entity must appear in the operator's message (after number-word normalisation), otherwise ask a clarifying question. Record the options (restore the ONNX models, spike GLiNER2.5-Decide or Laya, keep LLM) and the data-residency question about where the LLM runs. **Do not implement this ADR in this task.**
- *Hardware and sensor signals: deferred.* Record the decision to defer, the evidence that would reopen it, and where a device reading would plug in.

Also write `docs/proposals/AMENDMENTS.md` listing exact requirement changes needed in existing specs (at minimum SPEC-001, SPEC-004 for pending confirmations, SPEC-005, SPEC-011 for the new tables), without editing those specs.

Run `python3 docs/tools/check_docs.py --write`. It must pass.

### CHECKPOINT
Stop here. Print a summary of the specs and ADRs you wrote, any conflict you found between documents, and your questions (batched). **Wait for the human to reply "proceed" before writing any code.**

## Step 3: implement the walking skeleton

First record a baseline: install dependencies and run the existing test suite, and report pass and fail counts (`poetry install && poetry run pytest -q` or the repo's equivalent). Do not "fix" unrelated failures.

Then build in this order, one commit per work package, tests included in each:

**WP-A. Channel contract and config.**
- `app/channels/base.py`: a channel-neutral `ChannelAdapter` protocol, `NormalisedInbound` (channel, update_id, chat_id, user_id, message_id, timestamp, text or media reference, chat type) and `OutboundMessage` (text, optional buttons). The pipeline never imports aiogram types.
- Add the engine entry point `handle_inbound(NormalisedInbound) -> list[OutboundMessage]` (for example in `app/services/`), wrapping the existing `event_processor`. It returns replies and performs no sending. Retire the side effect in `telegram_adapter.process_telegram_message` (the `send_message_fn` call) by routing it through the new contract, keeping the old function working for the sandbox until the human removes it.
- Settings: `TELEGRAM_MODE`, `BOT_TOKEN`, `WEBHOOK_SECRET`, `WEBHOOK_BASE_URL`, `BOT_ENV` (dev or prod), database URL. Fail fast with a clear message if a required value is missing. Commit `.env.example` with names and no values.

**WP-B. Schema.** One reviewed, reversible migration (or a small set) that: adds `org` and `org_id` with a default org on the tables the bot flow touches (list any tables left for later); extends or adds the inbound log with `channel`, `update_id` (unique together for inbound rows), `processing_status` (`received`, `processed`, `failed`) and `correlation_id`; adds `invite`, `pending_confirmation`, `chat_state`, consent fields on the user, and a small table for "already told this chat" notices. Reconcile with the existing `ConversationLog`, `User` and `TimelineEvent` models and list differences from SPEC-011 in `docs/proposals/AMENDMENTS.md`.

**WP-C. Intake and idempotency.**
- Webhook route with constant-time verification of Telegram's secret-token header. Reject missing or wrong secrets without touching the database.
- **Acknowledge fast, process in a worker.** The webhook (and polling) handler inserts the inbound row **before** running the pipeline and returns success quickly. On a duplicate `(channel, update_id)` return success immediately without running it or replying. Processing happens in a worker loop (an asyncio task started with the app, plus a separate entry point `python -m app.channels.worker` for the production instance) that claims `received` rows, with at most one message in flight per chat so order is preserved and a small concurrency cap overall, because the LLM extraction step may be slow. A recovery routine re-claims or flags rows stuck in `received`. Add a test that a slow pipeline does not delay the webhook response, and one that two quick messages from the same chat are processed in order.
- Polling entry point and a small admin CLI (`python -m app.channels.telegram.admin set-webhook|delete-webhook|info`) that never prints the token. The CLI refuses to start polling in prod while a webhook is set.
- Graceful shutdown and a health endpoint.

**WP-D. Access control and onboarding.**
- Serve only private chats. For group, supergroup and channel updates, send at most one "write to me privately" notice per chat and run no pipeline. Ignore `edited_message` for now, with a log line.
- `/start <invite_token>` binds `chat_id` to a user. Tokens are single-use and expire. An invalid or used token produces a clear Russian message and no binding. Unbound users get one onboarding instruction and create no state.
- Consent notice with a confirm button on first use. **Do not process operator messages until consent is recorded.** Mark the Russian wording as a draft for the human and a lawyer to review.
- A seed script `scripts/seed_pilot.py` that reads machines and operators from a local YAML or CSV (not committed) and can print invite links. No real data in the repo.

**WP-E. Message flow with commit-after-confirm.**
- Text in a private chat goes through the existing pipeline. Auto-route results commit immediately. Confirm-route and implausible results are stored in `pending_confirmation` and shown back with ✅ / ✏️ buttons. **No `TimelineEvent` exists until ✅.** Refactor `event_processor._write_events` minimally to support this and keep the sandbox and existing tests working.
- Callback data is versioned, short enough for the platform limit, bound to one pending row, expiring, and safe against double taps and stale taps (answer the callback with a short message).
- ✏️ stores "awaiting correction" in `chat_state`. The next message from that chat resolves the pending item, or, if it was already committed, creates a correction event that references the original (`corrects_event_id`), by calling the shared logic behind `POST /correct/{event_id}` and not over HTTP.
- Voice: reply that voice is not supported yet and ask for text, and store the `file_unique_id` in the log for later manual transcription. Photos and other media: one polite reply.

**WP-F. Delivery.** One send wrapper: split long text at paragraph boundaries under the platform limit, avoid `parse_mode` injection (plain text by default or proper escaping), respect `retry_after` on rate-limit errors with a retry cap, mark the user unreachable on a "blocked by user" error, set timeouts. All user-facing strings live in `app/channels/telegram/copy_ru.py`.

**WP-G. Fixes the bot depends on.**
- Replace the lifetime counters `fuel_added_today` and `hours_worked_today` with values computed from events in the org-local calendar day (see SPEC-004-R10). Do not leave counters that never reset.
- Collapse the three off-topic (T4) reply paths (`task_router._build_t4_reply`, the T4 branch of `_build_agency_prompt`, `event_processor._agency_reply`) into one template-only path.
- Make correction events readable: expose the operator correction rate as a query for the harness metrics (SPEC-010-R12).

**Tests (all offline).** Fixtures of real Telegram update shapes: private text, voice, photo, group message, callback query, edited message, `/start` with and without payload. A fake Bot API that records outbound calls. Cover at least:
1. a missing or wrong webhook secret is rejected;
2. the same update delivered twice causes one inbound row, one event and one reply;
3. an unbound user gets the onboarding message and no state;
4. a group message is ignored with at most one notice;
5. a valid invite binds the chat, and a reused or expired invite does not;
6. a confirm-route message creates no `TimelineEvent` until ✅;
7. a double tap on ✅ creates exactly one event, and a stale tap gets a safe reply;
8. ✏️ followed by a corrected message creates a correction event linked to the original;
9. a long reply is split under the limit, and a simulated `retry_after` is retried within the cap;
10. a "blocked by user" error marks the user unreachable without crashing;
11. voice and photo get the polite replies and no event;
12. `fuel_today` is correct across a day boundary in a non-UTC timezone;
13. an import-boundary test fails if the engine imports `app/channels` or aiogram, or if anything under `app/channels` imports engine modules other than the contract and `handle_inbound`.

Add the new tests to the existing suite, keep previously passing tests passing, and report the final pass and fail counts against the baseline.

## Step 4: runbooks (documents only)

Write, and do not execute:
- `docs/runbooks/botfather_setup.md`: name, description and about text in Russian, command list matching only commands that exist, privacy mode, disabling "allow groups" so the bot cannot be added to groups, token rotation.
- `docs/runbooks/bot_deploy.md`: separate compose project and database for the real bot, an example reverse-proxy snippet (not applied) for the webhook path over HTTPS, the webhook setup and verification steps using the admin CLI and `getWebhookInfo` (look at `last_error_message` to confirm Telegram can reach the VPS), the polling fallback if inbound reachability fails, rollback, and a reminder never to run polling with the production token while a webhook is set.
- `docs/runbooks/local_dev.md`: running with the dev token in polling mode.

## Final response (at most 300 words)

1. Baseline and final test counts.
2. What is built, mapped to requirement IDs, and what was deferred.
3. Anything that deviates from an Accepted ADR or invariant, with evidence.
4. The decisions the human still owes (including the Proposed ADRs), in priority order.
5. What the human must verify live: inbound webhook reachability from Telegram, current `getWebhookInfo` state, the consent wording, the dev bot test with two real accounts.

Do not paste documents into the reply. Point to the files.
