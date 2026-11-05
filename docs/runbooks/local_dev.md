# Runbook: local development with the dev bot

Document only — nothing here is executed by this task.

## Prerequisites

- `TELEGRAM_BOT_TOKEN_DEV` already set in `.env` (confirmed present during
  this build; this process never read or printed its value).
- Poetry installed, dependencies installed (`poetry install`). **Note:**
  this sandbox could not verify this step at all — no `poetry`, `pip`, or
  internet access to install anything (see the final report's baseline
  section). Run this yourself and confirm it works before trusting
  anything else in this runbook.

## Option A — bare metal

```bash
cp .env.example .env   # if starting fresh; otherwise your existing .env already has the dev token
# edit .env: TELEGRAM_MODE=polling, BOT_ENV=dev
poetry install         # now pulls in aiogram too — see pyproject.toml
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload
```

That's the whole dev workflow — one process, one command. With
`TELEGRAM_MODE=polling`, the app's own lifespan (`app/main.py`) starts both
the bot worker **and** the Telegram poll loop as background asyncio tasks
automatically. There is no second terminal to run. (Running
`python -m app.channels.telegram.polling` separately alongside `uvicorn` is
still possible but pointless — it would just start a second, redundant
worker against the same table. See that module's docstring.)

## Option B — Docker Compose (same as the existing demo flow)

```bash
docker compose up -d
```

Add the new env vars to `.env` (names only, see `.env.example`):
`TELEGRAM_MODE=polling`, `BOT_ENV=dev`, `TELEGRAM_BOT_TOKEN_DEV` (already
set). `docker-compose.yml`'s `api` service substitutes these in (WP-A). The
`api` container runs `uvicorn app.main:app`, so the same single-process
in-app polling loop applies here too — nothing extra to run or configure
for the bot specifically.

## Testing the flow end to end

1. Open your dev bot in Telegram (the one tied to `TELEGRAM_BOT_TOKEN_DEV`
   — never the prod bot for this).
2. Generate an invite:
   ```bash
   poetry run python -m scripts.seed_pilot --file your_local_pilot_data.yaml --bot-username <dev_bot_username>
   ```
   (`your_local_pilot_data.yaml` is yours to create locally — not
   committed, matches the `pilot_data*.yaml` gitignore pattern added in
   this phase. See `scripts/seed_pilot.py`'s docstring for the expected
   shape.)
3. Tap the printed `/start <token>` link from a **second** real Telegram
   account (not the one running the bot) — this cannot be simulated
   without a second account; see the final report's "must verify live"
   section.
4. Send a consent confirmation, then a message like "залил 50 литров".
   You should see a ✅/✏️ confirmation prompt (CONFIRM route) or an
   immediate "Записал" (AUTO route) depending on extraction confidence.

## Resetting local state

```bash
rm -f *.db   # the SQLite dev fallback, if DATABASE_URL points at one — never do this against docker-compose's Postgres volume
```
