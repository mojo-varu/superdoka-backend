# VFM Architecture — Verbalised
## A prose description of the finalised architecture diagram
## Reference document for Claude Code — do not deviate from this design

This document describes the finalised VFM closed-domain agentic architecture
diagram in full prose. Every component, every data flow, and every boundary
is described here. Claude Code must treat this as the authoritative design
specification. Any code change that contradicts a flow described here requires
explicit approval before implementation.

---

## The overarching principle

The footer of the diagram states the system's identity in three phrases:

**Closed-domain bounded agency · replayable memory · evidence-grounded responses**

These are not aspirational — they are architectural constraints.

- **Closed-domain bounded agency** means the system operates within fixed assets,
  fixed actors, fixed workflows, and finite intents. It never expands its own domain.
- **Replayable memory** means every state can be reconstructed from the event
  timeline. Nothing is ever deleted or overwritten in the source-of-truth layer.
- **Evidence-grounded responses** means every output is traceable to a confirmed
  operator input. The system never invents, infers beyond evidence, or produces
  claims that cannot be sourced.

The italic annotation inside the diagram — *never appears smarter than its evidence*
— is the single most important design constraint. It applies to every component
that produces output.

---

## The machine operator — external actor

The machine operator sits above the system boundary, labelled as
**"external actor · the beacon"**.

The operator is outside the system. The system does not control the operator,
does not modify the operator's behaviour, and does not require the operator to
learn anything new. The operator communicates through channels they already use.

The operator is called "the beacon" because they are the closest human to the
physical asset — the first to notice what sensors cannot measure: unusual sounds,
smells, vibrations, fuel behaviour, mechanical resistance. The system's entire
value depends on capturing and structuring what the beacon reports.

The bidirectional arrow between the operator and the interfaces layer represents
two distinct flows: inbound messages from operator to system, and outbound replies
from system to operator. The same channel carries both directions.

---

## Interfaces — Telegram · MAX · REST

The interfaces layer is a full-width band spanning the width of the diagram,
sitting between the external operator and the operational harness boundary.

It carries: **Telegram · MAX · REST — receive updates · deliver replies**

**What it does:** Receives operator messages from external messenger channels
and REST API calls. Delivers VFM replies back through the same channel.
Normalises channel-specific message formats into a canonical internal
representation before passing them into the harness.

**What it does not do:** It does not understand, classify, store, or act on
messages. It is a thin bidirectional transport layer.

**The return path:** A dashed arc on the far left of the diagram shows replies
flowing from the response output layer back up to the interfaces. This return
path goes around the outside of the harness boundary — replies exit the harness,
travel back to the interfaces, and are delivered to the operator through their
channel. The arc goes left rather than right to avoid overlapping the replay harness.

---

## Operational harness boundary

The amber dashed rectangle enclosing all layers from understanding through
response output is the **operational harness boundary**.

Everything inside this boundary is observed, logged, and measured. The harness
knows what signal came in, what the system understood, what it decided, what it
said, and what the outcome was. Nothing inside the boundary escapes measurement.

The harness boundary is not a component — it is a scope definition. It says:
"the replay harness has visibility into everything within this boundary."

The machine operator and the interfaces layer sit outside the harness boundary.
The operator's raw messages enter the harness at the signal normaliser. The
system's replies exit the harness at the reply-to-channels output.

---

## Understanding layer — three sequential components

The understanding layer sits immediately inside the harness boundary, below
the interfaces. It contains three components connected left to right by arrows.

### Signal normaliser
**"safety · format · language"**

The first component every message touches. Handles language detection, format
cleanup, Cyrillic normalisation, injection guard safety screening, and creation
of a canonical internal message object. A message that fails safety screening
is rejected here and never reaches the ML models.

The signal normaliser is grey — it is infrastructure, not intelligence.

### Intent + entity extraction
**"schema-validated slots"**

The purple component that performs the core language understanding work.
Uses the fine-tuned DistilBERT intent classifier (ONNX) to identify what
the operator is reporting, and the fine-tuned NER extractor (ONNX) to extract
the specific data values — fuel volume, hours, issue description, machine
identifier. The "schema-validated slots" label means extracted entities are
validated against expected types and ranges before passing downstream.

