# Runbook: bot deployment

Document only — nothing here is executed by this task. All commands below
are for the human to run.

## Known discrepancy — read this first

**ADR-0021 says "deployed twice... each with its own database and Docker
Compose project."** The repo today has **one** `docker-compose.yml` (the
existing demo/dev stack) plus **one override file** `docker-compose.prod.yml`
(`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
--build`) — the standard Compose override pattern, not two independent
Compose projects. Both patterns give you separate containers, networks and
volumes (the prod override uses `superdoka_*` container/volume names vs.
`logbuk_*` for dev, and its own `env_file: .env.prod`), so the *separation*
ADR-0021 cares about (no shared token, no shared database, no shared
running process) **is achieved** — but the literal words "two Compose
projects" don't match what's on disk. This is flagged as a real conflict
in the final report, not resolved here; this runbook documents the actual
files that exist.

## Local dev → demo instance (existing, unchanged)

```bash
docker compose build api
docker compose up -d
```

Uses `docker-compose.yml` as-is. `TELEGRAM_MODE`, `BOT_ENV`,
`TELEGRAM_BOT_TOKEN_DEV`, `WEBHOOK_SECRET`, `WEBHOOK_BASE_URL` are read from
the root `.env` via Compose's own variable substitution (added to the
`api` service's `environment:` block in WP-A — see `docker-compose.yml`).
Default `TELEGRAM_MODE=polling` for this instance unless you have a public
URL for it.

## Production instance (new, for real pilot operators)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

1. Copy `.env.prod.example` → `.env.prod` on the VPS, fill in real values
   (never commit `.env.prod` — already gitignored).
2. Set `BOT_ENV=prod`, `TELEGRAM_MODE=webhook`,
   `TELEGRAM_BOT_TOKEN_PROD=<real token>`, `WEBHOOK_SECRET=<a long random
   string, e.g. `openssl rand -hex 32`>`, `WEBHOOK_BASE_URL=https://<this
   instance's own public domain>` — **not** `demo.superdoka.ru`, that's the
   separate demo instance.
3. Bring the stack up (command above). This runs `alembic upgrade head`
   automatically (see `docker-compose.prod.yml`'s `api` command), then
   `uvicorn` with 2 workers.
4. Register the webhook:
   ```bash
   docker compose exec api python -m app.channels.telegram.admin set-webhook
   ```
   (never prints the token — SPEC-014-R06).
5. **Verify inbound reachability** — this is explicitly **not yet
   verified** per the human's own stated facts (the build prompt: "the bot
   token works from the VPS [outbound]... inbound webhook reachability
   from Telegram to the VPS is not yet verified"):
   ```bash
   docker compose exec api python -m app.channels.telegram.admin info
   ```
   Check `last_error_message` in the output — if Telegram could not reach
   your webhook URL on a previous delivery attempt, it shows up there.
   `getWebhookInfo`'s exact current response fields should be checked
   against the live Bot API docs; this runbook doesn't hardcode them.

## Polling fallback if inbound reachability fails

If step 5 shows persistent delivery errors (firewall, no public IP, no
reverse proxy yet):

```bash
docker compose exec api python -m app.channels.telegram.admin delete-webhook
docker compose exec -d api python -m app.channels.telegram.polling
```

**Never run polling with the prod token while a webhook is set** — the
admin CLI's polling entry point (`app/channels/telegram/polling.py`)
refuses to start under `BOT_ENV=prod` if `get_webhook_info()` shows an
active webhook, specifically to prevent this.

## Reverse proxy (not applied by this task — example only)

```nginx
location /api/v1/channels/telegram/webhook {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
}
```

`docker-compose.prod.yml` already binds the `api` service to
`127.0.0.1:8000` only (not `0.0.0.0`), so a reverse proxy terminating TLS
is required for Telegram to reach the webhook at all over HTTPS.

## Rollback

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
# fix the issue, then:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations in this phase (WP-B) are reversible
(`alembic downgrade -1` inside the container) — test the downgrade on a
disposable database before relying on it in a real rollback.

## Backup

Unchanged from ADR-0014: nightly encrypted `pg_dump` of the `superdoka_db`
volume, one tested restore. Not automated by this task.
