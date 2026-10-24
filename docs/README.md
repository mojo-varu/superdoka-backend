# SuperDoka v1 — Specs and ADRs

This folder turns `SHIPPABLE_SCOPE.md` into build-ready documents for spec-driven development. Nothing here adds product scope. If something looks like new scope, it is a bug in these docs: raise it.

## What each document type is for

| Type | Answers | Changes how |
|---|---|---|
| `SHIPPABLE_SCOPE.md` | What ships in v1 and why | Product decision by Varun |
| **ADR** (`adr/`) | Why we build it this way | Never edited once Accepted. Superseded by a new ADR. |
| **SPEC** (`specs/`) | What the system must do, testably | Edited through a reviewed change before the code changes |
| `ARCHITECTURE_VERBALIZED.md` | What Claude Code must never do (ten rules) | Binds everything below |

**Precedence when documents disagree:** `ARCHITECTURE_VERBALIZED.md` rules, then Accepted ADRs, then SPECs for behaviour detail, then `SHIPPABLE_SCOPE.md` for what ships. A conflict is a defect: stop and report it, do not pick silently.

## Conventions

- **Requirement IDs:** `SPEC-NNN-Rnn`. Words MUST, SHOULD, MAY carry their usual meaning.
- **Scenario IDs:** `AC-NNN-nn`. Each names the requirements it proves and a test level (unit, integration, golden, e2e, manual, performance).
- **Open questions:** `OQ-NNN-n`. They live in the spec they block.
- **Starting values** (for example "30 minutes", "K = 2") are configuration defaults, not decisions. Make them configurable.
- **Statuses.** Spec: Draft, Ready, Blocked, Done. ADR: Proposed, Accepted, Superseded.
- **Done** means every MUST requirement has a passing scenario and no blocking open question remains.

## Workflow for one change

1. Pick requirement IDs from a Ready spec. That list is the ticket.
2. Write the failing tests from the matching `AC-` scenarios.
3. Implement until the tests pass. Reference IDs in commit messages, for example `SPEC-004-R05: revoke UPDATE/DELETE on timeline_event`.
4. If the spec is wrong or silent, change the spec first in its own commit. If the change alters a decision, write or supersede an ADR first.
5. Run `python3 docs/tools/check_docs.py --write`. It fails on broken references and regenerates `TRACEABILITY.md`.
6. Update the spec status when the definition of Done is met.

## Build order (SHIPPABLE_SCOPE §11 → specs)

| Phase | Specs and parts |
|---|---|
| 0 Foundation | SPEC-011, SPEC-004 (core), SPEC-005 (`PolicyDecision`), SPEC-010 (H1, H2), SPEC-012 |
| 1 Telegram text end to end | SPEC-001, SPEC-003 (R01 to R09), SPEC-005 (rules), SPEC-006 (templates only) |
| 2 Outputs | SPEC-008, SPEC-009 |
| 2b Decision-model spike | SPEC-003 (R10 to R14), ADR-0012 |
| 3 Voice | SPEC-002 (blocked on ADR-0015, ADR-0017) |
| 4 Proactive rules | SPEC-007 |
| 5 Harness | SPEC-010 (H3 to H5), SPEC-006 (validator, kill switch) |
| 6 LLM verbaliser | SPEC-006 (go-live, blocked on ADR-0016 and R14 gate) |
| 7 Pilot | SPEC-013 |

## Specs

| ID | Title | Status | Phase |
|---|---|---|---|
| [SPEC-001](specs/SPEC-001-channel-onboarding-idempotency.md) | Telegram channel, onboarding, idempotent inbound, corrections entry point | Ready | 1 |
| [SPEC-002](specs/SPEC-002-voice-input.md) | Voice input with transcript echo-confirm | Blocked | 3 |
| [SPEC-003](specs/SPEC-003-understanding-pipeline.md) | Understanding pipeline and decision-model spike | Ready | 1 |
| [SPEC-004](specs/SPEC-004-state-graph-and-timeline.md) | State graph, timeline events, corrections, derived signals | Ready | 0 |
| [SPEC-005](specs/SPEC-005-policy-engine.md) | Policy engine and the three day-one behaviours | Ready | 0 |
| [SPEC-006](specs/SPEC-006-supervisor-execution.md) | Supervisor execution, templates, bounded LLM verbaliser, validator, kill switch | Ready | 6 |
| [SPEC-007](specs/SPEC-007-proactive-watchdog.md) | Proactive watchdog, five fixed rules, suppression and quiet hours | Ready | 4 |
| [SPEC-008](specs/SPEC-008-digital-esm2-waybill.md) | Digital ЭСМ-2 waybill export | Ready | 2 |
| [SPEC-009](specs/SPEC-009-fleet-intelligence-and-traceability.md) | Daily digest, owner commands, trace, findings log | Ready | 2 |
| [SPEC-010](specs/SPEC-010-harness.md) | Minimal foundational harness (log, version stamps, replay, golden set, metrics) | Ready | 0 |
| [SPEC-011](specs/SPEC-011-data-model.md) | v1 data model and migrations | Ready | 0 |
| [SPEC-012](specs/SPEC-012-infrastructure-and-operations.md) | Infrastructure and operations baseline | Ready | 0 |
| [SPEC-013](specs/SPEC-013-pilot-readiness.md) | Pilot readiness, consent, and success measurement | Ready | 7 |

