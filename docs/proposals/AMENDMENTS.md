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
