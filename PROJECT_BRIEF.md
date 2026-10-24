# Logbuk / VFM — Project Brief
## Context for new conversation thread

---

## What we are building

**VFM (Virtual Fleet Manager)** is a context-aware digital supervisor for heavy equipment
fleets in Russian construction and mining. It operates inside Telegram and MAX — the
messengers operators already use — and turns unstructured field updates into structured
fleet intelligence for owners, without changing how operators communicate.

**The product is not a chatbot or assistant.** It is a closed-domain agentic system:
- Fixed assets (machines), fixed actors (operators, owners), finite workflows (shift, fuel,
  hours, issue, handover)
- Deterministic policy engine routes every interaction — LLM only adapts language
- Machine state graph is the source of truth — replayable, immutable, evidence-grounded
- System never appears smarter than its evidence

**Two relationships, one supervisor:**
- Operator → supervisor: sends free-text updates, gets confirmations or one clarifying
  question. No new app. No training. No behaviour change.
- Owner → supervisor: receives fleet intelligence — fuel anomalies, shift summaries, open
  issues, escalations — without chasing operators.

---

## Platform name

**ДОЗОР (Dozor)** — the platform. Means "watch/patrol" in Russian. Industrial vocabulary,
works in both scripts.
**VFM** — Virtual Fleet Manager, the first module within ДОЗОР.
**Logbuk** — the construction site module (future).

---

## Architecture overview

Five layers, two cross-cutting systems:

```
Interfaces          Telegram · MAX · REST API
Understanding       Signal normalisation → Intent+entity extraction → Confidence scoring
State layer         Canonical machine state · Derived signals
                    Event timeline (REPLAYABLE · append-only · immutable)
                    Session context · Workflow rules · Escalation thresholds
Policy layer        Policy engine · Rules · Suppression logic
                    → Policy object: CONFIRM · CLARIFY · ALERT · NUDGE · ESCALATE
Supervisor          Template engine (T1/T2/T8 — deterministic)
                    LLM verbaliser (T3/T5/T6/T7 — language only)
                    Response validator (ensures no new facts)
Response/Output     Reply to channels · Machine log · Fleet intelligence · Owner alert

Cross-cutting:
  Replay harness    Event timeline → Evaluation metrics → KPI feedback → Policy + memory
  Proactive watchdog Reads state · Suppression · Feeds response layer
```

**Design principle:** State graph holds truth · Supervisor routes within bounds ·
LLM adapts language · Harness measures outcomes

---

## Tech stack

```
Backend:      FastAPI (Python)
Database:     PostgreSQL 15 (Docker)
Cache:        Redis 7 (Docker)
ML models:    DistilBERT fine-tuned → ONNX (intent classifier + NER extractor)
LLM:          qwen2.5:3b-instruct via Ollama (local)
Channels:     Telegram (live) · MAX (in progress) · REST sandbox
Frontend:     logbuk-neo.html (static, served by FastAPI)
Deployment:   Docker Compose (colima on Mac)
```

---

## Current state — what is working

### Backend pipeline
- `POST /api/v1/vfm/update` — full pipeline running end to end
- Intent classifier: 90%+ accuracy on Russian operator messages (shift_start 0.997,
  fuel_log 1.00, hours_log 0.999, issue_report 0.999)
- NER extractor: working, minor truncation issues on some entities
- T1/T2 templates: confirmed working (no LLM call)
- T4 off-topic: routing correctly but reply quality inconsistent (LLM not fine-tuned)
- Machine state graph: tracking fuel, hours, issues across shifts
- Anomaly detection: fuel rate vs rolling baseline, fires correctly

### Endpoints available
```
POST /api/v1/vfm/update
GET  /api/v1/vfm/fleet/intelligence       ← new, returns real data
GET  /api/v1/vfm/machine/{reg}/state      ← new, per-machine detail
GET  /api/v1/vfm/sandbox/operators
GET  /api/v1/operator/{id}/timeline
GET  /api/v1/operator/{id}/machines
GET  /api/v1/logs/events
GET  /api/v1/owner/fleet/summary
GET  /api/v1/owner/fleet/{machine_id}
```