## ADRs

| ID | Decision | Status |
|---|---|---|
| [ADR-0001](adr/ADR-0001-telegram-private-chats-only.md) | Telegram first, private 1:1 chats only, thin channel adapter | Accepted |
| [ADR-0002](adr/ADR-0002-tiered-decision-stack.md) | Tiered decision stack, deterministic core decides | Accepted |
| [ADR-0003](adr/ADR-0003-bounded-llm-role.md) | LLM restricted to a verbalisation allowlist behind validator, timeout and kill switch | Accepted |
| [ADR-0004](adr/ADR-0004-conversationlog-vs-timelineevent.md) | Two records, ConversationLog for every turn, TimelineEvent for confirmed facts only | Accepted |
| [ADR-0005](adr/ADR-0005-append-only-and-corrections.md) | Immutability enforced in Postgres, corrections are new events | Accepted |
| [ADR-0006](adr/ADR-0006-idempotent-inbound.md) | Idempotent inbound handling keyed on channel and update id | Accepted |
| [ADR-0007](adr/ADR-0007-voice-echo-confirm.md) | Voice transcripts are untrusted input, numeric entities need operator confirmation | Accepted |
| [ADR-0008](adr/ADR-0008-provenance-on-every-output-value.md) | Every printed value carries provenance or says "не зафиксировано" | Accepted |
| [ADR-0009](adr/ADR-0009-waybill-derived-view-and-wording.md) | The waybill is a read-only derived view, worded as a companion until legality is verified | Accepted |
| [ADR-0010](adr/ADR-0010-fixed-proactive-rules.md) | Proactive behaviour limited to five fixed rules with suppression and quiet hours | Accepted |
| [ADR-0011](adr/ADR-0011-replay-harness-readonly-manual-feedback.md) | Replay harness is read-only and the KPI and memory feedback loop is human-reviewed | Accepted |
| [ADR-0012](adr/ADR-0012-decision-model-adoption-gate.md) | Decision-model adoption is gated by a Russian eval set, Jev is not adopted | Accepted |
| [ADR-0013](adr/ADR-0013-tenancy-and-invite-binding.md) | Multi-tenancy by org_id on every table, operators bound through invite deep links | Accepted |
| [ADR-0014](adr/ADR-0014-deployment-baseline.md) | Single VPS with Docker Compose and Postgres, no new infrastructure in v1 | Accepted |
| [ADR-0015](adr/ADR-0015-stt-provider.md) | Speech-to-text provider (open) | Proposed |
| [ADR-0016](adr/ADR-0016-llm-hosting-and-data-residency.md) | LLM hosting and personal-data residency (open) | Proposed |
| [ADR-0017](adr/ADR-0017-voice-audio-retention.md) | Voice audio retention (open) | Proposed |

Open (Proposed) ADRs are decisions the builder still owes, not defaults. See each ADR's "Decision (pending)" section.

## Generated and supporting files

- [`TRACEABILITY.md`](TRACEABILITY.md): scope section to spec map, requirement to scenario map. Generated.
- [`CLAUDE_MD_SNIPPET.md`](CLAUDE_MD_SNIPPET.md): paste into the repo's `CLAUDE.md` so Claude Code follows this process.
- [`templates/`](templates): SPEC and ADR templates.
- [`tools/check_docs.py`](tools/check_docs.py): consistency checker.

## Items that need verification before the specs are final

These are in the specs as open questions. The most important: Russian support in GLiNER2.5-Decide, legal acceptability of a chat-generated ЭСМ-2, 152-ФЗ data location, Telegram reachability for the pilot operators, the STT provider, LLM hosting, audio retention, and reconciling event types and intents with the existing `logbuk-backend` code (OQ-003-1, OQ-004-1, OQ-005-3, OQ-011-1).
