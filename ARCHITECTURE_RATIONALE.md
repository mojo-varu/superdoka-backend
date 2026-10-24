# VFM Architecture Design Rationale
## Why each component exists and what it is responsible for

This document captures the design philosophy behind each architectural component.
It exists to prevent future decisions from accidentally undermining the principles
that make the system reliable, auditable, and operationally trustworthy.

---

## Core design principle

**The system never appears smarter than its evidence.**

Every output the system produces must be traceable to a confirmed operator input.
The system does not infer, fabricate, or extrapolate beyond what has been explicitly
reported. This is not a limitation — it is the property that makes the system
trustworthy in an industrial context where incorrect data causes real financial harm.

---

## The four-layer mental model

```
State layer    = truth about the machine and workflow
Policy layer   = what should happen next
Supervisor     = how the system behaves, prioritises, and communicates
LLM            = language and tone adaptation only
```

These four layers must never bleed into each other. The LLM must not make policy
decisions. The policy layer must not depend on LLM output. The state layer must
not be mutated by anything other than validated, confirmed operator events.

---

## Component rationale

---

### Interfaces (Telegram · MAX · REST)

**What it is:**
The ingress and egress layer. Receives operator messages from external channels
and delivers VFM replies back through the same channels.

**Why it exists:**
Operators communicate through messengers they already use. VFM does not introduce
a new app or a new behaviour. The interface layer is deliberately thin — it normalises
channel-specific message formats into a canonical internal representation and routes
replies back through the correct channel.

**Design decision:**
Bidirectional. The same channel that receives operator updates delivers VFM replies,
proactive watchdog nudges, and owner alerts. This means the operator never needs
to switch context — everything happens in their existing workflow.

**What it is NOT responsible for:**
Understanding, structuring, or storing messages. It passes signals in and replies out.

---

### Signal Normalisation

**What it is:**
The first processing step inside the harness boundary. Cleans, validates, and
canonicalises incoming messages before any intelligence processing occurs.

**Why it exists:**
Operator messages arrive in inconsistent formats — typos, mixed Russian/English,
Cyrillic homoglyphs, emoji, voice-to-text artefacts. A message that looks like
"залли 150лт соляры" needs to be understood as a fuel log before it reaches
the intent classifier. Normalisation handles this without involving the ML models.

**Design decision:**
Safety check runs here. Messages that fail injection guard rules are rejected
before they touch any downstream component. This keeps the intelligence pipeline
clean and prevents prompt injection or adversarial inputs from reaching the LLM.

**What it is NOT responsible for:**
Understanding intent or extracting data. It only makes the signal processable.

---

### Intent Classification

**What it is:**
A fine-tuned DistilBERT model exported to ONNX that classifies operator messages
into one of 14 intent classes: shift_start, shift_end, fuel_log, hours_log,
issue_report, status_update, off_topic, unknown, and others.

**Why it exists:**
The system needs to know what the operator is trying to say before it can decide
what to do. Intent classification is the first step in understanding — it routes
the message into the correct handling path without involving the LLM.

**Design decision:**
Deterministic once trained. The classifier produces a confidence score alongside
the intent. High confidence (≥0.90) routes to automatic processing. Low confidence
(<0.70) routes to clarification. This threshold-based routing is what makes
T1 confirmations fast and template-driven while T2 clarifications are targeted.

**Why not use the LLM for intent classification:**
Speed, reliability, and cost. A fine-tuned classifier runs in milliseconds with
no external API call. It does not hallucinate. It does not drift with temperature.
For a closed domain with finite intents, a classifier is strictly better than
an LLM for this task.

**What it is NOT responsible for:**
Extracting the actual data values (fuel volume, hours, issue description).
That is the NER extractor's job.

---

### Entity Extraction (NER)

**What it is:**
A fine-tuned DistilBERT NER model exported to ONNX that extracts structured
data points from operator messages: fuel volume, hours worked, issue descriptions,
machine identifiers, repair costs.

**Why it exists:**
Knowing the intent is "fuel_log" is not enough. The system needs the actual
number — 150 litres — to update the machine state. The NER model extracts these
entities from free-text Russian operator language without requiring structured input.

**Design decision:**
Schema validation happens after NER extraction, before state mutation. An extracted
fuel volume of 5000 litres is implausible and gets rejected. An extracted hours value
of 50 hours in a single update is implausible and triggers clarification instead of
automatic logging. The schema contract between extraction and state mutation is what
prevents bad data from corrupting the machine state graph.

**What it is NOT responsible for:**
Deciding what to do with extracted entities. That belongs to the policy layer.

---

### Schema Validation (Confidence Router)

