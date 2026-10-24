---
id: ADR-0007
title: Voice transcripts are untrusted input, numeric entities need operator confirmation
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§14 inv. 2", "§15.2"]
specs: [SPEC-002]
---

# ADR-0007: Voice transcripts are untrusted input, numeric entities need operator confirmation

## Context
Operators speak in noisy cabins. Speech-to-text errors on numbers ("сто пятьдесят" versus "сто пятнадцать") silently corrupt fuel and hours, which feed the waybill. Confirming is cheaper than silent corruption.

## Decision
A voice note is converted, transcribed, and then treated like any other message with `source=voice`, with one difference: **before any numeric entity (fuel, hours) from a voice message is committed, the bot echoes the transcript with inline ✅ / ✏️ buttons**. Only a ✅ tap (or an accepted edit) allows the event to be written. The transcript is a Signal normaliser concern, not a separate pipeline.

Which provider performs STT is a separate, open decision (ADR-0015). The pipeline depends only on an `SttProvider` interface.

## Consequences
**Good:** the worst voice failure becomes a visible wrong echo, not a wrong record.
**Costs and risks:** one extra tap per voice report, which touches the "no behaviour change" promise. Measure the confirm-reject rate (H5) and watch whether operators abandon voice.

## Alternatives considered
| Option | Why not |
|---|---|
| Confirm only when STT confidence is low | STT confidence is not a reliable predictor of number errors; revisit with pilot data. |
| Commit then allow correction | Wrong numbers would already be in state, digest or waybill. |

## Revisit when
Pilot data shows the confirm-reject rate is very low for a given provider; a confidence-gated confirm may then be proposed.

## Enforced by
SPEC-002-R05 to R08. Test AC-002-02, AC-002-03. Invariant 2.
