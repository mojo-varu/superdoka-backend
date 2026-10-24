---
id: SPEC-008
title: Digital ЭСМ-2 waybill export
status: Ready
phase: 2
pillar: 1
scope_refs: ["§1", "§3 Pillar 1", "§13", "§14 inv. 1", "§15.2"]
adrs: [ADR-0008, ADR-0009]
depends_on: [SPEC-004, SPEC-011]
---

# SPEC-008: Digital ЭСМ-2 waybill export

## 1. Purpose
The owner types `/waybill <machine> <date|range>` and receives a PDF that looks like the waybill they know, filled only from what operators actually reported, with everything else visibly marked "не зафиксировано". This is the wedge.

## 2. Scope and non-goals
**In:** command, period export, PDF template, chat-to-field mapping, provenance, export record.
**Out:** legal claims of equivalence, photo or OCR of paper waybills, one-tap foreman confirmation (post-pilot candidates), editing the timeline.

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-008-R01 | `/waybill <machine alias> <date or range>` MUST be available to owners. Dates accept `YYYY-MM-DD` and `DD.MM.YYYY`. A range is `from..to`. Invalid input returns a help message. | MUST |
| SPEC-008-R02 | The PDF MUST be generated server-side with embedded Cyrillic fonts, following a template mapped against the **official form** (Типовая межотраслевая форма № ЭСМ-2). | MUST |
| SPEC-008-R03 | A period export MUST produce one document for the date range, with a block per shift or day. A maximum range applies (starting value 10 days, matching the 1 to 10 days one paper waybill covers). | MUST |
| SPEC-008-R04 | Chat-to-field mapping MUST be: `shift_start` gives departure time, machine and object; `hours_log` gives meter readings; `fuel_log` gives fuel issued; `shift_end` gives return time. Organisation, customer, machine and state number, operator and date come from master data and the session. | MUST |
| SPEC-008-R05 | Every filled value MUST trace to a `conversation_log` id through the event's `source_conversation_id`. The PDF MUST include a provenance appendix listing each filled field with the source message timestamp. | MUST |
| SPEC-008-R06 | Every field with no evidence MUST print "не зафиксировано". Fields chat cannot legitimately fill (medical exam, mechanic sign-off, customer or foreman signature) MUST always print that text. | MUST |
| SPEC-008-R07 | The export MUST NOT use defaults or last-known values to fill gaps. | MUST |
| SPEC-008-R08 | Values MUST come from `effective_events` (SPEC-004-R07). Corrected values MAY be marked "исправлено". | MUST |
| SPEC-008-R09 | The PDF header and bot messages MUST describe the document as a digital waybill record or companion and MUST NOT claim legal equivalence. Draft header text: "Цифровая запись путевого листа (ЭСМ-2). Сформирована из сообщений оператора. Не заменяет утверждённую форму." Final text pending the legal check. | MUST |
| SPEC-008-R10 | Each export MUST be recorded in `waybill_export` with org, machine, range, `generated_at`, the included event ids and a content hash. The hash is computed over a canonical serialisation of rendered field values, not PDF bytes. | MUST |
| SPEC-008-R11 | The export MUST NOT write to `timeline_event` or any state. | MUST |
| SPEC-008-R12 | The template MUST be verified against the official form and the owner's photo before this spec is Done (OQ-008-1). | MUST |
| SPEC-008-R13 | An empty range SHOULD reply "нет записей за период" without generating a PDF. | SHOULD |
| SPEC-008-R14 | Generation SHOULD complete within a configured time (starting value 10 s) for a range of up to the maximum. | SHOULD |

## 4. Interfaces and data
Reads `effective_events`, `machine`, `shift_session`, `app_user`, `org`. Writes `waybill_export`. Output: Telegram document to the requesting owner.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-008-01 | Given a day with all four events, when `/waybill CAT-101 2026-10-05` runs, then a PDF is returned with the companion header and no equivalence claim. | R01, R02, R09 | integration, manual |
| AC-008-02 | Given a 3-day range with events on 2 days, then one document has three blocks, one marked "не зафиксировано" for missing readings. | R03, R06 | integration |
| AC-008-03 | Given the PDF, then each filled value has an appendix entry with a source message timestamp, and a query by `source_conversation_id` returns the message. | R05 | integration |
| AC-008-04 | Given a shift without a `fuel_log`, then the fuel field prints "не зафиксировано", not zero. | R06, R07 | integration |
| AC-008-05 | Given a corrected fuel value, then the PDF shows the corrected value and a `waybill_export` row lists the effective event ids. | R08, R10 | integration |
| AC-008-06 | Given any export, then `timeline_event` row count is unchanged. | R11 | integration |
| AC-008-07 | Given a 30-day range, then a clear "максимум N дней" message is returned. | R03 | unit |
| AC-008-08 | Given the same inputs exported twice, then the content hash is identical. | R10 | unit |
| AC-008-09 | Given each event type, then it fills only the fields in the mapping table of R04 (mapping test). | R04 | unit |
| AC-008-10 | Given the template, then a field-by-field review against the official form and the owner's photo is signed off. | R12 | manual |
| AC-008-11 | Given an empty range, then the reply is "нет записей за период" and no PDF is generated. | R13 | integration |
| AC-008-12 | Given a maximum-length range on the target VPS, then generation completes within the configured time. | R14 | performance |

## 6. Open questions
- **OQ-008-1:** Obtain the official ЭСМ-2 form and re-read the owner's photo to map every field. Owner: Varun. Blocks Done.
- **OQ-008-2:** Legal acceptability in place of the paper form. Ask the pilot owner's accountant and a Russian lawyer. Decides final R09 wording.
- **OQ-008-3:** Which PDF library. Implementation choice, no decision needed here.
- **OQ-008-4:** Whether the owner wants the PDF also available outside Telegram (email or REST). Ask in the pilot.

## 7. Traceability
Scope §1, §3 Pillar 1, §13, §14, §15.2. ADR-0008, ADR-0009. Invariants 1 and 9. Related specs: SPEC-004, SPEC-009, SPEC-011.
