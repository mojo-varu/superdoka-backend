# Prompt for Claude Code: assess the MVP, then draft the specs and ADRs for a production-grade Telegram bot

Paste everything below the line into Claude Code, started at the repo root (the `logbuk` folder that contains `app/`, `alembic/` and `docs/`).

---

## Role and ground rules

You are auditing the current SuperDoka MVP and preparing the documents that will guide building a **shippable Telegram bot** on top of it. This task is **read-mostly**: you may run tests and read code, and you may write only under `docs/`. **Do not change application code, migrations, configuration or dependencies.**

Before anything else, read, in this order:
1. `docs/README.md` and the process rules in `docs/CLAUDE_MD_SNIPPET.md`
2. `SHIPPABLE_SCOPE.md` (especially §2 "Where things stand today", §3 pillars, §13 open decisions, §14 and §15 invariants)
3. `ARCHITECTURE_VERBALIZED.md` (the ten "must never do" rules)
4. Every file in `docs/adr/` and `docs/specs/`

Rules for this task:
- **Evidence or UNKNOWN.** Every statement about the code must cite `path:line` or a command and its result. If you cannot verify something, write `UNKNOWN` and say what you would need. Do not guess and do not smooth over gaps.
- **Never read, print or copy secrets** (bot tokens, `.env` values, API keys). You may note that a secret exists and how it is loaded.
- **Do not call the live Telegram API or any external service.** If a live test would help, write the exact commands for the human to run instead.
- **Do not edit Accepted ADRs.** Propose a superseding ADR instead. Do not edit existing specs in place; list changes in `docs/proposals/AMENDMENTS.md`.
- **Decisions belong to the human.** New ADRs are `Proposed`, new specs are `Draft`. Give a recommendation, the options and the trade-offs, and never mark anything Accepted.
- **Stay inside v1 scope.** If something is useful but outside `SHIPPABLE_SCOPE.md`, list it as a scope question, do not write it into a spec as a requirement.
- Keep the wording rule: until legal acceptability is verified, the waybill is a "companion" or "digital waybill record".
- Ask questions only at the end, in one batch, and only for things you could not determine from the repo. Do not stop midway to ask.

Context you should know: the repo contains `app/adapters/telegram_adapter.py`, a function-style adapter meant to be called from an existing bot handler, but the bot process itself (token, update loop, handlers) may live outside this repo. The human says a SuperDoka Telegram bot is already in place. Telegram access in Russia was restricted during 2026 and its status today is unknown, so design for a channel-neutral core and do not assume reachability.

## Phase 1: evidence-based state assessment

Write `docs/status/STATE_ASSESSMENT.md`. Use short sections and tables. Cover:

**A. Inventory**
- Repo map: entry points, main packages, what each does, dependencies and versions, Python version, database and migration state (`alembic` heads, models versus `SPEC-011`).
- Where the Telegram bot actually lives: in this repo, another repo, or unknown. What library it uses, how it receives updates (webhook or polling), how it is deployed. List what you could not determine.

**B. What actually runs**
- Install and run the test suite and any lint or type checks. Record the exact commands, pass and fail counts, skipped and flaky tests, and anything that needs services you do not have.
- Run the sandbox flow and the simulation scripts if they run locally without external services. Record results.
- Check the four known issues in `SHIPPABLE_SCOPE.md` §2 and report whether each still exists: `fuel_today` and `hours_today` missing a date filter, `fuel_baseline` null, inconsistent T4 replies, the 99.3% accuracy claim and how the test set was produced.

**C. Compliance against the specs**
- Produce `docs/status/compliance.csv` with one row per requirement ID across all 13 specs: `requirement_id, status, evidence, notes`. Status is one of `Implemented`, `Partial`, `Missing`, `Deviates`, `UNKNOWN`. Generate the ID list by parsing the specs, not by hand.
- Summarise per spec in `STATE_ASSESSMENT.md` with counts and the three most important gaps.
- Call out every place where the code **deviates** from an Accepted ADR or an invariant. From the adapter I already suspect the following, so confirm or refute each with evidence: events appear to be committed before the operator confirms; there is no unique key on `(channel, update_id)`; there is no `org_id`; no webhook secret check; group-oriented code paths; reply sending is coupled to the adapter instead of returning a neutral reply; the correction callback does not link to the original event.

