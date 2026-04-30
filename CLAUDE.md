# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Logbuk is a **Virtual Fleet Manager (VFM)** backend — a FastAPI service that processes operator messages (via Telegram/MAX/REST) for heavy equipment fleets. Operators send natural-language messages ("залил 50 литров", "начинаю смену на БЗ-99") which flow through an NLP pipeline (NER → LLM extraction) and are recorded as structured fleet events.

## Commands

### Development (local, SQLite fallback — no Docker required)
```bash
poetry install
poetry run uvicorn app.main:app --reload
```

### Full stack with Docker (Postgres + Redis + Ollama LLM)
```bash
docker-compose up --build
```
The `api` container runs `alembic upgrade head` automatically before starting uvicorn.

### Database migrations
```bash
poetry run alembic upgrade head          # apply all migrations
poetry run alembic revision --autogenerate -m "description"  # generate new migration
```

### Testing
```bash
poetry run pytest                        # all tests
poetry run pytest tests/test_e2e_message_flow.py  # single file
poetry run pytest -k "test_critical"     # single test by name
```

### Linting / formatting
```bash
poetry run black app/ tests/
poetry run isort app/ tests/
poetry run flake8 app/ tests/
poetry run mypy app/
```

## Architecture

### Three-Pillar Design
Every inbound message flows through three pillars, coordinated via the `FleetUpdate` domain object (`app/schemas/fleet_update.py`):

1. **Interface** — HTTP adapter creates a `FleetUpdate` via `FleetUpdate.from_raw()`. Endpoints live in `app/api/v1/endpoints/`. The VFM endpoint (`/api/v1/vfm/update`) is the primary ingest path.

2. **Intelligence** — `app/core/context_llm.py` runs the extraction pipeline: injection guard → context-aware prompt builder → LLM call (Anthropic/YandexGPT/Ollama, configured via env vars) → JSON response validation → confidence calibration. Returns an `ExtractionResult` with `intent`, `entities`, and `confidence`.

3. **Agency** — `app/services/event_processor.py` orchestrates the full write pipeline: operator resolution → intelligence → session/machine resolution → DB writes (atomic: `TimelineEvent` + specific log table + `MachineState` UPSERT) → rule evaluation → reply assembly.

### Key Data Models (`app/db/models.py`)
- **`ActiveSession`** — one row per operator on shift; answers "who is on what machine right now" in O(1). Redis mirrors this for sub-millisecond reads.
- **`MachineState`** — live digital-twin snapshot per machine; updated on every event via UPSERT. Avoids aggregating logs for real-time queries.
- **`TimelineEvent`** — immutable append-only ledger of every operator action. All specific log tables (`FuelLog`, `HoursLog`, `IssueReport`) link back to their `TimelineEvent` via `timeline_event_id`. Corrections are new `CORRECTION` events pointing to the original — originals are never modified.
- **`GroupMessage`** — inbound message queue with retry/failure tracking (`retry_count`, `last_error`, `failed_at`).

### Background Processing
`app/services/watcher.py` runs two asyncio loops on startup:
- **Queue drain** (every 5 min): picks up `PENDING` `GroupMessage` rows and runs them through `EventProcessor`. Retries up to 3 times before marking `FAILED`.
- **Nudge loop** (every 5 min): fires check-in nudge rules for operators overdue on shift.

### Rule Engine
`app/services/rule_engine.py` loads `app/rules/fleet_rules.yaml` at startup. Rules are data — edit the YAML to change thresholds without redeployment. Rules use dot-notation field access (`session.fuel_ratio`) and fire all matching rules (not first-match). The `RuleEngine.reload()` method supports hot-reload via an admin endpoint.

### LLM Configuration
Controlled entirely via environment variables:
- `LLM_PROVIDER`: `anthropic` (default) | `yandex` | `ollama`
- `LLM_MODEL`: model name (default: `claude-haiku-4-5-20251001`)
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`

In `docker-compose.yml` the default is Ollama (`qwen2.5:7b-instruct`) running on the host machine at `host.docker.internal:11434`.

### Confidence Routing
After extraction, `ConfidenceRoute` determines action:
- `≥ 0.85` → `AUTO`: write immediately
- `0.60–0.85` → `CONFIRM`: write + show inline keyboard asking operator to confirm
- `< 0.60` → `LLM`: re-ask operator for clarification

Owner admin intents (`ADD_MACHINE`, `ASSIGN_MACHINE`) always route `AUTO` regardless of confidence.

### Database
- Production: PostgreSQL via `asyncpg` (async SQLAlchemy 2.0)
- Local dev fallback: SQLite via `aiosqlite` (no Docker needed)
- Schema managed by Alembic; migration files in `alembic/versions/`
- `DATABASE_URL` env var switches between them automatically
