---
id: SPEC-017
title: Bot observability and operations (light)
status: Draft
phase: 1
pillar: foundation
scope_refs: ["§9"]
adrs: []
depends_on: [SPEC-010, SPEC-011, SPEC-014]
---

# SPEC-017: Bot observability and operations (light)

## 1. Purpose
Enough operational visibility to run the bot as a solo builder without flying blind:
one place to grep an interaction end to end, a health check, a minimal alert, and a
written runbook for deploying and rolling back. Deliberately light — this is not a
full observability stack, and it does not replace SPEC-010's harness.

## 2. Scope and non-goals
**In:** correlation-id logging for the channel layer, structured log format, health
endpoint, minimum alerting to the builder's own Telegram chat, deploy/rollback
runbook.
**Out:** metrics dashboards, distributed tracing, paging/on-call tooling (none of
this is needed at ~5 owners / ~50 operators) · the replay harness and golden set
(SPEC-010, separate concern) · the correction-rate metric (SPEC-010-R12, reused not
redefined here).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-017-R01 | Every log line produced by `app/channels/*` for a given inbound update MUST carry the same `correlation_id` used on that update's `conversation_log` row (SPEC-011-R03), so one interaction's logs can be found with a single grep. | MUST |
| SPEC-017-R02 | Channel-layer logs MUST be structured (JSON or consistent key=value), not free-text, so they can be filtered by field. | MUST |
| SPEC-017-R03 | A health endpoint MUST distinguish liveness (process is up) from readiness (worker loop is running, database is reachable), and for webhook mode MUST report whether the last Telegram API contact succeeded. | MUST |
| SPEC-017-R04 | If the unhandled-exception rate or the webhook error rate exceeds a configured threshold within a rolling window, the system MUST send one alert to the builder's own Telegram chat (per SHIPPABLE_SCOPE §9), not repeat it on every subsequent error within the same window. | MUST |
| SPEC-017-R05 | Deployment and rollback for the bot MUST be documented as a runbook (`docs/runbooks/bot_deploy.md`) covering the separate compose project and database, webhook setup/verification via the admin CLI and `getWebhookInfo`, and the polling fallback. The rollback path MUST be exercised at least once (manually, by the human) before the pilot starts. | MUST |

## 4. Interfaces and data
No new tables. Reuses `conversation_log.correlation_id` (SPEC-011-R03). The alert
threshold and window are configuration, not constants.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-017-01 | Given one inbound update, when its logs are collected, then every line for that update shares one `correlation_id` matching its `conversation_log` row. | R01 | integration |
| AC-017-02 | Given a sample of channel-layer log output, then every line parses as structured (JSON or key=value), not free text. | R02 | unit |
| AC-017-03 | Given the database stopped, when the health endpoint is queried, then readiness reports false while liveness still reports true. | R03 | integration |
| AC-017-04 | Given a burst of simulated errors exceeding the threshold within one window, then exactly one alert is sent to the builder's chat for that window, not one per error. | R04 | integration |
| AC-017-05 | Given the deploy runbook, when a human follows it on a disposable environment, then a rollback completes and the system returns to the previous working state. | R05 | manual |

## 6. Open questions
- **OQ-017-1:** Alert threshold and window starting values. Pick conservatively and tune after the first week of real traffic.
- **OQ-017-2:** Whether the builder's alert chat is the same Telegram account used for the bot's own BotFather management, or separate. Operational preference, ask the human.

## 7. Traceability
Scope §9. Related specs: SPEC-010, SPEC-011, SPEC-014.
