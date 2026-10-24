# SuperDoka VFM — Evidence-Based MVP Assessment

Prepared for: handoff to another Claude session that has no prior context on this repo.
Repo: `superdoka-backend` (FastAPI VFM backend). Date: 2026-10-24.

## 0. Important scope note — read this first

`CLAUDE_CODE_ASSESSMENT_PROMPT.md` (repo root) is a large audit prompt that assumes a
documentation framework — `docs/README.md`, `SHIPPABLE_SCOPE.md`,
`ARCHITECTURE_VERBALIZED.md`, `docs/adr/`, `docs/specs/`, `docs/templates/`,
`docs/tools/check_docs.py` — with 13 numbered specs and existing ADRs.

**That framework does not exist in this repo.** Verified: `find docs` returns nothing;
the only root-level markdown files are `BuildUp-Presentation.md`, `CLAUDE.md`,
`README.md`, `closed-domain-agentic-architecture.md`, and the prompt file itself. There
is no `docs/` directory at all.

So the elaborate Phase 1–3 procedure in that prompt (parse 13 specs for requirement IDs,
write `compliance.csv`, draft superseding ADRs, run `check_docs.py`) **cannot be
executed as written** — there is nothing to audit against. If that doc framework exists
in a separate planning repo, point the next session at that repo instead. What follows
is a from-scratch, single-document assessment built directly from the code, not a
continuation of that framework.

## 1. What this system actually is

A FastAPI backend that ingests operator messages (Telegram/MAX/REST) about heavy
equipment, extracts intent/entities via LLM, and writes structured fleet events. Two
architecture layers coexist:

- **The documented one** (`CLAUDE.md`): three pillars — Interface → Intelligence
  (`context_llm.py`) → Agency (`event_processor.py`), with `ConfidenceRoute`
  (AUTO ≥0.85 / CONFIRM 0.60–0.85 / LLM <0.60).
- **An undocumented second layer on top**, found live in `app/core/task_router.py`,
  `context_graph.py`, `intelligence_router.py`, `rephraser.py` — none of these are
  mentioned in `CLAUDE.md`. It adds a task-type taxonomy (T1–T8), a "context graph" of
  machine/operator state with precomputed anomaly signals, and a rephrasing pass that
  sits between template-fill and delivery.

Both layers are real and wired together (`event_processor.py` calls into
`intelligence_router.run_intelligence`, which calls `task_router.route`). This is not
two competing designs — it's one pipeline, just under-documented.

## 2. Live vs. dead code — verified by call-graph tracing

| Component | Status | Evidence |
|---|---|---|
| T1 (confirm), T2 (clarify/confirm-log), T3 (contextual clarify), T4 (off-topic) | **Live, reachable** | `task_router.py:94-147`, called from `intelligence_router.py:522` with `recipient="operator"` on every message |
| T5 (insight), T6 (proactive suggestion) | **Dead code** | Require `is_proactive=True`. Grepped every call site of `run_intelligence()`/`task_route()` — `is_proactive` is never passed `True` anywhere in the codebase |
| T7 (shift summary), T8 (owner alert) | **Dead code** | Require `recipient="owner"`. The only call site (`intelligence_router.py:530`) hardcodes `recipient="operator"` — the owner branch in `task_router.py:102-108` is unreachable |
| Watcher nudge delivery | **Stub, not wired** | `watcher.py:184` — `# TODO: send via adapter`. `_get_owner_settings` (`watcher.py:189-191`) always returns `None` |
| Classifier + NER extraction (the "cheap" path) | **Dormant** | `model_loader.py` defaults to `llm_only` mode; no ONNX classifier/NER model files exist anywhere in the repo. Extraction currently runs 100% through LLM calls (`context_llm.py`), not the regex/classifier front-end the pipeline is designed around |
| Injection guard | **Live, confirmed wired** | `context_llm.py:46` imports it, `context_llm.py:344` actually calls `guard_check(update.raw_text)` |

**Implication**: of the 8 task types the architecture is built around, only 4 (T1–T4)
ever fire in production today. The owner-facing half of the product (summaries, alerts,
proactive insight) is fully coded but has no caller.

## 3. Determinism and feedback loop — verified

- **Deterministic**: routing (`task_router.py`), signal thresholds
  (`context_graph.py:47-51`), confidence-route gates, rule engine (`fleet_rules.yaml`),
  DB writes.