**What it is:**
The gate between the understanding layer and the state layer. Validates that
extracted entities are plausible, complete, and within acceptable ranges before
any state mutation occurs.

**Why it exists:**
The state layer is the source of truth. Anything that enters it must be trustworthy.
Schema validation is the architectural enforcement of "never appears smarter than
its evidence" — it rejects implausible extractions rather than logging them silently.

**Design decision:**
Produces three outcomes: accept (high confidence, complete data → log immediately),
clarify (low confidence or missing required field → ask operator one question),
escalate (critical signal detected → alert owner immediately).

**What it is NOT responsible for:**
Generating the clarification question. That belongs to the supervisor layer.

---

### Machine State Graph

**What it is:**
The source of truth for everything the system knows about each machine. A structured,
per-machine representation of current state, historical events, derived signals,
and session context.

**Why it exists:**
This is the moat. Without persistent, structured, per-machine memory, VFM is just
a message router. The state graph is what allows the system to know that a machine's
fuel rate this shift is 40% above its 7-day baseline, that the hydraulics fault was
reported three shifts in a row, and that the operator on duty today has a history
of terse updates that need active clarification.

**Design decision — four internal components:**

1. **Canonical machine state** — authoritative current status per machine.
   Only mutated by validated, confirmed events. Never inferred. Never estimated.
   This is what the owner dashboard reads as ground truth.

2. **Event timeline** — append-only, immutable log of every confirmed operational
   event. This is the replayability layer. Any machine state at any point in time
   can be reconstructed from the event timeline. The replay harness reads from here.
   Nothing is ever deleted or modified in this table.

3. **Derived signals** — computed from the event timeline. Fuel anomalies,
   recurring issue patterns, machine silence detection. These are observations,
   not ground truth. They can be recomputed at any time from the raw events.
   The distinction between canonical state (truth) and derived signals (observations)
   is critical — derived signals inform policy decisions but never override
   canonical state.

4. **Session context** — short-lived, per-conversation context. What the operator
   said last, what intent was last classified, what the pending clarification is.
   This is what allows VFM to understand "ещё 50" (50 more) as a fuel addition
   after a previous fuel log rather than an ambiguous number. Session context
   expires at shift end.

**Why replayability matters:**
In industrial operations, the ability to reconstruct what happened and when is
not just useful — it is sometimes legally required. The immutable event timeline
means the system can always answer "what did the operator report and when" with
a traceable answer tied to the original message.

**What it is NOT responsible for:**
Deciding what to do with the state. That belongs to the policy layer.

---

### Policy Engine

**What it is:**
The deterministic rules layer that decides what should happen next based on
machine state, extracted intent, confidence scores, and business rules.
Produces an explicit policy object: CONFIRM · CLARIFY · ALERT · NUDGE · ESCALATE.

**Why it exists:**
The supervisor needs bounded, auditable decision-making. By separating the
"what should happen" (policy) from the "how to say it" (supervisor/LLM),
the system remains predictable and debuggable. Every routing decision can be
logged, replayed, and explained.

**Design decision — explicit policy object:**
The policy engine does not produce a reply. It produces a typed decision:
what action should be taken and why. The supervisor layer executes that decision.
This separation means you can change how VFM phrases a confirmation (supervisor)
without changing when it decides to confirm vs clarify (policy).

**Suppression logic lives here:**
If the watchdog has already alerted on a fuel anomaly for machine X, the policy
engine suppresses re-alerting until the state changes. This prevents the system
from becoming noise for the owner — a property that is architecturally enforced,
not dependent on the LLM behaving well.

**What it is NOT responsible for:**
Generating language. The policy engine never produces text — only decisions.

---

### Supervisor (Bounded Action Selection)

**What it is:**
The layer that executes the policy decision. Routes to the correct execution path:
template engine for deterministic responses, LLM verbaliser for contextual language,
escalation path for critical events.

**Why it exists:**
Think of the supervisor as a digital operations lead. It understands the domain,
knows the machine and the operator, and decides how to respond to the current
situation within the bounds the policy engine has set. It has a persona and an
agenda — but it cannot invent policy or override canonical state.

**Design decision — agenda-driven:**
The supervisor has four priorities in order:
1. Safety — critical events always escalate immediately
2. Completeness — missing data is always clarified before logging
3. Anomaly detection — unusual patterns surface to the owner
4. Owner intelligence — shift summaries and accountability reports

These priorities are hardcoded into the supervisor's decision logic. They do not
change based on LLM output or operator preference.

**What it is NOT responsible for:**
Generating natural language. The supervisor decides what to say. The LLM verbaliser
decides how to phrase it — but only for T3/T5/T6/T7 where templating is insufficient.

