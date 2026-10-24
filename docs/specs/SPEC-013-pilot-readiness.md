---
id: SPEC-013
title: Pilot readiness, consent, and success measurement
status: Ready
phase: 7
pillar: foundation
scope_refs: ["§12", "§13"]
adrs: [ADR-0001, ADR-0009, ADR-0015, ADR-0016, ADR-0017]
depends_on: [SPEC-001, SPEC-008, SPEC-009, SPEC-010]
---

# SPEC-013: Pilot readiness, consent, and success measurement

## 1. Purpose
Make pilot #1 (the fleet owner who described the shift process; two weeks; real operators and machines) measurable and safe to start, and capture the data the next iterations need.

## 2. Scope and non-goals
**In:** a start gate, consent, data collection, success measurement, pilot review.
**Out:** pricing decisions (an input to them), post-pilot candidates.

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-013-R01 | The pilot MUST NOT start until the **start gate** passes: the Telegram reachability test on the pilot operators' phones and networks is done and recorded (OQ-001-4); the legal wording check for the waybill has been requested and R09 copy of SPEC-008 is in its safe form; ADR-0017 is Accepted; ADR-0015 is Accepted if voice is in the pilot; ADR-0016 is Accepted if the LLM is live; the hosting and data-location note exists (SPEC-012-R10). | MUST |
| SPEC-013-R02 | Operators and the owner MUST see a short consent notice on first use covering message and voice storage and the use of anonymised messages for improving the product. The consent MUST be recorded per `app_user`. | MUST |
| SPEC-013-R03 | Real messages, voice samples, owner edits to the waybill template and anything that confused an operator MUST be collected into a pilot notes file, and eligible messages anonymised into the eval and golden sets (SPEC-003-R11, SPEC-010-R11). | MUST |
| SPEC-013-R04 | The pilot report MUST compute: the share of shifts with start, fuel, hours and end captured (target at least 80%); the operator correction rate trend over the two weeks; owner engagement with the digest, measured as any owner interaction (a tap on "Откуда?" or a command) within 24 hours of each digest, since Telegram gives no read receipts; findings logged that the owner marks as useful (target at least three). | MUST |
| SPEC-013-R05 | At the end of the pilot, the owner MUST be asked whether they would pay, and how much. The answer is recorded verbatim. | MUST |
| SPEC-013-R06 | A pilot review note MUST list which open decisions in SHIPPABLE_SCOPE §13 were closed and how, and which spec or ADR changes follow. | MUST |

## 4. Interfaces and data
Reads harness metrics (SPEC-010-R12), `finding`, `digest_log`. Writes a consent flag on `app_user` and a pilot notes file.

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-013-01 | Given each start-gate item, then a recorded result exists before the first real shift. | R01 | manual |
| AC-013-02 | Given a new user, when they first write, then consent is shown and recorded. | R02 | integration |
| AC-013-03 | Given two weeks of logs, when the pilot report command runs, then it prints the four measures. | R04 | integration |
| AC-013-04 | Given the pilot ends, then the owner's willingness-to-pay answer is stored. | R05 | manual |
| AC-013-05 | Given the pilot, then a pilot notes file exists and anonymised messages in the eval set carry a consent flag. | R03 | manual |
| AC-013-06 | Given the pilot ends, then a review note lists the closed open decisions and the resulting spec or ADR changes. | R06 | manual |

## 6. Open questions
- **OQ-013-1:** Wording of the consent notice. Draft in Russian for the pilot owner's review. Whether a lawyer should review it depends on the 152-ФЗ check.
- **OQ-013-2:** Whether the success targets stay as proposed. Adjust with the owner.

## 7. Traceability
Scope §12, §13. ADR-0001, ADR-0009, ADR-0015, ADR-0016, ADR-0017. Related specs: SPEC-001, SPEC-002, SPEC-008, SPEC-009, SPEC-010, SPEC-012.