**D. Telegram bot production-readiness review**
Write `docs/status/BOT_READINESS.md` as a checklist with `PASS / FAIL / UNKNOWN` and evidence for each item. Include at least:
- Update intake: webhook secret verification, setWebhook lifecycle, behaviour on restart, polling versus webhook, per-chat message ordering, concurrency.
- Delivery: handling of rate limits and `retry_after`, "bot was blocked by the user" errors, the 4096-character limit and message splitting, `parse_mode` escaping, outbound timeouts, retries and idempotency, an outbox or equivalent.
- Interaction: command menu, `/start` and invite flow, `/help`, callback data design (size limit, versioning, expiry, double-tap safety, unknown or stale callbacks), conversation state persisted in the database rather than memory, user-facing error messages, Russian copy quality.
- Security and privacy: secret handling, only bound users are served, group chats ignored, abuse and flood limits, use of `injection_guard.py`, log redaction of personal data, consent record, deletion or export on request.
- Operations: structured logs with correlation id, metrics, alerting, health endpoint, graceful shutdown, deployment and rollback, backup and restore.
- Testing: fixtures of real Telegram update shapes, a fake Bot API for tests, end-to-end test through the webhook, replayability of logged traffic.
- Channel contingency: how much of the code imports Telegram types outside the adapter, and what a MAX adapter would require.

Verify any Telegram Bot API limit you cite against the current official documentation, and say so if you could not.

**E. Risks, unknowns, and questions**
List the top risks ranked by impact, and a single batched list of questions for the human, each with what it blocks.

## Phase 2: propose specs and ADRs

Use the templates in `docs/templates/`. Number new files from the next free IDs (check the folders, do not assume). Keep the front-matter format so `docs/tools/check_docs.py` keeps working. Every new requirement needs at least one acceptance scenario.

Start from this seed list. For each item, decide **keep, merge or drop** based on your findings and say why in `docs/proposals/PROPOSAL_NOTES.md`. Add anything the audit shows is missing.

**Candidate specs (status Draft)**
1. *Telegram bot runtime and delivery resilience*: update intake mode, per-chat ordering, outbox with retry and backoff, rate-limit and `retry_after` handling, blocked-user handling, message splitting, escaping, timeouts, graceful shutdown.
2. *Bot interaction design and copy*: command menu, onboarding and invite flows, versioned and expiring callback data, double-tap safety, error and help copy in Russian, persisted conversation state.
3. *Bot security, privacy and consent*: webhook secret, bound-user allowlist, per-chat flood limits, log redaction, consent record, data export and deletion, token rotation.
4. *Bot observability and operations*: structured logs, metrics, alerts, dead-letter or poison-update handling, deploy and rollback, runbooks.
5. *Bot test harness*: real update fixtures, a fake Bot API, contract tests, end-to-end tests through the webhook, link to replay in SPEC-010.
6. *Legacy bot migration*: strangler cutover from the old handler to the new adapter behind a feature flag, rollback plan, migrating `GroupMessage` and `fuel_logs` data into `timeline_event`, moving from group to private chats.

**Candidate ADRs (status Proposed, with options, a recommendation, consequences, and a revisit trigger)**
1. *Channel contingency*: Telegram reachability and MAX adapter readiness (supplements ADR-0001, do not edit it).
2. *Bot framework and runtime*: for example aiogram, pyTelegramBotAPI or a thin client. Decide from what is actually in place.
3. *Update intake and hosting location*: webhook versus long polling, and whether a Russian-hosted server can reliably reach the Telegram API. Flag the tension with data-location rules and give the human a test plan.
4. *Conversation state*: persisted in Postgres, serialised per chat, never in process memory.
5. *Outbound delivery*: transactional outbox with retry and rate-limit policy.
6. *Callback data and interactive message contract*.
7. *Legacy migration strategy*.
8. *Hardware or sensor signals: deferred* (record the decision to defer, the evidence that would reopen it, and where a device reading would plug in).

Then:
- Write `docs/proposals/AMENDMENTS.md`: for each existing spec that needs a change (for example SPEC-001 needs a brownfield section), list the exact requirement IDs to add or modify and why. Do not edit those specs.
- Run `python3 docs/tools/check_docs.py --write`. It must pass with no errors. Fix your own documents until it does.

## Phase 3: delivery plan

Write `docs/status/DELIVERY_PLAN.md`:
- Ordered work packages (WP1, WP2, ...), each with the requirement IDs it satisfies, dependencies, a relative size (S, M or L, not a time estimate), exit criteria drawn from the acceptance scenarios, and the human decisions that must be made first.
- The first work packages should make the existing bot safe and correct (commit-after-confirm, idempotency, tenancy, secret check, neutral reply contract) before adding features.
- Mark what is the **minimum slice for the two-machine validation** and what waits for the full v1.
- A definition of "shippable Telegram bot" for this product, as a short measurable checklist derived from `BOT_READINESS.md`.

## Final response

Reply with at most 300 words:
1. Overall state in two sentences, with the compliance counts (Implemented, Partial, Missing, Deviates, UNKNOWN).
2. The five most serious findings.
3. Which specs and ADRs you created, and which seed items you dropped or merged.
4. The decisions the human must make first, in priority order.
5. Anything you could not verify and how to verify it.

Do not paste the documents into the reply. Point to the files.
