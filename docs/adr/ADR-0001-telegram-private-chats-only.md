---
id: ADR-0001
title: Telegram first, private 1:1 chats only, thin channel adapter
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 2", "§10", "§13"]
specs: [SPEC-001, SPEC-013]
---

# ADR-0001: Telegram first, private 1:1 chats only, thin channel adapter

## Context
MAX has registration friction, so it cannot be the first channel. Telegram has a stable Bot API and supports voice notes. Group chats mix several actors in one thread and break the mapping from a message to one operator and one shift session. Whether the pilot operators can reach Telegram on their phones and networks is **not yet verified** (SHIPPABLE_SCOPE §13).

## Decision
We will integrate Telegram through the Bot API using a webhook, and handle **private 1:1 chats only**. Updates from group or channel chats are ignored with one polite "write to me privately" reply. All channel specifics live behind a thin `ChannelAdapter` interface so MAX can be added later without touching the pipeline.

## Consequences
**Good:** a chat id maps to exactly one `app_user`, so session binding is unambiguous. The pipeline stays channel-neutral.
**Costs and risks:** operators who coordinate in groups today must also write privately. If Telegram is unreachable for the pilot operators, this ADR fails and the channel strategy must be reopened.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| MAX first | Registration challenges. Deferred, not rejected. |
| Group chats | Cannot attribute messages to one operator and session. |
| WhatsApp | Not discussed in scope; no evidence it helps and it adds a business-API dependency. |
| REST only | No operator-facing surface. REST stays as a sandbox and test interface. |

## Revisit when
The reachability test on pilot phones fails, the pilot owner says operators will not use private chats, or MAX registration becomes workable.

## Enforced by
SPEC-001-R01, R02, R03. Test AC-001-01, AC-001-02.