- **Non-deterministic (LLM)**: entity/intent extraction, T3/T5/T6/T7 reply generation,
  the rephrasing pass — i.e. the step that decides *what the message means* is
  open-ended, and everything deterministic downstream of it inherits that uncertainty.
- **No learning loop exists.** `_calibrate_confidence` (`context_llm.py:285-318`) is a
  static hand-written penalty formula — same behavior on day 1 and day 1000.
  `POST /correct/{event_id}` (`app/api/v1/endpoints/vfm.py:130-165`) writes an immutable
  `CORRECTION` ledger entry; grepped the whole repo for `CORRECTION` — it is written in
  exactly one place and **read back nowhere**. Operator corrections never adjust
  confidence calibration, thresholds, or produce training data.

## 4. Telegram bot production-readiness

Checked `app/adapters/telegram_adapter.py` against the deviations the assessment prompt
predicted, plus general bot-readiness basics.

| Item | Status | Evidence |
|---|---|---|
| Commit before operator confirms | **Confirmed deviation** | `event_processor.py` writes `TimelineEvent` + log row and commits (`_write_events`, ~line 426) *before* checking `confidence_route == CONFIRM` to set `needs_confirmation = True` (line 429-430). The row exists in the DB before the operator has agreed to it. |
| Idempotency key on inbound updates | **FAIL** | No `(channel, update_id)` unique key anywhere. `GroupMessage.telegram_message_id` is `unique=True` (`models.py:403`) but that's a different ID than Telegram's webhook `update_id` — it doesn't protect against webhook replay. |
| Multi-tenancy (`org_id`) | **FAIL** | Grepped `org_id`/`tenant` across `app/db/models.py` and all of `app/` — zero hits. |
| Webhook secret verification | **FAIL** | Grepped for secret-token header checks — zero hits anywhere in the repo. |
| Correction callback → original event linkage | **Confirmed deviation** | `telegram_adapter.py:143-147` — the `"correct"` callback branch just tells the operator to retype a message; it never calls `/correct/{event_id}` or references the original `TimelineEvent`. The real correction endpoint exists (`vfm.py:130-165`) but is **not wired** to this Telegram callback path at all. |
| Neutral reply contract | **Partial** | `process_telegram_message()` does return a neutral `FleetUpdate` (`reply_text`, `intent`, etc.), but it *also* performs the actual `send_message_fn()` call itself when one is passed in (`telegram_adapter.py:92-101`) — so the side effect is optional but present, not cleanly separated. |
| Group-chat orientation | **Confirmed** | `GroupMessage` model + `Watcher._queue_drain_loop` are built around `group_id`-keyed ingestion — this is a group-chat-first design, not 1:1 bot DMs. |
| Rate-limit / `retry_after` handling | **FAIL** | Grepped `retry_after` across `app/` — zero hits. |
| Message splitting (4096-char limit) | **FAIL** | Grepped `4096` across `app/` — zero hits. No chunking logic found. |
| Outbox / delivery idempotency | **FAIL** | Grepped `outbox` — zero hits. No such table in `models.py`. |
| Flood/abuse limiting | **FAIL** | Grepped `flood` — zero hits. |
| Injection guard in use | **PASS** | Confirmed call site at `context_llm.py:344`. |
| Operator allowlist | **Partial** | `_resolve_operator` (`event_processor.py:165-178`) checks `User.is_active`, but there's no broader bound-user/flood gate at the adapter boundary. |

## 5. Known issues from the assessment prompt — verified against this repo

The prompt names four known issues from a `SHIPPABLE_SCOPE.md` that doesn't exist here,
but all four are independently checkable against the code, and all four reproduce:

1. **`fuel_today`/`hours_today` missing a date filter** — confirmed, and worse than
   "missing a filter": `MachineState.fuel_added_today` / `hours_worked_today`
   (`models.py:470-471`) are incremented with a plain `+=` in
   `event_processor.py:511,515` with **no reset mechanism anywhere** — no cron job, no
   watcher task, no stored "last reset date" column. These fields accumulate forever
   across calendar days; "today" is not actually scoped to today.
2. **`fuel_baseline` null** — confirmed as a real, expected state, not just a bug:
   `fuel_rate_baseline` (`context_graph.py:240`) is `0.0` whenever
   `total_hours_30d == 0`, which is true for any machine/operator pair with under 30
   days of history. `has_baseline` (line 289) exists specifically to flag this, but the
   anomaly-detection signal (`_compute_signals`, line 303-322) silently no-ops when
   baseline is 0 rather than surfacing "insufficient data" to the operator or owner.