This component is purple — it performs language understanding, which is the
controlled, bounded use of ML in this architecture.

### Confidence scoring
**"accept · clarify · route"**

The second purple component. Takes the classified intent and extracted entities
and produces a routing decision based on confidence: high confidence routes to
automatic acceptance and state update; low confidence routes to clarification;
critical signals route to immediate escalation. This is the gate between
understanding and action.

The three understanding components connect left to right with arrows.
A single arrow then flows down from the understanding layer into the state layer.

---

## Domain · state layer — the machine state graph

The state layer is the most visually dominant element in the diagram — a wide
coral-coloured container labelled:

**"Machine state graph — source of truth"**

It spans the full width of the internal content area and is the tallest layer.
The visual dominance is intentional — this is the architectural moat.

The state layer contains four internal components, each with a dotted border
to indicate they are sub-components of the same container:

### Canonical state
**"status per asset"**

Top-left internal component. Stores the current authoritative status of each
machine: WORKING, IDLE, BREAKDOWN, SHIFT_ACTIVE. This is ground truth.
It is only mutated by validated, confirmed events from the understanding layer.
It is never inferred, estimated, or set by the LLM.

### Derived signals
**"anomaly · trend · recurrence"**

Top-right internal component. Computed observations derived from the event
timeline: fuel consumption anomalies against rolling baseline, recurring issue
patterns, machine silence detection. These are observations, not ground truth.
They can be recomputed at any time from raw events. They inform policy decisions
but never override canonical state.

### Event timeline — replayable operational memory
**"append-only · immutable · provenance per signal"**

The full-width middle component, styled with a coral dashed border to make it
the most prominent element inside the state layer. This is the append-only,
immutable log of every confirmed operational event. Every entry carries full
provenance: which operator sent it, which machine it belongs to, what the
original raw text was, what was extracted, and when.

**Replayable** means any machine state at any point in time can be reconstructed
by replaying the event timeline from the beginning. Nothing is ever deleted.
Nothing is ever overwritten. This is the source from which the replay harness
reads events.

### Session context · workflow rules · escalation thresholds
The bottom full-width component inside the state layer. Contains three things:
short-lived per-conversation session context (expires at shift end), the
deterministic workflow rules that govern valid state transitions, and the
escalation thresholds that determine when the policy engine escalates vs confirms.

A single arrow flows down from the state layer into the policy layer.

---

## Policy layer — rules engine

A coral-coloured full-width block labelled:

**"Policy engine · rules · suppression logic"**

Below it, in bold: **CONFIRM · CLARIFY · ALERT · NUDGE · ESCALATE**

These five words are the complete action vocabulary of the system. The policy
engine produces exactly one of these five outputs per interaction. No other
actions exist. The supervisor cannot invent a new action type.

**What the policy engine does:** reads the confidence routing decision from the
understanding layer, cross-references it with the current machine state,
applies business rules and escalation thresholds, applies suppression logic
to prevent repeated alerts on the same condition, and produces a typed policy
decision.

**Suppression logic** is explicitly named here because it is architecturally
important. Without suppression, anomaly alerts and watchdog nudges would fire
on every processing cycle for the same condition. Suppression ensures each
signal fires once and does not re-fire until the underlying state changes.

**What the policy engine does not do:** It does not generate language. It does
not call the LLM. It produces a decision object, not a reply.

A single arrow flows down from the policy layer into the supervisor execution layer.

---

## Supervisor · execution layer — three parallel components

Labelled **"Supervisor · execution"**, this layer contains three components
side by side. A single arrow from the policy layer fans into all three — the
policy decision determines which path activates.

### Template engine
**"deterministic replies"**

Grey — infrastructure. Handles T1 (confirmation), T2 (field clarification),
T4 (off-topic redirect), and T8 (critical alert). For the vast majority of
interactions, the correct reply is fully determined by the extracted data and
machine state. A template produces this reply in under 1ms with zero risk of
hallucination. No LLM is involved.

**This is the most important architectural decision in the system.** T1 is
approximately 70% of all operator interactions. Making it deterministic means
the system is fast, predictable, and trustworthy for the majority of turns.

