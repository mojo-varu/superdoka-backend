---
id: SPEC-012
title: Infrastructure and operations baseline
status: Ready
phase: 0
pillar: foundation
scope_refs: ["§9", "§13"]
adrs: [ADR-0014, ADR-0016]
depends_on: []
---

# SPEC-012: Infrastructure and operations baseline

## 1. Purpose
Run the pilot on one VPS with enough operational hygiene that a data loss or a silent failure cannot end it.

## 2. Scope and non-goals
**In:** deployment, resource measurement, backups and restore, alerts, logs, secrets, billing stance.
**Out:** high availability, autoscaling, payments and automated billing (not in v1).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-012-R01 | The system MUST run on one VPS using Docker Compose and Postgres. | MUST |
| SPEC-012-R02 | Redis MUST be added only if the existing code already uses it. No other new infrastructure. | MUST |
| SPEC-012-R03 | RAM and CPU MUST be measured with all models loaded (ONNX, plus STT and LLM if local) and recorded in this repo before choosing the VPS plan. | MUST |
| SPEC-012-R04 | A nightly encrypted `pg_dump` MUST be copied off the server. | MUST |
| SPEC-012-R05 | A restore MUST be tested once and documented as a runbook, with the date of the test. | MUST |
| SPEC-012-R06 | A health endpoint and error alerts MUST notify the builder's own Telegram chat. Alert triggers include webhook failures, rows stuck in `received`, kill-switch trips and a failed nightly backup. | MUST |
| SPEC-012-R07 | Logs MUST be structured with the correlation id (SPEC-010-R03). | MUST |
| SPEC-012-R08 | Secrets (bot token, webhook secret, provider keys, owner codes) MUST be supplied through environment or a secrets file outside version control. | MUST |
| SPEC-012-R09 | Billing MUST be manual invoicing. No billing code in v1. | MUST |
| SPEC-012-R10 | Hosting region and provider MUST be recorded together with the data-location decision (ADR-0016) before real operator data is stored. | MUST |

## 4. Interfaces and data
`docker-compose.yml`, `.env` template, `docs/runbooks/restore.md` (to be created in phase 0).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-012-01 | Given a fresh VPS, when the compose stack starts, then health returns OK and the webhook is registered. | R01 | manual |
| AC-012-02 | Given the full model set loaded, then recorded RAM is below the plan limit with headroom noted. | R03 | manual |
| AC-012-03 | Given the nightly job runs, then an encrypted dump appears off-server. | R04 | manual |
| AC-012-04 | Given a restore into a scratch database, then row counts match and the runbook is dated. | R05 | manual |
| AC-012-05 | Given a stuck inbound row or a failed backup, then the builder receives a Telegram alert. | R06 | integration |
| AC-012-06 | Given a repo scan, then no secrets are in version control. | R08 | unit (static) |
| AC-012-07 | Given the compose file, then it defines only the app, Postgres and, if already used, Redis. | R02 | unit (static) |
| AC-012-08 | Given a request, then log lines are JSON and carry the correlation id. | R07 | integration |
| AC-012-09 | Given the repository dependencies, then no billing or payment library is present. | R09 | unit (static) |
| AC-012-10 | Given the first real operator data is about to be stored, then a hosting and data-location note exists. | R10 | manual |

## 6. Open questions
- **OQ-012-1:** Hosting provider and region, and whether 152-ФЗ requires in-country storage for operator names and chat ids. Verify with a Russian lawyer or the hosting provider. This is not legal advice.
- **OQ-012-2:** Whether Redis is currently used. Check the repo.

## 7. Traceability
Scope §9, §13. ADR-0014, ADR-0016. Related specs: SPEC-010, SPEC-011.
