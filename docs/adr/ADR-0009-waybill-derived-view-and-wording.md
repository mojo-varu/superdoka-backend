---
id: ADR-0009
title: The waybill is a read-only derived view, worded as a companion until legality is verified
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§1", "§3 Pillar 1", "§13", "§15.2"]
specs: [SPEC-008, SPEC-013]
---

# ADR-0009: The waybill is a read-only derived view, worded as a companion until legality is verified

## Context
The ЭСМ-2 is the wedge. Whether a chat-generated record is legally acceptable in place of the official form is **unverified**. The pitch diagram has no output box for the waybill.

## Decision
1. The waybill export is a **read-only derived view** of `timeline_event`. It never writes to the timeline.
2. Each export is recorded in `waybill_export` with the included event ids and a content hash.
3. All product copy, bot messages and PDF headers say "digital waybill record" or "waybill companion". They never claim to replace or be legally equivalent to the official form until the legal check passes.
4. The PDF template is mapped against the **official form** (Типовая межотраслевая форма № ЭСМ-2), not against the list in the scope document.

## Consequences
**Good:** the wedge ships without a legal claim it cannot back.
**Costs and risks:** a positioning cost; "companion" is a weaker sell than "alternative". Resolve through the accountant and lawyer check.

## Alternatives considered
| Option | Why not |
|---|---|
| Claim equivalence now | Unverified, potentially misleading to customers. |
| Skip the PDF, show only the digest | Loses the wedge. |

## Revisit when
Legal acceptability is confirmed (open decision in §13), then update wording and this ADR.

## Enforced by
SPEC-008-R01, R09 to R11. Test AC-008-01, AC-008-05.
