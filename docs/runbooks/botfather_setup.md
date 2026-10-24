# Runbook: BotFather setup

Document only — nothing here is executed by this task. Run these steps
yourself in Telegram, talking to @BotFather.

## 1. Create the dev bot (if not already done)

The repo's `.env` already has `TELEGRAM_BOT_TOKEN_DEV` populated (confirmed
present during this build, value never read or printed by this process).
If you need a *second* dev bot or are setting this up fresh:

1. `/newbot` → choose a name and a `_bot`-suffixed username.
2. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN_DEV`. Never put it in
   `docker-compose.yml` directly — that file only references
   `${TELEGRAM_BOT_TOKEN_DEV}` for substitution from `.env` (see
   `docker-compose.yml`'s `api` service, WP-A).

## 2. Identity

- `/setname` — e.g. "SuperDoka (dev)" to visually distinguish from prod in
  your own Telegram client.
- `/setdescription` — short Russian description, e.g.:
  "Цифровой помощник для операторов спецтехники. Присылайте обновления по
  смене — топливо, часы, проблемы."
- `/setabouttext` — one line, Russian.

## 3. Command list — `/setcommands`

Only commands the code actually implements (SPEC-015-R01). For the
validation slice this is exactly:

```
start - Начать работу / привязать аккаунт
help - Что писать боту
```

Do **not** add `/today`, `/machine`, `/waybill`, `/trace` yet — those ship
with SPEC-008/SPEC-009, not this phase. Re-run `/setcommands` when they do.

## 4. Privacy mode — `/setprivacy`

Leave privacy mode **Enabled** (the BotFather default). This means the bot
only receives messages that are commands, replies to it, or sent in a
private chat — it will not silently read every message in a group even if
someone adds it. Combined with step 5, group chats are a non-issue.

## 5. Disable "allow groups" — `/setjoingroups`

Set to **Disabled**. SPEC-001-R02/ADR-0022: private 1:1 chats only. This
means the bot cannot be added to a group at all, which is a stronger,
earlier guarantee than the in-app "please write to me privately" notice
(`app/services/engine_entrypoint.py::_handle_non_private`) — that handler
still exists as defence in depth for any update that slips through
(e.g. an old group membership predating this setting), but should never be
the *only* control.

## 6. Repeat for prod

Do all of the above again for the **prod** bot, using
`TELEGRAM_BOT_TOKEN_PROD` (also already present in `.env`, not read or
printed by this process). Use a visually distinct name (no "(dev)" suffix,
or an explicit "(prod)" if that helps avoid confusion) so you can never
mistake which bot you're talking to in your own Telegram client.

## 7. Token rotation (SPEC-016-R08)

If a token is ever compromised:

1. In BotFather: `/revoke` (or `/token` to get a fresh one — check current
   BotFather menu wording, it has changed before).
2. Update the relevant `.env` (`TELEGRAM_BOT_TOKEN_DEV`) or `.env.prod`
   (`TELEGRAM_BOT_TOKEN_PROD`) — never both from the same rotation.
3. Re-run `python -m app.channels.telegram.admin set-webhook` (prod) or
   restart the polling process (dev) so the new token takes effect.
4. No data migration is needed (ADR-0021) — the token is not stored
   anywhere except env config.