---

### Template Engine

**What it is:**
A deterministic reply generator for T1 (confirmation), T2 (field clarification),
T4 (off-topic redirect), and T8 (critical alert). Produces Russian-language replies
by filling structured templates with data from the confirmed event and machine state.

**Why it exists:**
For the majority of operator interactions — fuel logs, hours logs, shift start/end,
off-topic messages — the correct reply is fully determined by the extracted data.
There is no need for language model creativity. "Записал: 150л топлива ✓" is
the correct reply to a fuel log. A template produces this in under 1ms with zero
risk of hallucination.

**Design decision — LLM excluded from T1/T2/T4/T8:**
This is the most important architectural decision in the system. T1 confirmations
are the most frequent interaction type (~70% of all operator messages). Making them
deterministic means the system is fast, predictable, and trustworthy for the vast
majority of interactions. The LLM is reserved for cases where language variability
genuinely adds value.

**What templates cannot do:**
Handle genuinely ambiguous messages, surface anomaly context in natural language,
or produce shift summaries. Those cases route to the LLM verbaliser.

---

### LLM Verbaliser

**What it is:**
A small language model (qwen2.5:3b-instruct, running locally via Ollama) that
produces natural language replies for T3, T5, T6, and T7 interactions.

**Why it exists:**
Some interactions require language that templates cannot produce. When an operator
sends an ambiguous message after a fuel log, the system needs to ask a contextually
appropriate question — not a generic form. When a fuel anomaly is detected, the
system needs to ask about symptoms in a way that references the specific numbers
from the machine state. The LLM handles the language layer for these cases.

**Design decision — strictly subordinate:**
The LLM receives a structured payload (machine state, policy decision, task
instruction) and produces one sentence. It does not make operational decisions.
It does not access raw operator history. It does not choose what to ask — the
policy engine has already decided that. It only adapts the phrasing.

The prompt explicitly prohibits fabrication: "НИКОГДА не изобретай данные."
The response validator enforces this architecturally after generation.

**Why local model (Ollama) not cloud API:**
Operational data is sensitive. Fuel consumption, machine locations, issue reports,
and operator identities should not leave the operator's infrastructure. Running
the LLM locally on the same server as the application keeps all data on-premises.

**What it is NOT responsible for:**
Any decision about what to say. Only how to say what has already been decided.

---

### Response Validator

**What it is:**
A post-generation check that validates LLM output before it is delivered to the
operator. Checks that the reply does not contain numbers, named entities, or claims
not present in the structured input payload.

**Why it exists:**
The LLM verbaliser can still hallucinate even with strict prompting. The response
validator is the architectural enforcement of "never appears smarter than its
evidence." If the reply contains a fuel rate not derived from the operator's
message or the machine state, the validator rejects it and falls back to a template.

**Design decision — fail safe to template:**
When validation fails, the system does not retry the LLM or produce a degraded
response. It falls back to the template engine. A slightly generic template reply
is always better than a hallucinated specific claim.

**What it is NOT responsible for:**
Generating alternative replies. It only validates or rejects.

---

### TimelineEvent (Machine Log)

**What it is:**
The persistent, append-only log of every confirmed operational event tied to
a specific machine, shift, and operator. The source of truth that the machine
state graph is computed from and the owner dashboard reads.

**Why it exists:**
Traceability. Every data point that appears in the owner dashboard must be
traceable to an original operator message with a timestamp and an operator identity.
The TimelineEvent table is that audit trail.

**Design decision — operational events only:**
TimelineEvent stores confirmed operational data: fuel_log, hours_log, issue_report,
shift_start, shift_end, repair_event. It does not store conversational noise —
off-topic messages, failed clarifications, or system messages.

