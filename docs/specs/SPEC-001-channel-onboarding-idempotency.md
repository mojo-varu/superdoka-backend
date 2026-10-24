---
id: SPEC-001
title: Telegram channel, onboarding, idempotent inbound, corrections entry point
status: Ready
phase: 1
pillar: 2
scope_refs: ["§3 Pillar 2", "§8 onboarding", "§13"]
adrs: [ADR-0001, ADR-0006, ADR-0013]
depends_on: [SPEC-011, SPEC-004]
---

# SPEC-001: Telegram channel, onboarding, idempotent inbound, corrections entry point

## 1. Purpose
An operator writes to a Telegram bot in a private chat the way they would tell a foreman. The system binds that chat to one operator and organisation using only a link, never double-logs a retried webhook, and routes corrections into the pipeline. The owner registers, adds machines and invites operators.

## 2. Scope and non-goals
**In:** webhook intake, private-chat enforcement, `ChannelAdapter`, owner registration, machine registration, operator invites, idempotency, correction entry point, REST sandbox parity.
**Out:** voice handling (SPEC-002), understanding (SPEC-003), event storage rules and correction semantics (SPEC-004), group chats and MAX (not in v1).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-001-R01 | The system MUST receive Telegram updates on a webhook endpoint that verifies Telegram's secret-token header and rejects requests without it. | MUST |
| SPEC-001-R02 | The system MUST process only private 1:1 chats. For group, supergroup or channel updates it MUST skip the pipeline and send at most one "please write to me privately" reply per chat. | MUST |
| SPEC-001-R03 | All Telegram-specific code MUST live behind a `ChannelAdapter` interface: `parse_inbound` returns a channel-neutral `NormalisedInbound` (channel, update_id, chat_id, message_id, timestamp, text or media reference), `send_outbound` accepts a channel-neutral `OutboundMessage` including inline buttons, `download_media` fetches media. Pipeline modules MUST NOT import Telegram types. | MUST |
| SPEC-001-R04 | The owner MUST be able to register with `/start <owner_code>`, which creates or links an `app_user` with role `owner` in the org that owns the code. | MUST |
| SPEC-001-R05 | The owner MUST be able to add machines by uploading a CSV or by a chat command (alias, registration number, type, class). Duplicate aliases within an org MUST be rejected with a clear message. | MUST |
| SPEC-001-R06 | The owner MUST be able to generate an operator invite for a named operator, optionally bound to a machine alias. The bot returns a deep link `t.me/<bot>?start=<invite_token>`. Tokens are single-use and expire (starting value 72 hours, configurable). | MUST |
| SPEC-001-R07 | `/start <invite_token>` MUST bind the sender's `chat_id` to the invite's operator and org. An invalid, expired or used token MUST produce a clear message and no binding. A `chat_id` MUST bind to at most one `app_user`. After binding the bot sends one short welcome telling the operator to write as they would to a foreman, and asks at most one question. | MUST |
| SPEC-001-R08 | The inbound `conversation_log` row MUST be inserted before the pipeline runs, with a unique key on `(channel, update_id)`. On a unique violation the handler MUST return success immediately and MUST NOT run the pipeline. | MUST |
| SPEC-001-R09 | A duplicate update MUST NOT produce a second outbound reply or a second timeline event. | MUST |
| SPEC-001-R10 | Each inbound row MUST carry a processing status (`received`, `processed`, `failed`). A recovery job MUST reprocess or flag rows stuck in `received` beyond a threshold (starting value 5 minutes) and alert the builder. | MUST |
| SPEC-001-R11 | When understanding detects a correction ("не 150, а 105"), the pipeline MUST resolve the target to the most recent matching event in the operator's current session. If the target is ambiguous it MUST CLARIFY. A confirmed correction is stored as in SPEC-004-R06. | MUST |
| SPEC-001-R12 | Messages from an unbound `chat_id` that are not `/start` MUST receive one onboarding instruction and MUST NOT create state. | MUST |
| SPEC-001-R13 | Owner-only commands (`/today`, `/machine`, `/waybill`, `/trace`, `/invite`, machine management) MUST check role `owner` in the sender's org. Operators receive a polite refusal. | MUST |
| SPEC-001-R14 | `POST /api/v1/vfm/update` MUST keep working through the same pipeline with `channel='rest'`, for sandbox and replay tests. | SHOULD |

## 4. Interfaces and data
- Tables: `app_user`, `invite`, `machine`, `conversation_log` (see SPEC-011).
- Commands: `/start <token>`, `/invite <name> [machine]`, `/addmachine <alias> <reg> <type>` (names are a proposal, see OQ-001-5).
- `NormalisedInbound` and `OutboundMessage` are defined once in the adapter package and reused by SPEC-002.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-001-01 | Given a message from a group chat, when the webhook receives it, then no pipeline runs, no `conversation_log` operational row is created, and at most one private-chat reply is sent. | R02 | integration |
| AC-001-02 | Given the codebase, when a static check scans pipeline packages, then none import Telegram types. | R03 | unit (static) |
| AC-001-03 | Given an owner with an invite for operator "Иван", when Иван taps the link, then his chat is bound, he gets one welcome with at most one question, and total owner-plus-operator onboarding takes under two minutes in a manual run. A reused or expired token binds nothing. | R06, R07 | integration + manual |
| AC-001-04 | Given a logged fuel of 150 L this session, when the operator writes "не 150, а 105", then a correction event referencing the original is appended and the effective fuel is 105. With two fuel events in the session and an unclear target, the bot asks which one. | R11 | integration, golden |
| AC-001-05 | Given a webhook payload, when it is delivered twice, then exactly one inbound row, one event and one reply exist. | R08, R09 | integration |
| AC-001-06 | Given a crash between inbound insert and pipeline completion, when the recovery job runs, then the row is reprocessed once or flagged, and no duplicate event results. | R10 | integration |
| AC-001-07 | Given an operator, when they send `/waybill`, then they get a refusal and no export is created. | R13 | integration |
| AC-001-08 | Given an unbound chat, when it sends "залил 100", then it gets the onboarding instruction and no timeline event or session is created. | R12 | integration |
| AC-001-09 | Given the sandbox REST call, when `POST /api/v1/vfm/update` is used, then it produces the same decisions as the Telegram path for the same text. | R14 | integration |
| AC-001-10 | Given a webhook call with a missing or wrong secret header, then it is rejected and no row is written. | R01 | integration |
| AC-001-11 | Given `/start <owner_code>`, then an owner is created or linked. An invalid code binds nothing. | R04 | integration |
| AC-001-12 | Given a CSV of three machines, then three machines are created. A duplicate alias is rejected with a clear message. | R05 | integration |

## 6. Open questions
- **OQ-001-1:** How is the owner code issued and delivered? Manual for the first customers. Owner: Varun.
- **OQ-001-2:** Invite expiry value. Starting value 72 h. Confirm with the pilot owner.
- **OQ-001-3:** Do operators already coordinate in groups? Ask the pilot owner (blocks nothing, informs ADR-0001 revisit).
- **OQ-001-4:** Telegram reachability on the pilot operators' phones and networks. Test before pilot. Blocks pilot start.
- **OQ-001-5:** Command names and whether Russian aliases are wanted. Telegram command names are Latin; keep `/` commands Latin and use button labels in Russian.

## 7. Traceability
Scope §3 Pillar 2, §8, §13. ADR-0001, ADR-0006, ADR-0013. Invariants 7 and 9 indirectly. Related specs: SPEC-002, SPEC-004, SPEC-011.
