# VFM Sandbox — Live Demo

The real backend, running locally. Streamlit replaces MAX messenger as the input channel.

## Quick start

```bash
pip install -r requirements.txt

# Copy your NER model into place
cp -r /path/to/distilxlmr_ner_m1  app/

# Optional — set LLM fallback for low-confidence messages
export LLM_API_KEY=your_key
export LLM_PROVIDER=anthropic    # or: yandex / ollama

# Seed demo data (run once)
python demo_seed.py

# Launch
streamlit run sandbox.py
```

Opens at `http://localhost:8501`.

## What runs in the demo

| Component | Status |
|---|---|
| NER inference (distilXLM-R ONNX) | Real — if model present |
| LLM fallback (Anthropic / YandexGPT) | Real — if `LLM_API_KEY` set |
| Session binding (operator → machine) | Real `SessionService` |
| Rule engine | Real `RuleEngine` reading `fleet_rules.yaml` |
| EventProcessor pipeline | Identical to production |
| Database | SQLite file (`vfm_demo.db`) — swap to Postgres via `DATABASE_URL` env var |

## Seeded data

- Owner: Алексей Петров
- Operators: Иван Сидоров (200001), Пётр Кузнецов (200002), Михаил Фёдоров (200003)
- Machines: CAT-101 (Excavator), BLZ-042 (Dump truck), KOM-007 (Bulldozer)

## Demo scripts (run from sidebar)

| Script | What it shows |
|---|---|
| Normal shift | Start shift → fuel log → hours → end shift. Session binding, timeline writes, shift summary |
| Fuel anomaly | 300L logged after 2h work. Fuel ratio rule fires, owner alert triggered |
| Critical issue | "Пожар в кабине". Critical severity escalation, machine status → WARNING |
| Repeated faults | Three issues on same machine. `repeated_faults` rule fires |

## Switching to production Postgres

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
# Run Alembic migrations instead of init_db()
alembic upgrade head
```
