---
id: ADR-0017
title: Voice audio retention (open)
status: Proposed
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§12", "§13"]
specs: [SPEC-002, SPEC-013]
---

# ADR-0017: Voice audio retention (open)

## Context
Traceability argues for keeping audio. Privacy argues for deleting it. The STT test and the golden set need real samples, but only with consent. Retention interacts with 152-ФЗ.

## Decision (pending)
Decide with the pilot owner before phase 3 starts. Minimum already fixed: `conversation_log` stores Telegram `file_unique_id`, STT metadata and the transcript, regardless of whether audio is kept.

Options to choose between:
1. Discard audio immediately after transcription.
2. Keep audio for a fixed number of days, then purge.
3. Keep audio during the pilot for STT scoring (consent required), purge afterwards.

## Consequences
Whichever is chosen must be implemented as a purge job with a test, and stated in the operator-facing consent text.

## Alternatives considered
See options.

## Revisit when
Not applicable until accepted.

## Enforced by
SPEC-002-R09, R10.
