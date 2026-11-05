# Proposed amendments to existing specs

Per `CLAUDE_CODE_BOT_BUILD_PROMPT.md` Step 2: exact requirement-ID changes needed in
existing Ready specs to support the Telegram bot work, **without editing those specs
directly**. A human (or a future, explicitly-approved commit) applies these.

## Already satisfied — no change needed

**SPEC-011-R01, R02** already require `org_id` on every table and already list an
`org` table in the v1 table set. The human's approved tenancy decision ("add an `org`
table and `org_id`, with a single default org... before a second customer is
onboarded, tenant scoping through one data-access layer plus a cross-org isolation
test (AC-011-01) is required") is **already fully specified** — `AC-011-01` already
exists verbatim in SPEC-011 §5. No amendment needed. The only action item is
operational, not a spec change: seed the single default org, and do not onboard a
second org until `AC-011-01` has an actual passing test, not just a specified one.

## SPEC-001 — channel, onboarding, idempotent inbound, corrections entry point

**Add SPEC-001-R15:** A chat bound to an `app_user` (R07) that has not recorded
consent (SPEC-016-R05) MUST see the consent prompt on its next message and MUST NOT
have that or any later message processed as operational data until consent is
recorded. *Why:* R07 currently describes binding and a welcome message but says
nothing about consent, and SPEC-016-R05's consent gate needs an explicit hook into
the onboarding sequence or it is easy to implement consent as a side door that a
determined test (or operator) can route around.

**Modify SPEC-001-R07's wording** to reference the new consent step by id, so the
onboarding sequence reads as one ordered flow: bind → welcome → consent → first
operational message, rather than appearing to allow consent to happen at an
unspecified point.

## SPEC-004 — state graph, timeline events, corrections, derived signals

**Add SPEC-004-R15:** CONFIRM-route and implausible results (SPEC-005-R04) MUST be
staged in a `pending_confirmation` row (SPEC-011 amendment below), not written to
`timeline_event`, until the operator confirms. Promotion from `pending_confirmation`
to `timeline_event` on confirmation MUST go through the same write path as R01 (one
`timeline_event` plus the specific log row plus `MachineState` UPSERT, in one
transaction). *Why:* R01/R02 already require that only confirmed events enter the
timeline, but neither specifies *where* an unconfirmed proposed value lives in the
meantime — today's code deviates by writing to `timeline_event` immediately and
flagging `needs_confirmation` afterward (`event_processor.py:426-430`). This closes
that gap per ADR-0023.

**Add SPEC-004-R16:** A `pending_confirmation` row not resolved within a configured
window (starting value: 24 hours, shared with SPEC-015's callback expiry, OQ-015-2)
MUST expire and MUST NOT be promotable afterward; an expired pending item that
receives a late ✅ tap is treated as a stale callback (SPEC-015-R07), not a commit.
*Why:* without an expiry, abandoned pending rows accumulate forever — the same class
of bug as the `fuel_added_today` counter that never resets (`SCOPE_SECTION2_EDITS.md`
item 4). This requirement exists so the same mistake is not repeated in the new
table.

**Modify SPEC-004-R06's wording** to note explicitly that a correction may originate
either from free text ("не 150, а 105", the existing mechanism) or from the ✏️
confirmation button (SPEC-015-R08) — both resolve through the same `corrects_event_id`
mechanism and the same `effective_events` resolution (R07). *Why:* clarifies that
these are one mechanism with two entry points, not two different correction models,
so a future implementer does not accidentally build two.

## SPEC-005 — policy engine and the three day-one behaviours

**Modify SPEC-005-R04's wording** to name the storage mechanism: "the decision MUST
be CONFIRM with `commit=after_confirm`... the proposed value is persisted to
`pending_confirmation` (SPEC-004-R15), not `timeline_event`, until the operator
confirms." *Why:* R04 already specifies the right behaviour (no silent log) but does
not currently say where the value lives while unconfirmed, which is exactly the gap
ADR-0023 closes. This is a clarifying amendment, not a behaviour change — R04's
testable outcome (`AC-005-04`) does not change.

## SPEC-011 — v1 data model and migrations

**Add SPEC-011-R14:** `pending_confirmation` (org, session, operator, machine, event
type, payload JSON, `source_conversation_id`, `proposed_at`, `expires_at`) MUST exist.
An index on `expires_at` MUST exist to support the expiry sweep (SPEC-004-R16).

**Add SPEC-011-R15:** `chat_state` (org, chat_id, state_key, state_payload JSON,
`updated_at`) MUST exist, unique on `(chat_id, state_key)`, to persist conversation
state such as `awaiting_correction` (SPEC-015-R08, R13) outside process memory.

**Add SPEC-011-R16:** A `channel_notice` table (channel, chat_id, notice_key,
`sent_at`), unique on `(channel, chat_id, notice_key)`, MUST exist to track "already
told this chat" one-time notices (for example the group-chat "write to me privately"
message, SPEC-001-R02), so a chat does not receive the same notice on every message.
*Why not reuse `chat_state`:* a group chat sending this notice is not bound to an
`app_user` or necessarily an `org` at the time the notice fires, so it needs a
narrower, org-optional table rather than overloading `chat_state`'s per-operator
semantics.

