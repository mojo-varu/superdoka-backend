"""
app/services/onboarding_service.py

WP-D: owner/operator binding via /start <invite_token>, and consent
recording. SPEC-001-R04/R06/R07, SPEC-016-R05, SPEC-015-R03.

Owner registration (SPEC-001-R04, "/start <owner_code>") and operator
invites (SPEC-001-R06/R07) are implemented as ONE mechanism here (the
Invite table, discriminated by invite.role) rather than two, because
OQ-001-1 records that owner-code issuance is manual for the first customers
and has no settled design yet — reusing one binding path avoids building a
second, parallel mechanism for a process that isn't decided. Flagged, not
silently assumed: see docs/proposals/AMENDMENTS.md.

Engine-side module — no Telegram/aiogram imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DEFAULT_ORG_ID, Invite, MachineAssignment, User


class BindOutcome(str, Enum):
    BOUND = "bound"
    INVALID_OR_EXPIRED = "invalid_or_expired"
    ALREADY_BOUND_ELSEWHERE = "already_bound_elsewhere"   # this chat_id already has a *different* app_user


@dataclass
class BindResult:
    outcome: BindOutcome
    user: Optional[User] = None


async def find_bound_user(db: AsyncSession, platform_user_id: int) -> Optional[User]:
    """SPEC-001-R07 / SPEC-016-R01: the allowlist check. A chat_id (Telegram
    private chats: chat_id == the user's own id) is bound iff a User row
    with this platform_user_id exists."""
    result = await db.execute(select(User).where(User.platform_user_id == platform_user_id))
    return result.scalar_one_or_none()


async def bind_invite(
    db: AsyncSession,
    token: str,
    platform_user_id: int,
) -> BindResult:
    """
    SPEC-001-R07: single-use, expiring. An invalid, expired or used token
    produces no binding (caller shows the clear Russian message — SPEC-015-R02).
    """
    result = await db.execute(select(Invite).where(Invite.token == token))
    invite = result.scalar_one_or_none()

    if invite is None or invite.used_at is not None or invite.expires_at < datetime.utcnow():
        return BindResult(BindOutcome.INVALID_OR_EXPIRED)

    existing = await find_bound_user(db, platform_user_id)
    if existing is not None:
        # Known gap vs. SPEC-001-R07's "at most one app_user" intent — the
        # existing users.unique_platform_user_per_owner constraint is
        # (platform_user_id, owner_id), not platform_user_id alone, so the
        # same Telegram account *could* already be bound under a different
        # owner. Not re-designed in this pass (AMENDMENTS.md flags it).
        return BindResult(BindOutcome.ALREADY_BOUND_ELSEWHERE, existing)

    user = User(
        org_id=invite.org_id,
        platform_user_id=platform_user_id,
        mobile="",   # Telegram does not hand over a phone number without a separate consent flow — not collected in v1
        name=invite.operator_name or "Оператор",
        user_type="OWNER" if invite.role == "owner" else "OPERATOR",
        owner_id=invite.created_by if invite.role != "owner" else None,
    )
    db.add(user)
    await db.flush()   # get user.id before the machine assignment / invite update

    if invite.machine_id is not None and invite.role != "owner":
        db.add(MachineAssignment(machine_id=invite.machine_id, operator_id=user.id))

    invite.used_at = datetime.utcnow()
    invite.used_by = user.id
    await db.commit()
    await db.refresh(user)

    return BindResult(BindOutcome.BOUND, user)


async def record_consent(db: AsyncSession, user: User, consent_version: str) -> None:
    """SPEC-016-R05: stored before any operator message is treated as
    operational data."""
    user.consent_given_at = datetime.utcnow()
    user.consent_version = consent_version
    await db.commit()


def has_consented(user: User) -> bool:
    return user.consent_given_at is not None
