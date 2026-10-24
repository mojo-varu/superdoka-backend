---
id: ADR-0018
title: Bot framework and runtime — aiogram 3
status: Accepted
date: 2026-10-24
deciders: Varun
scope_refs: ["§3 Pillar 2"]
specs: [SPEC-014]
---

# ADR-0018: Bot framework and runtime — aiogram 3

## Context
There is no existing bot process (`MVP_ASSESSMENT_FOR_CLAUDE.md` §6 — the Telegram
bot's hosting, token, and update loop are not in this repo). A library has to be
picked before any Telegram-specific code is written. Candidates considered were
aiogram 3, pyTelegramBotAPI, and a thin hand-rolled HTTP client against the Bot API.

## Decision
We will use **aiogram 3** for all Telegram-specific code. Current aiogram
documentation MUST be checked before pinning an exact version (library release
cadence is faster than this document). All aiogram imports live under
`app/channels/telegram/` and nowhere else in the codebase (SPEC-014-R13 / SPEC-001-R03
enforce this as an import boundary, not just a convention).

## Consequences
**Good:** aiogram 3 is async-native (matches the existing async SQLAlchemy stack),
supports both webhook and long-polling intake with the same handler/dispatcher model
(needed for ADR-0019), and has first-class typed update/filter support that reduces
hand-rolled payload parsing.
**Costs and risks:** adds a dependency with its own upgrade cadence; aiogram's
internal types must never leak past `app/channels/base.py` (ADR-0020) or the
import-boundary test (SPEC-014-R13) has no teeth.

## Alternatives considered
| Option | Why not (or why not yet) |
|---|---|
| pyTelegramBotAPI | Sync-first design fights the existing async FastAPI/SQLAlchemy stack; would need a thread-pool bridge for every call. |
| Hand-rolled HTTP client against the raw Bot API | More control, but reimplements update parsing, long-polling offset handling, and retry semantics aiogram already provides correctly. Revisit only if aiogram's abstractions prove to be in the way. |

## Revisit when
aiogram 3 proves unable to cleanly support both webhook and polling behind one
handler (ADR-0019), or a major breaking aiogram release lands mid-pilot and the
cost of upgrading exceeds the cost of migrating off it.

## Enforced by
SPEC-014-R13. Test AC-014-11.
