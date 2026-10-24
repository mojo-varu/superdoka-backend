---
id: SPEC-015
title: Bot interaction design and copy
status: Draft
phase: 1
pillar: 2
scope_refs: ["§3 Pillar 2", "§3 Pillar 3"]
adrs: [ADR-0022, ADR-0023, ADR-0024]
depends_on: [SPEC-001, SPEC-004, SPEC-005, SPEC-014]
---

# SPEC-015: Bot interaction design and copy

## 1. Purpose
Everything the operator actually sees: the command menu, the onboarding and consent
flow, the ✅/✏️ confirmation loop, correction handling, and every piece of Russian
copy — kept correct, consistent and testable without re-deriving it from the engine
each time.

## 2. Scope and non-goals
**In:** command menu, `/start <token>` presentation, consent notice UI, welcome/help
copy, ✅/✏️ confirmation buttons, callback data contract, double-tap and stale-tap
behaviour, correction flow presentation, voice/photo polite replies, persisted
conversation state, error copy, the single Russian-copy module.
**Out:** webhook/delivery mechanics (SPEC-014) · consent *record* storage and flood
limiting (SPEC-016) · the underlying binding/idempotency logic (SPEC-001) · the
underlying commit-after-confirm write path (SPEC-004 amendment, SPEC-005).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-015-R01 | The bot's command menu (as registered with BotFather) MUST list only commands the code actually implements. For the validation slice this is `/start` and `/help`; owner commands (`/today`, `/machine`, `/waybill`, `/trace`) are added only once SPEC-008/SPEC-009 ship. | MUST |
| SPEC-015-R02 | `/start <invite_token>` MUST present the binding outcome from SPEC-001-R07 with a short Russian welcome on success, and a short Russian "invalid or expired link" message on failure, each in at most two sentences. | MUST |
| SPEC-015-R03 | On first use, before any operator message is processed beyond the consent prompt itself, the bot MUST show a consent notice with an inline confirm button. The notice text is **marked draft, pending human and legal review** before pilot. | MUST |
| SPEC-015-R04 | Confirm-route and implausible-value results (SPEC-005-R02 `commit=after_confirm`) MUST be shown back to the operator with ✅ ("Верно") / ✏️ ("Исправить") inline buttons. No `TimelineEvent` exists until ✅ is tapped (see `docs/proposals/AMENDMENTS.md` for the SPEC-004 pending-confirmation amendment this depends on). | MUST |
| SPEC-015-R05 | Callback data MUST be versioned, fit within Telegram's current callback-data size limit (verify at implementation time), expire (starting value: same window as the pending-confirmation row, see ADR-0023), be bound to exactly one pending item, and be usable only by the chat that owns it. | MUST |
| SPEC-015-R06 | A double tap on ✅ MUST create exactly one `TimelineEvent` — the second tap is answered with a short "already recorded" callback answer and causes no further write. | MUST |
| SPEC-015-R07 | A stale callback (expired, already resolved, or referencing a pending row that no longer exists) MUST be answered with a short, safe Russian message via `answerCallbackQuery` and MUST cause no state change. | MUST |
| SPEC-015-R08 | ✏️ MUST store `awaiting_correction` in `chat_state` (SPEC-011 amendment) referencing the pending or committed item. The next text message from that chat MUST resolve it: if the original item was not yet committed, it replaces the pending value; if it was already committed, it creates a correction event referencing the original (`corrects_event_id`, SPEC-004-R06) by calling the same logic `POST /correct/{event_id}` calls, in-process, not over HTTP. | MUST |
| SPEC-015-R09 | Voice messages (until SPEC-002 ships) MUST receive a polite "voice is not supported yet, please send text" reply, and the Telegram `file_unique_id` MUST be stored on the `conversation_log` row for later manual transcription. No event is created. | MUST |
| SPEC-015-R10 | Photos and other unsupported media MUST receive one polite reply and create no event. | MUST |
| SPEC-015-R11 | Every Russian user-facing string MUST live in one module (`app/channels/telegram/copy_ru.py`). No Russian string is inlined elsewhere in `app/channels`. | MUST |
| SPEC-015-R12 | Error conditions (unparseable callback, unknown command, internal failure) MUST produce a short, clear Russian message and MUST NOT expose stack traces, exception text, or internal identifiers to the chat. | MUST |
| SPEC-015-R13 | Conversation state (`awaiting_correction` and any future multi-turn state) MUST be persisted in the `chat_state` table, never in process memory, so a worker restart does not lose a pending correction prompt or require the operator to repeat themselves. | MUST |

