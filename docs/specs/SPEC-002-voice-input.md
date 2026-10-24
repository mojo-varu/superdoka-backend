---
id: SPEC-002
title: Voice input with transcript echo-confirm
status: Blocked
phase: 3
pillar: 2
scope_refs: ["§3 Pillar 2", "§12", "§13", "§14 inv. 2"]
adrs: [ADR-0007, ADR-0015, ADR-0017]
depends_on: [SPEC-001, SPEC-003]
---

# SPEC-002: Voice input with transcript echo-confirm

**Blocked until ADR-0015 (STT provider) and ADR-0017 (audio retention) are Accepted.** The stub and adapter work can start earlier.

## 1. Purpose
An operator sends a voice note "залил сто пятьдесят литров". The system transcribes it, shows the transcript back with ✅ / ✏️, and only after the operator confirms does a numeric fact enter the record.

## 2. Scope and non-goals
**In:** voice download, conversion, transcription, echo-confirm, correction by re-sending, metadata storage, retention purge.
**Out:** speaker identification, languages other than Russian, audio playback to the owner, choosing the provider (ADR-0015).

## 3. Requirements

| ID | Requirement | Priority |
|---|---|---|
| SPEC-002-R01 | The system MUST accept Telegram voice messages in private chats. Other media (photo, video, document) MUST receive one polite "не умею пока" reply and no state change. | MUST |
| SPEC-002-R02 | Transcription MUST go through an `SttProvider` interface: `transcribe(audio, language="ru")` returns `Transcript(text, provider, model, latency_ms, confidence?, raw_meta)`. | MUST |
| SPEC-002-R03 | There MUST be a stub provider for tests and at least one real adapter selected by configuration. | MUST |
| SPEC-002-R04 | Audio MUST be downloaded and converted to the format the provider needs (typically OGG/Opus to mono WAV). A maximum duration applies (starting value 60 s). Over the limit the bot asks the operator to send a shorter note. | MUST |
| SPEC-002-R05 | The transcript MUST enter the same Understanding pipeline as text, with `source=voice`. | MUST |
| SPEC-002-R06 | When a voice message yields any numeric entity (fuel, hours), the bot MUST echo the transcript with inline ✅ / ✏️ buttons before any event is committed. No event is written before ✅. | MUST |
| SPEC-002-R07 | ✏️ MUST prompt the operator to send corrected text or a new voice note. The new message is processed as a fresh turn linked to the rejected echo in `conversation_log`. | MUST |
| SPEC-002-R08 | An unanswered echo MUST expire (starting value 30 minutes) with no event written, and the expiry MUST be logged. Missing data is then handled by the close-out rule (SPEC-007 Rule R2). | MUST |
| SPEC-002-R09 | `conversation_log` MUST store the Telegram `file_unique_id`, STT provider and model, latency, transcript and the confirm outcome (`confirmed`, `edited`, `expired`). | MUST |
| SPEC-002-R10 | Audio files MUST be handled per the accepted retention policy in ADR-0017, implemented as a purge job with a test. | MUST |
| SPEC-002-R11 | This spec is Done only when ADR-0015 is Accepted and the candidate providers have been scored on real cabin samples for number accuracy, latency, cost and data location. | MUST |
| SPEC-002-R12 | A voice message without numeric entities (for example an issue description) MAY be processed without the confirm step, but the reply SHOULD quote the recognised text so errors are visible. | SHOULD |
| SPEC-002-R13 | An STT failure or timeout MUST yield a request to resend or type, and no event. | MUST |
| SPEC-002-R14 | The voice confirm-reject rate MUST be exposed as a harness metric (SPEC-010-R12). | MUST |

## 4. Interfaces and data
`SttProvider`, `Transcript`, inline callback payloads for ✅ and ✏️ (include the `conversation_log` id of the echo). Storage in `conversation_log` (SPEC-011).

## 5. Acceptance scenarios

| ID | Scenario | Proves | Level |
|---|---|---|---|
| AC-002-01 | Given a photo, when sent, then one polite refusal and no state change. | R01 | integration |
| AC-002-02 | Given a voice note transcribed as "залил сто пятьдесят литров", when processed, then the bot echoes the transcript with ✅ / ✏️ and no `timeline_event` exists yet. After ✅ one `fuel_log` of 150 exists and a reply is sent. | R05, R06 | integration |
| AC-002-03 | Given the echo, when the operator taps ✏️ and sends "сто пять", then a new turn is processed, linked to the rejected echo, and a confirm is requested again. | R07 | integration |
| AC-002-04 | Given an echo with no answer for the expiry period, then no event exists and the log shows `expired`. | R08 | integration |
| AC-002-05 | Given a 5-minute voice note, then the bot asks for a shorter note. | R04 | integration |
| AC-002-06 | Given the provider times out, then the operator is asked to resend and no event is written. | R13 | integration |
| AC-002-07 | Given the retention policy "N days", when the purge job runs, then audio older than N days is gone and the transcript and metadata remain. | R10 | integration |
| AC-002-08 | Given the real-cabin sample set, then a scored comparison table exists in ADR-0015. | R11 | manual |
| AC-002-09 | Given the stub provider is configured, then the pipeline runs through `SttProvider`. Swapping to a real adapter by configuration needs no pipeline change. | R02, R03 | unit |
| AC-002-10 | Given a processed voice note, then the log row holds `file_unique_id`, provider, model, latency, transcript and confirm outcome. | R09 | integration |
| AC-002-11 | Given a voice issue description with no numbers, then no echo is required and the reply quotes the recognised text. | R12 | integration |
| AC-002-12 | Given a day of logs with known voice outcomes, then the metrics command prints the confirm-reject rate equal to the hand count. | R14 | unit |

## 6. Open questions
- **OQ-002-1:** STT provider. See ADR-0015. Blocks Done.
- **OQ-002-2:** Retention policy. See ADR-0017. Blocks the purge job.
- **OQ-002-3:** Size of the cabin sample set needed for a defensible comparison (suggest at least 100 numeric utterances; confirm). Owner: Varun.
- **OQ-002-4:** Do operators actually send voice? Observe in the pilot; if the confirm tap pushes operators back to text, revisit ADR-0007.

## 7. Traceability
Scope §3 Pillar 2, §12, §13, invariant 2. ADR-0007, ADR-0015, ADR-0017. Related specs: SPEC-001, SPEC-003, SPEC-010.
