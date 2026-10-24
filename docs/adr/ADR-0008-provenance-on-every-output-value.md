---
id: ADR-0008
title: Every printed value carries provenance or says "не зафиксировано"
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 1", "§3 Pillar 4", "§14 inv. 1"]
specs: [SPEC-008, SPEC-009, SPEC-004]
---

# ADR-0008: Every printed value carries provenance or says "не зафиксировано"

## Context
"Never appears smarter than its evidence" must hold for documents, not only chat replies. A waybill that looks complete while parts were never captured misleads the owner and is a legal exposure.

## Decision
Every value on a waybill or digest must trace to a `conversation_log` id (through `timeline_event.source_conversation_id`). A value with no evidence is printed as **"не зафиксировано"**. Fields chat cannot legitimately fill (medical exam, mechanic sign-off, customer or foreman signature) always print that text. Derived numbers (rates, totals) are computed from traced inputs and list those inputs on drill-down.

## Consequences
**Good:** an owner can audit any number in two taps, which is also the ROI story.
**Costs and risks:** documents look emptier than the paper form in early shifts. That is intended, but pilot copy must explain it.

## Alternatives considered
| Option | Why not |
|---|---|
| Fill with defaults or last-known values | Fabricates evidence. |
| Hide empty fields | Looks complete when it is not. |

## Revisit when
One-tap foreman or customer confirmation exists (post-pilot candidate); those fields may then carry confirmation provenance.

## Enforced by
SPEC-008-R05 to R08, SPEC-009-R05, R06. Test AC-008-03, AC-009-03. Invariant 1.