### LLM verbaliser
**"language only · bounded"**

Purple — language component. Handles T3 (contextual clarification), T5
(anomaly enquiry), T6 (proactive suggestion), and T7 (shift summary).
For these four task types, natural language variability adds value that
templates cannot provide. The LLM receives a structured payload — machine
state, policy decision, task instruction — and produces one or two sentences.

**Critically:** The LLM verbaliser is purple, the same colour as the
understanding layer components. This is intentional — purple marks all
language processing components. The LLM is in the same category as intent
classification: a controlled, bounded use of language model capability,
not the decision-making brain of the system.

**The LLM does not:** make policy decisions, access raw conversation history,
choose what to ask, determine severity, or produce numerical claims not
present in its input payload.

### Response validator
**"ensures no new facts"**

Grey — infrastructure. Validates every LLM-generated reply before delivery.
Checks that the reply does not contain numbers, named entities, or claims
not sourced from the structured input payload. If validation fails, the
system falls back to the template engine silently.

The italic annotation immediately below these three components:
*never appears smarter than its evidence*
— is the architectural contract that the response validator enforces.

A single arrow flows down from the supervisor execution layer into the
response output layer.

---

## Response · output layer — four parallel components

The output layer sits at the bottom of the harness boundary, with four
components side by side:

### Reply to channels
**"TG · MAX · REST"**

The operator-facing output. Delivers the VFM reply back through the same
channel the operator used. Connects via the left-side return arc back up
to the interfaces layer. This return arc goes outside the harness boundary —
the reply exits the system and is delivered externally.

### Fleet intelligence
**"computed owner view"**

The owner dashboard data source. A computed view over canonical state,
derived signals, and the event timeline. Surfaces fuel consumption trends,
shift summaries, open issue counts, anomaly flags, and machine activity
status. This is what the owner sees — not raw messages, not operator chat.

### Owner alert
**"anomaly · escalation"**

Direct owner notification for time-sensitive conditions: fuel anomalies,
critical issues, machine silence exceeding thresholds. Separate from fleet
intelligence because alerts require immediate attention rather than
dashboard review.

### Machine log
**"traceable · immutable"**

The persistent, structured record of every confirmed operational event,
positioned rightmost adjacent to the harness boundary because it is the
primary data source the replay harness reads. Every machine log entry
carries full provenance: operator, machine, raw message, extracted data,
timestamp. This is what feeds the harness.

---

## Proactive watchdog — left vertical cross-cutting system

A grey dashed vertical rectangle on the left side of the diagram, spanning
from the understanding layer height down to the response output layer.

**What it does:** Runs independently of the inbound message loop. Reads from
the machine state graph at a fixed interval to check for conditions that
warrant proactive outreach: machine silence during active shift hours,
anomalies persisting across multiple shifts, unresolved issues exceeding
age thresholds.

**Two connections:**

1. **Arrow pointing right into the state layer** (y=340 in the diagram) —
   the watchdog reads state. This arrow points rightward into the system,
   meaning the watchdog is consuming state, not producing it.

2. **Arrow bending down and right into the reply-to-channels output** —
   the watchdog's outbound nudges go through the same reply layer as
   supervisor responses. The watchdog does not deliver messages directly
   to channels — it routes through the response layer, ensuring all outbound
   messages pass through the same output path.

**The watchdog does not:** write to canonical state, call the LLM directly,
or bypass the policy engine's suppression logic. Watchdog-initiated nudges
respect the same suppression rules as policy-triggered alerts.

---

## Replay harness — right vertical cross-cutting system

An amber dashed vertical rectangle on the right side of the diagram, outside
the operational harness boundary, spanning the same vertical range as the
state layer through the response output layer.

The amber colour matches the harness boundary — both are amber because they
represent the same concern: observability, measurement, and learning.

**What it does:** Observes every interaction from two data sources, measures
outcome quality, and feeds improvement signals back into the state and policy layers.

**Four connections:**

1. **"events" arrow pointing right from event timeline into the harness** —
   the harness reads every confirmed operational event from the immutable
   event timeline. This is the input signal side.

