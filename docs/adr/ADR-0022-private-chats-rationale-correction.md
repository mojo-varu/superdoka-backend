---
id: ADR-0022
title: Private chats only — corrected rationale (supplements ADR-0001)
status: Accepted
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 2", "§10", "§13"]
specs: [SPEC-001, SPEC-015]
---

# ADR-0022: Private chats only — corrected rationale (supplements ADR-0001)

## Context
ADR-0001 (Accepted, not edited by this ADR) already decided: Telegram first, private
1:1 chats only, thin channel adapter. Its stated rationale was "group chats mix
several actors in one thread and break the mapping from a message to one operator and
one shift session." That framing is **too strong**: Telegram does give a sender id on
every group message, so attributing a message to an operator is technically possible
in a group. The decision to serve private chats only was correct; the reason given
for it was not the real reason.

## Decision
We reaffirm ADR-0001's decision unchanged: private 1:1 chats only for the first
validation; group, supergroup and channel updates are ignored with one polite reply
(SPEC-001-R02). We correct the rationale. The real reasons are:
1. **Group privacy mode.** By default a Telegram bot in a group only receives
   messages that mention it or reply to it, not the full stream — so "the bot sees
   every operator message" is not actually true in groups without disabling privacy
   mode, which has its own trust and noise costs.
2. **Replies visible to everyone.** A confirmation, a clarifying question, or a
   correction prompt meant for one operator is visible to the whole group, which
   breaks the 1:1 "digital foreman" feel the product depends on (SHIPPABLE_SCOPE
   §3 Pillar 3) and leaks one operator's numbers to colleagues.
3. **Off-topic chatter dilutes the signal.** Groups mix shift-relevant messages with
   unrelated conversation, which is exactly the kind of noise the system's "never
   appears smarter than its evidence" and closed-domain principles are designed to
   avoid absorbing.

Sender-id attribution was never the blocking problem; privacy mode visibility,
reply leakage, and signal dilution are.

## Consequences
**Good:** the decision does not change, so SPEC-001-R02 and everything built on it
stands. Future readers get the real reasoning instead of a claim ("cannot attribute
a sender") that a Telegram API check would quickly disprove and cast doubt on the
rest of the document.
**Costs and risks:** none beyond what ADR-0001 already accepted — operators who
coordinate in groups today must still also write privately.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Edit ADR-0001 directly | Forbidden — ADR-0001 is Accepted. A superseding/supplementary ADR is the correct mechanism. |
| Enable group privacy mode off and allow groups with per-operator reply routing (e.g. DM fallback for sensitive replies) | Adds real complexity (routing confirmations out of the group to a DM) for a problem the private-chat-only decision already avoids outright. Revisit only if the trigger below fires. |

## Revisit when
Operators explicitly refuse to use private chats and prefer to coordinate only in an
existing group (stated preference during the pilot, not a guess) — the trigger named
by the human when approving this decision.

## Enforced by
SPEC-001-R02. Test AC-001-01.
