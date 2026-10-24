---
id: SPEC-014
title: Telegram bot runtime and delivery resilience
status: Draft
phase: 1
pillar: 2
scope_refs: ["§3 Pillar 2", "§9", "§13"]
adrs: [ADR-0018, ADR-0019, ADR-0020, ADR-0025]
depends_on: [SPEC-001, SPEC-011]
---

# SPEC-014: Telegram bot runtime and delivery resilience

## 1. Purpose
The bot takes inbound Telegram traffic without losing, duplicating or blocking on it,
and sends replies without crashing on Telegram's own failure modes (rate limits,
blocked users, oversized text). The engine and the Telegram runtime stay strictly
separated so a slow understanding call never delays the webhook response.

## 2. Scope and non-goals
**In:** intake mode selection (webhook/polling), webhook secret verification,
acknowledge-fast/process-in-worker, per-chat ordering, graceful shutdown, health
endpoint, outbound message splitting, escaping, `retry_after` handling, blocked-user
handling, outbound timeouts, the admin CLI, the engine/channel import boundary.
**Out:** a full transactional outbox (deferred, see ADR-0025) · callback data design
(SPEC-015) · consent and flood limits (SPEC-016) · structured logging content and
alerting (SPEC-017) · test infrastructure itself (SPEC-018, though this spec's
requirements are what SPEC-018 tests).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-014-R01 | The bot MUST support two intake modes selected by `TELEGRAM_MODE=polling\|webhook`, sharing the same handler code for both. Polling is for local development; webhook is for the VPS. | MUST |
| SPEC-014-R02 | The webhook route MUST verify Telegram's secret-token header before any database access. A missing or incorrect secret MUST be rejected with no row written and no pipeline run. | MUST |
| SPEC-014-R03 | The webhook (and the polling loop) MUST insert the inbound row and return success **before** running the understanding/agency pipeline. A duplicate `(channel, update_id)` (SPEC-011-R04) MUST return success immediately without running the pipeline again or sending a second reply. | MUST |
| SPEC-014-R04 | Processing MUST happen in a worker (an asyncio task started with the app, plus a separate entry point `python -m app.channels.worker` for the production instance) that claims `received` rows. At most one message per chat MUST be in flight at a time, so per-chat order is preserved, and overall concurrency MUST be capped (starting value: configurable, default low single digits) because LLM extraction may be slow. | MUST |
| SPEC-014-R05 | A recovery routine MUST re-claim or flag inbound rows stuck in `received` beyond a threshold (starting value 5 minutes, shared with SPEC-001-R10) so a crashed worker never silently drops a message. | MUST |
| SPEC-014-R06 | An admin CLI (`python -m app.channels.telegram.admin set-webhook\|delete-webhook\|info`) MUST exist, MUST NOT print the bot token under any subcommand or error path, and MUST refuse to start polling in the `prod` environment while a webhook is currently set (checked via `getWebhookInfo`). | MUST |
| SPEC-014-R07 | The process MUST shut down gracefully: in-flight messages either complete or are left in a recoverable `received`/`processing` state (never silently lost), and a health endpoint MUST report readiness distinct from liveness. | MUST |
| SPEC-014-R08 | Outbound text MUST be split at paragraph boundaries to stay under Telegram's current per-message text limit. The exact limit MUST be verified against current Telegram Bot API documentation at implementation time, not hardcoded from this spec. | MUST |
| SPEC-014-R09 | Outbound sends MUST default to a `parse_mode` that cannot be used for injection (plain text, or markup with all user-sourced substrings escaped). No raw operator or LLM text is ever interpolated into a `parse_mode` string without escaping. | MUST |
| SPEC-014-R10 | On a Telegram rate-limit response, the send wrapper MUST honour the `retry_after` value and retry up to a configured cap (starting value 3 attempts), then log the failure and drop the single outbound message rather than blocking the worker. A full retry/outbox queue is explicitly deferred (ADR-0025). | MUST |
| SPEC-014-R11 | A "bot was blocked by the user" (or equivalent) delivery error MUST mark that `app_user` unreachable (a flag, not a deletion) and MUST NOT crash the worker or retry indefinitely. | MUST |
| SPEC-014-R12 | Every outbound Telegram API call MUST have a timeout distinct from and shorter than the overall pipeline timeout, so a slow Telegram API cannot itself stall the worker. | MUST |
| SPEC-014-R13 | The engine (`app/core`, `app/services`, `app/db`, `app/rules`) MUST NOT import `app/channels` or any aiogram module. Code under `app/channels/*` MUST import only `app/channels/base.py` and the engine's single entry point (`handle_inbound`) from the engine side. This boundary MUST be enforced by a static test, not by convention alone. | MUST |