### Known issues
- `fuel_today` and `hours_today` in fleet/intelligence accumulate across all historical
  runs — needs `WHERE created_at >= today` date filter
- T4 LLM replies inconsistent — model not fine-tuned, prompt-only mitigation in place
- `fuel_baseline` returns null — anomaly percentage comparison not yet computed
- Simulate_fleet.py start phrases need machine reg number included

### Sandbox UI (logbuk-neo.html)
- Operator console: UI exists, message send works, replies not correctly wired
- Fleet intelligence screen: exists but shows static/placeholder data
- Machine logs tab: not wired to real endpoint
- Needs: all three screens wired to real backend data

---

## Current state — what is in progress

- Telegram integration: in progress
- MAX integration: in progress
- LLM fine-tuning: training data generated (2000 synthetic examples),
  Qwen2.5-1.5B-Instruct target model, Kaggle GPU needed for training run
- Sandbox fleet simulation: simulate_fleet.py ready, needs start phrase fix

---

## Key files

```
app/core/intelligence_router.py    # 4-stage pipeline entry point
app/core/task_router.py            # T1-T8 routing + templates
app/core/context_graph.py          # machine state graph + serialise_for_prompt()
app/core/context_llm.py            # LLM context builder
app/core/persona.py                # VFM supervisor persona (lru_cache)
app/core/VFM_PERSONA.md            # supervisor character + agenda definition
app/core/model_loader.py           # ONNX model loader
app/services/session_service.py    # shift session management
app/services/rule_engine.py        # business rules
app/services/watcher.py            # proactive watchdog (designed, not yet running)
app/api/v1/endpoints/vfm.py        # API endpoints
static/logbuk-neo.html             # sandbox UI

train/vfm_state_graph_runner_v3.py # standalone simulation (7 scenarios, template-only)
train/simulate_fleet.py            # 14-day fleet simulation via curl
train/probe_agency_llm.py          # direct LLM probe bypassing pipeline
train/BACKEND_CHANGES.md           # Claude Code handover for V1 backend fixes
training/generate_agency_data.py   # synthetic training data generator
training/train_agency_model.py     # LoRA fine-tuning script
```

---

## What comes next — in order

### Step 1: Sandbox integration (immediate)
Wire logbuk-neo.html to real backend data.
Full spec: `SANDBOX_INTEGRATION.md`

### Step 2: Backend V1 hardening
Four targeted changes to intelligence_router and task_router.
Full spec: `BACKEND_EVOLUTION.md` → Priority 1 section

### Step 3: Fleet simulation
Run simulate_fleet.py after start phrase fix to seed 14 days of data.
Verify fleet intelligence dashboard shows real accumulated data.

### Step 4: LLM fine-tuning (when Kaggle GPU available)
Target: Qwen/Qwen2.5-1.5B-Instruct
Training data: training/data/agency/ (2000 synthetic examples)
Script: training/train_agency_model.py
After training: export to GGUF, load into Ollama as vfm-agency:1.7b

### Step 5: Backend architecture evolution (V1.5)
Formalise policy object, add schema validation, response validator,
separate canonical state from event history.
Full spec: `BACKEND_EVOLUTION.md` → Priority 2 section

### Step 6: Replay harness (V2)
After 4-6 weeks of real operator data accumulates.
Full spec: `BACKEND_EVOLUTION.md` → Priority 3 section

---

## Design principles — non-negotiable

1. Graph = truth — canonical state mutated only by validated events
2. Policy = logic — what happens next is always deterministic
3. LLM = language — adapts tone, never decides operational outcomes
4. Never appears smarter than its evidence — response validator enforces this
5. Replayable — event timeline is append-only, any state reconstructable
6. Operator is the beacon — closest to the asset, first to notice what sensors miss
7. Every conversational turn must justify itself operationally — if a question does
   not improve fuel confidence, downtime prediction, or maintenance clarity,
   it should not be asked