## 4. Interfaces and data
- Tables: `pending_confirmation`, `chat_state` (both new — see `docs/proposals/AMENDMENTS.md`, owned by SPEC-004/SPEC-011).
- Module: `app/channels/telegram/copy_ru.py` — single source for all Russian strings.
- Callback data format: `v1:<action>:<pending_id>:<expiry_or_nonce>` (exact format is ADR-0024's decision, not fixed by this spec).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-015-01 | Given an unbound chat sends anything other than `/start`, then it receives one onboarding instruction and creates no `app_user` state, no `chat_state`, no event. | R02 (cross-ref SPEC-001-R12) | integration |
| AC-015-02 | Given a first-time bound operator, when they send their first message, then they see the consent notice with a confirm button before any operational reply, and no operator message is processed as data until consent is confirmed. | R03 | integration |
| AC-015-03 | Given a confirm-route fuel log, then no `TimelineEvent` exists and a `pending_confirmation` row exists with ✅/✏️ buttons shown. | R04 | integration |
| AC-015-04 | Given the ✅ button tapped twice in quick succession, then exactly one `TimelineEvent` exists; the second tap's callback answer says it was already recorded. | R06 | integration |
| AC-015-05 | Given a callback for a pending item that has expired or already resolved, then the bot answers safely and nothing changes in the database. | R07 | integration |
| AC-015-06 | Given ✏️ tapped on a committed fuel-log event, when the next message is "не 150, а 105", then a correction event is created referencing the original, and `effective_events` (SPEC-004-R07) reflects 105. | R08 | integration |
| AC-015-07 | Given a voice note sent to the bot, then the reply says voice is not supported yet, `file_unique_id` is stored on the conversation log row, and no `TimelineEvent` is created. A photo gets one polite reply and no event. | R09, R10 | integration |
| AC-015-08 | Given the `app/channels/telegram` package, when searched for Russian string literals outside `copy_ru.py`, then none are found. | R11 | unit (static) |
| AC-015-09 | Given a worker restart between ✏️ and the corrected message, then the correction is still correctly resolved against the pending `chat_state` row. | R13 | integration |
| AC-015-10 | Given the BotFather command list, then it contains only `/start` and `/help`; given a generated callback payload, then it parses as `v<version>:<action>:<pending_id>:<nonce>`, fits Telegram's current callback-data size limit, and a tap from a chat that does not own the referenced `pending_id` is rejected as a stale/unauthorised callback. | R01, R05 | unit |

## 6. Open questions
- **OQ-015-1:** Final consent notice wording needs human and legal review before pilot (R03). Do not ship default copy as final.
- **OQ-015-2:** Callback data expiry window starting value. Should roughly match how long an operator is plausibly mid-shift and might tap a stale button — propose 24 hours, confirm with the pilot owner.
- **OQ-015-3:** Whether `/help` text differs for owner vs operator role. Default to role-aware copy once SPEC-008/009 land; out of scope for the validation slice.

## 7. Traceability
Scope §3 Pillar 2, §3 Pillar 3. ADR-0022, ADR-0023, ADR-0024. Related specs: SPEC-001, SPEC-002, SPEC-004, SPEC-005, SPEC-014, SPEC-016.
