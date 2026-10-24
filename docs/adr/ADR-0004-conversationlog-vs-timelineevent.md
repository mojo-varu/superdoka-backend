---
id: ADR-0004
title: Two records, ConversationLog for every turn, TimelineEvent for confirmed facts only
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§6 H1", "§8", "§15.2"]
specs: [SPEC-004, SPEC-010, SPEC-011]
---

# ADR-0004: Two records, ConversationLog for every turn, TimelineEvent for confirmed facts only

## Context
An operator message may be off-topic, a question, a correction, a rejected voice transcript or a clarification reply. Treating every message as an operational event would pollute the state graph and the waybill. The harness and replay need every turn, including the ones that never became events. The pitch diagram draws only the timeline.

## Decision
We will keep two records.
- **ConversationLog (H1):** one row per inbound message and one per outbound reply, linked, including off-topic and rejected turns. Owned by the harness. Source of provenance.
- **TimelineEvent:** only confirmed operational events. Append-only. Each event carries `source_conversation_id` pointing back to the ConversationLog row.

A ConversationLog row optionally links forward to its `timeline_event_id`.

## Consequences
**Good:** the state graph holds facts, the log holds evidence. Replay uses the log, projections use the timeline.
**Costs and risks:** two writes per confirmed message, and the link must stay consistent. A write that creates an event must also set the link in the same transaction.

## Alternatives considered
| Option | Why not |
|---|---|
| One table for everything | Mixes evidence with facts; waybill and digest queries need filtering rules everywhere. |
| Log only inside the timeline | Loses off-topic and rejected turns, so replay and metrics are incomplete. |

## Revisit when
Never expected. Storage cost is trivial at pilot scale.

## Enforced by
SPEC-004-R01, R02, SPEC-010-R01, SPEC-011-R03, R04.
