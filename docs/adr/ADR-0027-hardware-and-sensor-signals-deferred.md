---
id: ADR-0027
title: Hardware and sensor signals — deferred
status: Proposed
date: 2026-10-24
deciders: Varun
scope_refs: ["§10"]
specs: []
---

# ADR-0027: Hardware and sensor signals — deferred

## Context
The accelerator-pitch architecture and `PROJECT_BRIEF.md`'s "beacon" framing both
gesture at a future where machine telemetry (fuel sensors, hour meters, GPS/
telematics) could feed the state graph directly instead of relying entirely on
operator self-report. Nothing in `SHIPPABLE_SCOPE.md`'s v1 scope (pillars 1–5,
§10 "explicitly not in v1") includes any hardware integration, and no device
integration code exists anywhere in this repo.

## Decision (pending — recorded as deferred, not rejected)
We will not build any hardware or sensor integration in v1 or in this Telegram bot
work. The operator remains the sole signal source for fuel, hours, and issue
reports, exactly as `PROJECT_BRIEF.md`'s design principle 6 states ("Operator is the
beacon — closest to the asset, first to notice what sensors miss"). This decision is
deferred, not closed: a future device-reading integration should plug into the
**state layer**, specifically as an additional event producer writing to
`timeline_event` through the same append-only, schema-validated path operator
messages use (SPEC-004-R01, R03) — not as a parallel, less-governed write path, and
not by mutating `MachineState`/canonical state directly (forbidden regardless of
source by `ARCHITECTURE_VERBALIZED.md` rule 2).

## Consequences
**Good:** keeps v1 scope honest — no sensor-integration work is implied or half-built
anywhere in the Telegram bot deliverables; a future integration has a clear, already-
specified landing point (the timeline event path) rather than needing its own
state-mutation design from scratch.
**Costs and risks:** none for v1. The only risk is scope creep if a future
contributor (or Claude Code session) assumes a sensor feed exists or starts
designing around one without reopening this ADR first.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| Design a sensor-ingestion API now, even if unused | No evidence any pilot owner has sensor hardware wired up; speculative design with no data to validate it against. |
| Treat operator self-report as temporary/inferior to future sensor data | Contradicts the product's own design principle — operator reports are the primary signal by design (noticing smells, sounds, resistance sensors cannot measure), not a stopgap for missing hardware. |

## Revisit when
A pilot or prospective customer has existing telemetry hardware (fuel sensors, hour
meters, GPS/telematics) and asks for it to feed the system, or the owner decides to
evaluate hardware partnerships explicitly — either is a product decision that
reopens this ADR, not something Claude Code should infer from code alone.

## Enforced by
No spec requirement — this ADR exists to record a scope boundary, not a built
behaviour. `ARCHITECTURE_VERBALIZED.md` rule 2 (no state mutation without a
validated TimelineEvent) already enforces the only constraint that matters if this
is ever revisited.