3. **Inconsistent T4 replies** — plausible given the code structure: T4 (off-topic) can
   be answered via the deterministic `_build_t4_reply` template (`task_router.py:210-225`)
   *or* via a free-form LLM call through `_build_agency_prompt` depending on routing
   path, and `event_processor.py` has a *third* off-topic path, `_agency_reply`
   (lines 531-566), which is a separate ad hoc LLM prompt not using the task-router
   templates at all. Three different code paths can produce a T4-shaped reply with no
   shared source of truth — this is a structural reason to expect inconsistency, though
   I did not run live messages to directly observe divergent output.
4. **99.3% accuracy claim** — **UNKNOWN**, could not verify. No test set, eval script,
   or accuracy-measurement code was found in `app/` or `tests/` during this session.
   Whoever owns that number needs to produce the eval set and script it was computed
   from.

## 6. Could not verify in this environment

- **Test suite results** — `poetry` is not on `PATH` and no system `pytest` is
  installed in this sandbox. Run `poetry install && poetry run pytest -q` yourself and
  report pass/fail counts.
- **Alembic head vs. live DB state** — 9 migration files exist under `alembic/versions/`
  (`000_initial_tables.py` through `2026_05_24_add_rephrasing_rejected_to_conversation_log.py`),
  but I did not have a running DB to check `alembic current` against `alembic heads`.
- **Where the actual Telegram bot process lives** — `telegram_adapter.py` is explicitly
  a function-style adapter meant to be called from an existing handler ("Integration:
  replace the body of your existing `/groups/messages` endpoint with a single call to
  `process_telegram_message()`" — adapter docstring, lines 4-20). The bot's token,
  update loop (webhook vs. polling), and deployment are **not in this repo**. Ask the
  human directly where that process runs.

## 7. Priority gaps to a shippable functional MVP

Ordered roughly by blast radius / what blocks what:

1. **Commit-after-confirm, not before.** CONFIRM-route writes currently land in the DB
   as fact before the operator agrees. Fix the write ordering in
   `event_processor._write_events` so a provisional/unconfirmed state is distinguishable
   and doesn't count as truth until confirmed.
2. **Wire the correction callback to the real correction endpoint.** Right now a tap on
   "Исправить ✗" in Telegram does nothing but ask for a retype — `/correct/{event_id}`
   exists but is orphaned from the bot flow.
3. **Fix `fuel_today`/`hours_today`.** Add an actual date-scoped query or a daily reset;
   right now these are lifetime-accumulating counters mislabeled as "today."
4. **Decide what to do with T5–T8.** They're fully built (templates, LLM prompts,
   rephraser frames) but have zero callers. Either wire up `is_proactive=True` /
   `recipient="owner"` call sites (watcher → owner alerts, shift-end → T7 summary), or
   explicitly descope them from the MVP so nobody assumes they work.
5. **Webhook security + idempotency + tenancy** before any real deployment: secret-token
   header check, a `(channel, update_id)` dedup key, and an `org_id`/tenant boundary if
   this will ever serve more than one fleet owner.
6. **Delivery robustness**: `retry_after` handling, 4096-char splitting, an outbox or
   equivalent for exactly-once-ish delivery. None of this exists today.
7. **Collapse the three T4 code paths** (`task_router._build_t4_reply`,
   `_build_agency_prompt`'s T4 branch, `event_processor._agency_reply`) into one, to stop
   the off-topic-reply inconsistency at its source.
8. **Produce or retract the 99.3% accuracy claim** — it's unsupported by anything in the
   repo right now.

## 8. Decisions that need a human, in priority order

1. Where does the live Telegram bot process actually run, and what library/hosting does
   it use? (Blocks almost everything in §4 and §7.)
2. Is the group-chat-first design (`GroupMessage`, group-keyed `Watcher`) intentional for
   v1, or should the MVP be 1:1 operator DMs only?
3. Should T5–T8 (owner summaries/alerts, proactive insight) be in MVP scope at all, or
   explicitly cut for v1 and revisited later?
4. Is multi-tenancy (`org_id`) needed for the MVP, or is single-owner-per-deployment
   acceptable for launch?
5. Who owns the 99.3% accuracy number, and what's the eval set?
