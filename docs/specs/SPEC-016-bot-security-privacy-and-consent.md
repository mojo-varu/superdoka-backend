---
id: SPEC-016
title: Bot security, privacy and consent
status: Draft
phase: 1
pillar: foundation
scope_refs: ["§9", "§13"]
adrs: [ADR-0021]
depends_on: [SPEC-001, SPEC-011, SPEC-014, SPEC-015]
---

# SPEC-016: Bot security, privacy and consent

## 1. Purpose
Only people the owner actually invited can make the bot act, abusive or runaway chat
traffic cannot overwhelm the pipeline, nothing secret ever lands in a log, and an
operator's consent and data rights are recorded and honourable on request.

## 2. Scope and non-goals
**In:** bound-user allowlisting (as a security boundary, not just a routing rule),
per-chat flood limiting, log redaction, consent record, data export and deletion,
token rotation.
**Out:** the webhook secret-token *mechanism* (SPEC-014-R02, referenced not
duplicated) · the consent *UI* (SPEC-015-R03) · legal review of consent wording
(open question, human-owned) · 152-ФЗ data-residency decision (ADR-0016, open).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-016-R01 | Only a `chat_id` bound to an `app_user` (SPEC-001-R07) MUST reach the understanding/agency pipeline. This allowlist check MUST run before any LLM call, extraction, or state mutation — an unbound or group chat is rejected at the channel boundary, not inside the engine. | MUST |
| SPEC-016-R02 | Each bound chat MUST be subject to a simple flood limit (starting value: N messages per rolling minute, configurable). Messages over the limit receive at most one "please slow down" reply per window and are not queued into the pipeline. | MUST |
| SPEC-016-R03 | The bot token and any other secret MUST NEVER appear in logs, error messages, or exception text, under any code path including failure paths. | MUST |
| SPEC-016-R04 | At INFO level, logs MUST record operator id, chat id, machine id and correlation id, not raw message text. Raw text MAY be logged at DEBUG level only, gated by an explicit, default-off environment flag never enabled in the `prod` `BOT_ENV`. | MUST |
| SPEC-016-R05 | On first use, a consent record (timestamp, consent-text version, `app_user_id`) MUST be stored before any operator message is treated as operational data (the UI for this is SPEC-015-R03; this requirement owns the stored record). | MUST |
| SPEC-016-R06 | An admin-triggered export MUST produce all `conversation_log` and `timeline_event` rows for one operator or one org, in a portable format (for example JSON or CSV), for data-subject access requests. | MUST |
| SPEC-016-R07 | An admin-triggered deletion request MUST remove or irreversibly anonymise personal identifiers (name, chat id) for one operator. Because `timeline_event` is append-only by design (ADR-0005) and MUST NOT be deleted wholesale, the exact mechanism (anonymise-in-place vs. a tombstone linking table) is an open question (OQ-016-1) and MUST be resolved with legal input before this requirement is marked Ready. | MUST |
| SPEC-016-R08 | The bot token MUST be rotatable (a new BotFather token swapped into the environment) without any data migration. The admin CLI's `set-webhook` (SPEC-014-R06) MUST re-register the webhook under the new token. | MUST |

## 4. Interfaces and data
- Tables: `consent` (or a consent column set on `app_user` — implementation detail, not fixed here), referencing `app_user`.
- Reuses: `conversation_log`, `timeline_event` (SPEC-011) for export; `app_user` for the allowlist and token-rotation requirements.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-016-01 | Given a message from an unbound chat or a group chat, then no LLM call, extraction, or database write beyond the onboarding/group-notice reply occurs. | R01 | integration |
| AC-016-02 | Given more than N messages in a chat within one minute, then messages beyond the limit get at most one "slow down" reply and are not processed. | R02 | integration |
| AC-016-03 | Given any code path including a forced exception during token loading, when logs are inspected, then the token string never appears. | R03 | unit + manual log review |
| AC-016-04 | Given a normal operator message processed with `BOT_ENV=prod` and the debug flag unset, then the INFO-level log line contains ids but not the raw message text. | R04 | unit |
| AC-016-05 | Given a new operator's first message, then a consent record exists before any operational reply is produced, and a second message from the same operator does not re-prompt consent. | R05 | integration |
| AC-016-06 | Given an export request for one operator, then the output contains that operator's `conversation_log` and `timeline_event` rows and no other operator's rows. | R06 | integration |
| AC-016-07 | Given a deletion request for one operator (manual trigger), then personal identifiers for that operator are removed or anonymised, and the operational ledger's referential integrity (e.g. `effective_events`, SPEC-004-R07) is unaffected. | R07 | integration (blocked on OQ-016-1) |
| AC-016-08 | Given a token rotation (dev token swap in a disposable local environment), then `set-webhook` succeeds under the new token and the old token is no longer accepted by Telegram for this bot. | R08 | manual (cannot be tested without a live call; write the exact command for the human) |

## 6. Open questions
- **OQ-016-1:** Deletion mechanism for an operator's personal identifiers inside an append-only ledger. Needs a Russian lawyer's input per SHIPPABLE_SCOPE §13 (152-ФЗ). Blocks R07 reaching Ready.
- **OQ-016-2:** Flood-limit starting value N. Pick conservatively; a legitimate operator rarely sends more than a few messages per minute.
- **OQ-016-3:** Whether export/deletion are admin-CLI-only or need an in-chat command for the operator themselves. Default to admin-CLI-only for the validation slice; ask the pilot owner.

## 7. Traceability
Scope §9, §13. ADR-0021 (separate dev/prod tokens). Related specs: SPEC-001, SPEC-011, SPEC-014, SPEC-015.