2. **"log" arrow from machine log, bending up into the harness** —
   the harness reads machine log entries to see what the system produced
   as output for each interaction. Together with the event timeline, the
   harness has both sides of every confirmed turn.

3. **"mem" arrow pointing left from harness into the state layer** —
   the harness writes memory updates back into the state layer. Compressed
   operational patterns, promoted memory rules, operator style preferences.
   These are derived summaries, not canonical state mutations.

4. **"KPI" arrow pointing left from harness into the policy layer** —
   the harness writes KPI feedback back into the policy engine. Escalation
   threshold adjustments, suppression window changes, fallback rate triggers.
   If hallucination rate exceeds threshold, the harness triggers template-only
   mode in the policy layer.

**The learning loop:** Event timeline + Machine log → Harness → Evaluation
metrics → Memory updates (state layer) + KPI threshold updates (policy layer).
This is the closed loop that makes the system improve through operational
experience without human intervention.

**Current status:** The harness is an architectural design. The data sources
(event timeline, machine log) exist. The harness processing layer is not yet
implemented. It is scheduled for V2 after sufficient real operator data
accumulates to calibrate meaningful thresholds.

---

## Data flow summary — one complete interaction

```
1. Operator sends "Залил 150 литров" via MAX

2. Interfaces receives the message, normalises channel format

3. Signal normaliser runs safety check, language normalisation

4. Intent + entity extraction classifies as fuel_log (0.999),
   extracts fuel_liters=150.0

5. Confidence scoring: 0.999 ≥ 0.90 threshold → accept

6. Machine state graph: updates canonical state (fuel_today += 150),
   writes TimelineEvent (fuel_log · 150L · Ivan · А771МР77 · timestamp)

7. Policy engine: high confidence + complete data → CONFIRM

8. Supervisor: CONFIRM routes to template engine

9. Template engine: "Записал: 150л топлива ✓"

10. Response validator: no LLM was called, no validation needed

11. Reply to channels: delivers "Записал: 150л топлива ✓" to Ivan via MAX

12. Machine log: entry written (fuel_log · 150L · traceable to original message)

13. Replay harness: reads event from timeline, reads log entry,
    records turn as confirmed · template · fuel_log · no correction

14. Fleet intelligence: updated fuel_today for А771МР77
```

---

## What Claude Code must never do

The following changes would violate the architecture and must not be made
without explicit approval and a documented rationale:

1. **Route T1/T2/T4/T8 through the LLM verbaliser** — these task types are
   always deterministic. Adding LLM to T1 confirmations destroys the system's
   speed, predictability, and hallucination resistance for the majority of turns.

2. **Mutate canonical state without a validated TimelineEvent** — canonical state
   is only ever updated as a consequence of a confirmed, schema-validated event
   being written to the event timeline. State mutations cannot be triggered directly.

3. **Delete or update TimelineEvent records** — the event timeline is append-only
   and immutable. Corrections are handled by creating a correction event, not by
   modifying existing records.

4. **Allow the LLM to produce a policy decision** — the LLM verbaliser receives
   a policy decision as input and produces language as output. It must never be
   asked to decide what action to take.

5. **Bypass the response validator for LLM output** — every LLM-generated reply
   must pass through the response validator before delivery. No exceptions.

6. **Remove suppression from the watchdog or alert paths** — without suppression,
   the system generates noise. Suppression is not optional.

7. **Allow session to open without machine binding** — a shift session cannot
   exist without a confirmed machine identifier. Fuel and hours logged without
   a machine cannot be attributed and must be rejected, not estimated.

8. **Move the LLM outside the operational harness boundary** — the LLM must be
   observable by the harness. If it runs outside the boundary, its outputs cannot
   be measured and the learning loop breaks.

9. **Merge ConversationLog and TimelineEvent into a single table** — these serve
   different purposes. TimelineEvent is the operational ledger the owner reads.
   ConversationLog is the complete interaction record the harness reads.
   Merging them would pollute the owner view with conversational noise.

10. **Add new action types beyond the five policy actions** — CONFIRM · CLARIFY ·
    ALERT · NUDGE · ESCALATE is the complete vocabulary. New behaviour must be
    expressed as a combination or refinement of these five, not as a new action.
