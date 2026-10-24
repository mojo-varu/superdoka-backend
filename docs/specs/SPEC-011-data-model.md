---
id: SPEC-011
title: v1 data model and migrations
status: Ready
phase: 0
pillar: foundation
scope_refs: ["§6 H1", "§8"]
adrs: [ADR-0004, ADR-0005, ADR-0006, ADR-0013]
depends_on: []
---

# SPEC-011: v1 data model and migrations

## 1. Purpose
One authoritative list of v1 tables, keys and database-level guarantees. Other specs reference these requirements instead of redefining tables.

## 2. Scope and non-goals
**In:** tables, constraints, tenant scoping, immutability, migrations, time handling.
**Out:** projection logic (SPEC-004), query layer details, reporting.

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-011-R01 | Every table MUST carry `org_id` NOT NULL with a foreign key to `org`. All access MUST go through a data-access layer that scopes by `org_id`. | MUST |
| SPEC-011-R02 | v1 tables: `org` (name, timezone, digest_time, quiet_hours, expected_shift_start), `app_user` (org, role owner or operator, channel chat id, name, locale), `invite` (token, org, role, operator, expires_at, used_at), `machine` (org, alias, reg_number, type, class), `shift_session` (org, operator, machine, object name and address, started_at, ended_at), `conversation_log`, `timeline_event`, `suppression`, `digest_log`, `waybill_export`, `finding`. | MUST |
| SPEC-011-R03 | `conversation_log` MUST have columns: org, session, operator, machine, channel, direction, raw text, source (`text` or `voice`), STT metadata, intent, confidence, confidence route, entities (JSON), policy action, task type, reply text, `reply_source` (`template`, `llm`, `fallback`), validator verdict, latency, `timeline_event_id` (nullable), `corrected_by` (nullable), correlation id, processing status, pipeline version stamp (SPEC-010-R02). | MUST |
| SPEC-011-R04 | `conversation_log` MUST have a unique key on `(channel, update_id)` for inbound rows. | MUST |
| SPEC-011-R05 | `timeline_event` (org, session, machine, operator, event type, payload JSON, schema version, `source_conversation_id`, `corrects_event_id` nullable) MUST be append-only, enforced by revoked privileges and a raising trigger (SPEC-004-R05, R08). An index on `corrects_event_id` MUST exist. | MUST |
| SPEC-011-R06 | `shift_session.machine_id` MUST be NOT NULL. | MUST |
| SPEC-011-R07 | `suppression` MUST have a unique key `(org, machine, rule, window_key)`. | MUST |
| SPEC-011-R08 | `digest_log` MUST have a unique key `(org, date)`. | MUST |
| SPEC-011-R09 | `waybill_export` (org, machine, range, generated_at, event ids included, content hash) rows MUST NOT be updated after creation. | MUST |
| SPEC-011-R10 | `app_user` MUST be unique on `(channel, chat_id)`. `invite.token` MUST be unique, single-use and carry an expiry. | MUST |
| SPEC-011-R11 | Schema changes MUST use Alembic migrations run by a separate migration role. The application role MUST NOT be able to alter tables. | MUST |
| SPEC-011-R12 | All timestamps MUST be stored as UTC `timestamptz`. Day boundaries MUST use the org timezone at query time. | MUST |
| SPEC-011-R13 | `timeline_event.payload` MUST carry `schema_version`, and a payload that fails its schema MUST be rejected before insert. | MUST |

## 4. Interfaces and data
The table list above is normative. Column types are an implementation detail unless stated.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-011-01 | Given orgs A and B, when org A's data layer queries machines, events, digests or exports, then nothing from B is returned, including through ids guessed from B. | R01 | integration |
| AC-011-02 | Given two inserts with the same `(channel, update_id)`, then the second fails with the unique violation. | R04 | integration |
| AC-011-03 | Given the application role, then UPDATE and DELETE on `timeline_event` and UPDATE on `waybill_export` fail. | R05, R09 | integration |
| AC-011-04 | Given a session insert without a machine, then it fails. | R06 | integration |
| AC-011-05 | Given a duplicate suppression key or digest key, then the second insert fails. | R07, R08 | integration |
| AC-011-06 | Given a fresh database, when migrations run, then the schema matches the model, and the application role cannot run DDL. | R11 | integration |
| AC-011-07 | Given an event near local midnight in a non-UTC org, then it is assigned to the right local day. | R12 | unit |
| AC-011-08 | Given a fresh database after migrations, then every table in R02 exists with `org_id` NOT NULL and a foreign key, and `conversation_log` has the columns in R03. | R02, R03 | integration |
| AC-011-09 | Given a second binding of the same `(channel, chat_id)`, a reused invite, or an expired invite, then each fails. | R10 | integration |
| AC-011-10 | Given an event payload without `schema_version` or failing its schema, then insert is rejected. | R13 | integration |

## 6. Open questions
- **OQ-011-1:** Reconcile with the existing `logbuk-backend` models and Alembic revisions. List differences in an appendix before implementing.
- **OQ-011-2:** Whether to use Postgres row-level security as defence in depth for tenant scoping (ADR-0013 revisit).

## 7. Traceability
Scope §6 H1, §8. ADR-0004, ADR-0005, ADR-0006, ADR-0013. Invariants 1 and 9. Related specs: all.