**Add SPEC-011-R17:** A `consent` record (either a dedicated table or columns on
`app_user` — implementation detail) MUST exist, capturing `app_user_id`, consent
timestamp, and the version of the consent text shown (SPEC-016-R05). *Why:* SPEC-011
is "one authoritative list of v1 tables" (§1 Purpose) and currently omits consent
storage entirely, even though SPEC-016-R05 and SPEC-001-R15 (above) both depend on it
existing.

## SPEC-003 — understanding pipeline (forward reference only, not proposed now)

**No amendment proposed in this task.** ADR-0026 (interim understanding backend,
Proposed, explicitly not implemented in this task) recommends a numeric-grounding
guardrail on LLM extraction. If and when ADR-0026 is accepted, SPEC-003 will need a
new requirement (`SPEC-003-R15` or next free id at that time) stating the grounding
check and its CLARIFY-on-failure behaviour, plus a matching acceptance scenario. This
is flagged here only so the dependency is visible; it is explicitly out of scope for
Step 2/3 of the current build task.

## Running `check_docs.py` after applying

None of the amendments above are applied to the existing spec files in this task —
per the build prompt's rule, existing specs are not edited directly. Once a human (or
an approved follow-up commit) applies them, re-run
`python3 docs/tools/check_docs.py --write` — the new requirement IDs (SPEC-001-R15,
SPEC-004-R15/R16, SPEC-011-R14–R17) will need at least one acceptance scenario each
to avoid new coverage-gap warnings, and SPEC-015's existing AC-015-03/04/06/08/09
already exercise most of the behaviour these amendments formalise, so most of the new
IDs can likely be satisfied by adding a `Proves` reference to an existing SPEC-015
scenario rather than writing an entirely new one.

---

## WP-B/WP-C implementation notes (added during Step 3 — code now exists)

The amendments above were written during Step 2, before any schema code existed.
Step 3 implemented the actual tables; this section records exactly what was built and
where it diverges from both SPEC-011's literal table names and from the Step 2
amendment text above, since a few details only became visible while writing the
migration (`alembic/versions/2026_10_24_bot_tenancy_and_pending_state.py`) and models
(`app/db/models.py`).

**Table naming — confirmed, not just proposed.** SPEC-011-R02 names `app_user` and
`shift_session`; the actual code keeps `users` (`User`) and `active_sessions`
(`ActiveSession`), per the build prompt's WP-B instruction to reconcile naming here
rather than rename existing tables. `PendingConfirmation`, `ChatState`,
`ChannelNotice`, `Invite`, and `Org` were added as new SQLAlchemy models with exactly
the shape the amendments above describe (`SPEC-011-R14`–`R17`).

