---
id: ADR-0010
title: Proactive behaviour limited to five fixed rules with suppression and quiet hours
status: Accepted
date: 2026-10-11
deciders: Varun
scope_refs: ["§3 Pillar 3", "§7", "§14 inv. 4, 10"]
specs: [SPEC-007, SPEC-005]
---

# ADR-0010: Proactive behaviour limited to five fixed rules with suppression and quiet hours

## Context
A sticky, proactive agent is the day-one impression, but unbounded proactivity becomes spam, and one 3 a.m. nudge ends adoption. Solo-builder scope also needs a ceiling.

## Decision
We will implement exactly five proactive rules, R1 to R5 (no shift start by expected time; shift closing with missing fuel or hours; open issue from previous shift; fuel rate anomaly versus baseline; daily digest). Adding a sixth requires an explicit decision and removing or deferring another. Every proactive message:
- is produced by the policy engine, not by the scheduler directly;
- passes the response validator and the normal reply path;
- honours the suppression table `(org, machine, rule, window_key)`;
- is blocked during quiet hours in the org timezone (starting value 21:00 to 06:00).

A rule re-arms only when the underlying state changes.

## Consequences
**Good:** predictable, testable, explainable.
**Costs and risks:** requests for more rules will arrive early. Treat each as a change to this ADR.

## Alternatives considered
| Option | Why not |
|---|---|
| Open-ended LLM-driven proactivity | Not auditable, not replayable. |
| No proactivity | Loses the "agent, not a dumb bot" differentiator. |

## Revisit when
Pilot findings show a missing rule with clear value. Update this ADR and SPEC-007 first.

## Enforced by
SPEC-007-R01 to R12. Test AC-007-01 to AC-007-07. Invariants 4 and 10.
