---
id: ADR-0015
title: Speech-to-text provider (open)
status: Proposed
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§13"]
specs: [SPEC-002, SPEC-013]
---

# ADR-0015: Speech-to-text provider (open)

## Context
Voice is a v1 requirement. Number accuracy on noisy cabin audio, latency, cost and **data location** (152-ФЗ, unverified) all matter. Candidates from the scope document: local `faster-whisper` on CPU, Yandex SpeechKit, SberDevices SaluteSpeech. Current terms of the hosted services must be verified.

## Decision (pending)
Decision is deferred to phase 3 and made on measurement, not preference:
1. Record real cabin audio from the pilot (with consent).
2. Score each candidate on **number accuracy** (the primary metric), latency, cost and data location.
3. Record the outcome here and flip status to Accepted.

**Already decided:** the pipeline depends on an `SttProvider` interface only (ADR-0007), so the choice stays swappable and the first provider is not a lock-in.

## Consequences
**Good:** no premature commitment; sample collection doubles as golden-set material.
**Costs and risks:** SPEC-002 can be built against a stub and one provider adapter, but cannot be declared Done until this ADR is Accepted.

## Alternatives considered
See candidates above. Foreign STT APIs are excluded unless a documented decision allows them (invariant 7).

## Revisit when
Not applicable until accepted. After acceptance: if pilot confirm-reject rate is poor.

## Enforced by
SPEC-002-R02, R03, R11. Blocks SPEC-002 "Done".