**`Invite` vs. the existing `MachineAssignment` link-token fields — resolved
2026-11-05.** `MachineAssignment` had `telegram_link_token` / `telegram_link_expires_at`
/ `telegram_link_used_at` columns plus a `MachineOperatorLinkGenerator` class in
`app/api/v1/endpoints/owners.py`, used by `/owner/assignments` and by
`/verify-phone` (`app/api/v1/endpoints/operators.py`). That mechanism hardcoded the
wrong bot username and produced a link format (`operator_{id}_AUTH_{token}`) the
real bot's `/start` parser (`app/services/onboarding_service.bind_invite`) never
understood — the two mechanisms were not interoperable, and only the `Invite`-based
one actually worked against the deployed bot. Confirmed, by repo-wide grep, that
nothing else in the sandbox depended on the old mechanism. Decision: consolidated
on `Invite`; the old columns, `MachineOperatorLinkGenerator`, and both call sites
(`/owner/assignments` link generation, `/verify-phone`) are removed. `Invite` gained
`bound_user_id` so an owner can pre-create the operator's `User` row (the chat-driven
`/addoperator` front door, SPEC-001-R05/R06) and have redemption attach
`platform_user_id` to it instead of creating a duplicate row.

**Owner registration folded into the same `Invite` mechanism as operator invites,**
discriminated by `Invite.role`. SPEC-001-R04 describes a separate `/start
<owner_code>` concept; OQ-001-1 already says owner-code issuance is "manual for the
first customers" with no settled design, so Step 3 did not build a second mechanism
for an undecided process. If owner registration gets a real design later, this
decision should be revisited explicitly, not left as an implicit default.

**`conversation_log.raw_update` (new JSON column, not anticipated in the Step 2
amendments above).** Needed so `app/channels/worker.py` can reconstruct the exact
`NormalisedInbound` a webhook/polling delivery produced, without a second table. Also
doubles as the input SPEC-010's future replay harness would read — convenient, not
originally planned.

**`conversation_log.operator_id` and `.raw_text` were loosened to nullable.** An
inbound row from an unbound chat, or a non-text update (voice/photo), has no operator
yet and/or no text — SPEC-011-R03 doesn't list these as nullable, but the intake
design (insert-before-you-know-who-it-is) requires it. Flagged here since it's a
behavior-affecting schema choice, not just a naming difference.

**A real, confirmed ADR-0020 import-boundary gap — not closed in Step 3.**
`tests/channels/test_import_boundary.py` (written and actually executed in this
sandbox, see `docs/status` / the final report) found two violations:
1. `app/services/engine_entrypoint.py` (engine-side) imports `app.channels.telegram`
   for `copy_ru` (Russian strings) and `callback_data` (Telegram-specific encoding).
   This is because `handle_inbound()`'s `OutboundMessage.text` is already final,
   rendered text — there is no abstraction between "the engine decided what to say"
   and "the channel decided how to say it in Telegram's format." Properly fixing this
   means `OutboundMessage` carrying a reply *kind* plus structured parameters, with
   rendering (including callback_data encoding) happening entirely on the
   `app/channels/telegram` side. Not attempted in this pass — a real redesign, not a
   patch.
2. `app/channels/worker.py`, `webhook.py`, and `polling.py` import `app.db.database`/
   `app.db.models` directly for the "insert the inbound row and return fast" half of
   WP-C (`insert_received_row`), because ADR-0020's literal text gives channels no
   sanctioned entry point for this — only `handle_inbound`, which by design is NOT
   called until the worker picks the row back up. Two ways to close this: (a) a narrow
   ADR-0020 amendment explicitly carving out one additional, minimal intake function
   alongside `handle_inbound`, or (b) move the dedup-insert logic into
   `app/services/engine_entrypoint.py` as a second function and accept that
   ADR-0020's "exactly one function" becomes "exactly one *processing* function," with
   intake as a documented, separate exception. Recommend (a) — a proposed, not
   applied, ADR amendment — over silently picking one.

Both are reported, confirmed-by-test findings, not guesses — see the final report for
the exact test output.