## 4. Interfaces and data
- Engine entry point: `handle_inbound(NormalisedInbound) -> list[OutboundMessage]` — returns replies, never sends anything itself (ADR-0020).
- `app/channels/base.py`: `ChannelAdapter` protocol, `NormalisedInbound`, `OutboundMessage` (channel-neutral; reused by SPEC-002 for voice).
- Settings: `TELEGRAM_MODE`, `BOT_TOKEN`, `WEBHOOK_SECRET`, `WEBHOOK_BASE_URL`, `BOT_ENV` (`dev`|`prod`), `DATABASE_URL`. Missing required values fail fast with a clear error at startup.
- Tables touched: `conversation_log` (SPEC-011-R03, R04), `pending_confirmation` (SPEC-004 amendment, see `docs/proposals/AMENDMENTS.md`).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-014-01 | Given a webhook POST with a missing or wrong secret-token header, then it is rejected, no database row is written, and the pipeline does not run. | R02 | integration |
| AC-014-02 | Given the same `(channel, update_id)` delivered twice to the webhook, then exactly one inbound row, one event (if any) and one outbound reply exist. | R03 | integration |
| AC-014-03 | Given a slow pipeline (simulated delay), when a webhook request arrives, then the HTTP response returns well before the pipeline finishes. | R03, R04 | integration |
| AC-014-04 | Given two quick messages from the same chat, when both are queued, then they are processed in the order received and never concurrently for that chat. | R04 | integration |
| AC-014-05 | Given a row stuck in `received` past the threshold (simulated crash), when the recovery routine runs, then it is re-claimed or flagged, and no duplicate event results if it eventually completes. | R05 | integration |
| AC-014-06 | Given the admin CLI, when `info` or `set-webhook` run, then the token never appears in stdout, stderr or logs; when polling is started in `BOT_ENV=prod` with a webhook currently set, it refuses and exits non-zero. | R06 | integration (manual token check) |
| AC-014-07 | Given a shutdown signal mid-processing, then no in-flight message is lost silently, and the health endpoint reflects the shutting-down state. | R07 | integration |
| AC-014-08 | Given a reply longer than Telegram's current text limit, then it is split at paragraph boundaries into multiple messages, each under the limit. | R08 | unit |
| AC-014-09 | Given operator or LLM text containing Markdown/HTML-special characters, then the sent message renders the literal characters rather than being interpreted as formatting. | R09 | unit |
| AC-014-10 | Given a simulated `retry_after` response, then the send is retried within the configured cap and then gives up cleanly; a simulated "blocked by user" error marks the user unreachable without raising. | R10, R11 | integration |
| AC-014-11 | Given the codebase, when a static check scans `app/core`, `app/services`, `app/db`, `app/rules` for imports of `app/channels` or `aiogram`, and scans `app/channels` for imports of engine modules other than the contract and `handle_inbound`, then none are found. | R13 | unit (static) |
| AC-014-12 | Given `TELEGRAM_MODE=polling` and `TELEGRAM_MODE=webhook` in two separate runs, then both route through the same handler and produce identical `handle_inbound` results for the same input; given a stalled outbound Telegram call exceeding the outbound timeout, then it is cancelled before the overall pipeline timeout fires. | R01, R12 | integration |

## 6. Open questions
- **OQ-014-1:** Exact Telegram message-length limit and `retry_after` semantics MUST be re-verified against current Bot API docs before WP-F is implemented (R08, R10) — do not trust a number carried over from training data.
- **OQ-014-2:** Concurrency cap starting value. Pick conservatively (the pilot is ~5 owners / ~50 operators) and make it configurable.
- **OQ-014-3:** Whether the worker and the webhook process are the same OS process for the demo instance, or always split. Affects `docs/runbooks/bot_deploy.md`.

## 7. Traceability
Scope §3 Pillar 2, §9, §13. ADR-0018, ADR-0019, ADR-0020, ADR-0025. Related specs: SPEC-001, SPEC-011, SPEC-015, SPEC-018.