**The gap — ConversationLog:**
A T4 off-topic message ("сегодня холодно") and its VFM reply ("Понял. Что по
А771МР77 — всё нормально?") are a conversational exchange, not an operational event.
They should not appear in the machine log but they must be preserved for:
- Session context (VFM needs conversation history for contextual understanding)
- Operator accountability (every message should be traceable regardless of intent)
- Replay harness (training signal requires both input message and output reply)

A separate `ConversationLog` table should be introduced in V1.5 to handle this.
Until then, the current implementation uses TimelineEvent for both — the dashboard
filters on intent to show only operational events to the owner, and non-operational
entries are stored but not surfaced.

**What it is NOT responsible for:**
Conversational context. That belongs to session state and the future ConversationLog.

---

### Proactive Watchdog

**What it is:**
A time-triggered background process that reads machine state independently of
the inbound message loop. Initiates outbound messages when state conditions
warrant — machine silence, persistent anomalies, unresolved issues.

**Why it exists:**
A supervisor does not only respond. It initiates. If a machine has not sent an
update in 90 minutes during active shift hours, a real supervisor would check in.
If fuel consumption has been anomalous for three consecutive shifts, a real
supervisor would flag it to the owner without waiting to be asked.

**Design decision — reads state, writes to response layer:**
The watchdog reads from the machine state graph and derived signals. It does not
write directly to the operator — it routes through the same response layer as
the supervisor. This means watchdog-initiated messages go through the same
validation and delivery path as supervisor replies.

**Suppression is mandatory:**
Without suppression, the watchdog fires on the same condition every cycle.
A suppression table ensures each signal type fires once per machine per condition
window. The window resets only when the underlying state changes — anomaly resolves,
machine reports in, issue is closed.

**What it is NOT responsible for:**
Understanding operator replies to its nudges. Those re-enter the pipeline through
the normal inbound message flow.

---

### Replay Harness

**What it is:**
A cross-cutting execution environment that observes every interaction — input signal
and output reply — measures outcome quality, and feeds improvement signals back
into the state graph and policy layer.

**Why it exists:**
The system is designed to improve over time through operational experience, not
through synthetic fine-tuning alone. The replay harness is what makes the system
adaptive within its bounded domain. It measures whether clarifications actually
resolved ambiguity, whether escalations were genuinely critical, whether operator
correction rate is increasing or decreasing.

**Design decision — four KPI buckets:**
1. Outcome KPIs: first-pass resolution rate, escalation precision
2. Reliability KPIs: template fallback rate, LLM latency
3. Risk KPIs: hallucinated fact rate, duplicate alert rate
4. Learning KPIs: operator correction rate, clarification success rate

**The most important rule:**
If hallucinated_fact_rate exceeds threshold, disable the LLM verbaliser and force
template-only mode automatically. This is the system protecting its own trustworthiness
without human intervention.

**Current status:**
The harness is designed but not yet implemented. The event timeline exists and
is the correct data source. Implementation is scheduled for V2 after 4-6 weeks
of real operator data has accumulated — synthetic data is insufficient to calibrate
meaningful KPI thresholds.

**What it is NOT responsible for:**
Running the pipeline. It observes and measures. It does not execute.

---

### Session Service

**What it is:**
Manages the lifecycle of an operator's active shift session. Creates a session on
shift_start, tracks the current machine, accumulates per-shift metrics, and closes
the session on shift_end.

**Why it exists:**
Context requires continuity. When an operator sends "ещё 50" (50 more), the system
needs to know that the previous message in this session was a fuel log of 150 litres
to interpret the bare number as 50 additional litres. Without session state, every
message is interpreted in isolation and contextual understanding becomes impossible.

**Design decision — session is per-operator-per-shift:**
A session opens when an operator sends a shift_start message that includes a machine
identifier. It closes on shift_end. If an operator works across multiple machines
in a day, each machine gets its own session. Session state is short-lived and does
not persist beyond the shift — historical context comes from the event timeline,
not from session state.

**The machine binding requirement:**
A session cannot open without a machine identifier. This is why shift start messages
must include the machine reg number: "начинаю смену на А771МР77". Without machine
binding, fuel logs and hours logs cannot be attributed to the correct asset.

---

## What belongs where — quick reference

| Question | Responsible component |
|---|---|
| What did the operator say? | Signal normalisation |
| What did they mean? | Intent classifier |
| What data did they report? | NER extractor |
| Is the data plausible? | Schema validator |
| What is the current machine state? | Machine state graph — canonical state |
| What patterns have emerged? | Machine state graph — derived signals |
| What happened historically? | Machine state graph — event timeline |
| What should happen next? | Policy engine |
| How should it be communicated? | Supervisor + template engine or LLM verbaliser |
| Did the reply introduce new facts? | Response validator |
| Was the operational event recorded? | TimelineEvent |
| Was the conversation recorded? | ConversationLog (V1.5) |
| Did the supervisor initiate correctly? | Proactive watchdog |
| Is the system improving? | Replay harness |
| What shift context exists? | Session service |

---

## Decisions that must not be reversed

1. **LLM excluded from T1/T2/T4/T8** — templates only for the majority of interactions
2. **Event timeline is append-only** — no updates, no deletes, ever
3. **Schema validation before state mutation** — bad data never reaches canonical state
4. **Response validator on all LLM output** — hallucinated facts never reach operators
5. **Suppression on watchdog** — the system never becomes noise for the owner
6. **Machine binding required for session** — no fuel or hours logged without machine identity
7. **LLM runs locally** — operational data never leaves the system boundary
