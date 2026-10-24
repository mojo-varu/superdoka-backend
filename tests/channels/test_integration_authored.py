"""
tests/channels/test_integration_authored.py

AUTHORED, NOT EXECUTED in this sandbox — sqlalchemy/aiosqlite/pytest are not
installed here (no pip/poetry, confirmed; see the final report for the
exact evidence). These are written to the same standard as this project's
existing integration tests (in-memory SQLite via aiosqlite, Base.metadata.
create_all) and should run as-is once `poetry install` succeeds — but that
has not been verified by running them. Treat every assertion here as a
claim to re-check, not a passing result.

Covers test scenarios 2, 3, 4, 5, 6, 7, 8, 11 from
CLAUDE_CODE_BOT_BUILD_PROMPT.md Step 3's numbered list, and the
corresponding AC- ids from SPEC-001/004/011/014/015.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import models  # noqa: F401 — registers all models on Base.metadata
from app.db.models import (
    ConversationLog, Invite, Machine, MachineAssignment, Org, DEFAULT_ORG_ID,
    PendingConfirmation, User,
)
from app.channels.base import ChatType, MediaKind, NormalisedInbound
from app.channels.worker import insert_received_row
from app.services import confirmation_service, onboarding_service
from app.services.engine_entrypoint import handle_inbound


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        session.add(Org(id=DEFAULT_ORG_ID, name="Test Org", created_at=datetime.utcnow()))
        await session.commit()
        yield session


async def _make_owner(db: AsyncSession) -> User:
    owner = User(org_id=DEFAULT_ORG_ID, platform_user_id=999, mobile="", name="Владелец", user_type="OWNER")
    db.add(owner)
    await db.flush()
    return owner


async def _make_machine(db: AsyncSession) -> Machine:
    m = Machine(org_id=DEFAULT_ORG_ID, reg_number="А771МР77", alias="КАТ-101", machine_type="excavator", model="CAT", year=2020)
    db.add(m)
    await db.flush()
    return m


# --- Scenario 2 / AC-014-02, AC-001-05, AC-011-02: duplicate update dedup ---

@pytest.mark.asyncio
async def test_duplicate_update_inserted_once(db: AsyncSession):
    inbound = NormalisedInbound(
        channel="telegram", update_id="dup-1", chat_id="555", user_id="555",
        message_id="1", timestamp=datetime.utcnow(), chat_type=ChatType.PRIVATE,
        text="hello",
    )
    first = await insert_received_row(db, inbound)
    second = await insert_received_row(db, inbound)
    assert first is True
    assert second is False

    from sqlalchemy import select, func
    count = (await db.execute(
        select(func.count(ConversationLog.id)).where(
            ConversationLog.channel == "telegram", ConversationLog.update_id == "dup-1"
        )
    )).scalar_one()
    assert count == 1


# --- Scenario 3 / AC-001-08, AC-016-01: unbound user gets onboarding, no state ---

@pytest.mark.asyncio
async def test_unbound_chat_gets_onboarding_and_creates_no_state(db: AsyncSession):
    inbound = NormalisedInbound(
        channel="telegram", update_id="u1", chat_id="777", user_id="777",
        message_id="1", timestamp=datetime.utcnow(), chat_type=ChatType.PRIVATE,
        text="залил 100",
    )
    replies = await handle_inbound(db, inbound)
    assert len(replies) == 1
    assert "систем" in replies[0].text.lower() or "ссылк" in replies[0].text.lower()

    from sqlalchemy import select
    assert (await db.execute(select(User).where(User.platform_user_id == 777))).scalar_one_or_none() is None


# --- Scenario 4 / AC-001-01: group message, at most one notice ---

@pytest.mark.asyncio
async def test_group_chat_gets_notice_once_not_twice(db: AsyncSession):
    inbound = NormalisedInbound(
        channel="telegram", update_id="g1", chat_id="-100", user_id="333",
        message_id="1", timestamp=datetime.utcnow(), chat_type=ChatType.GROUP,
        text="привет",
    )
    first = await handle_inbound(db, inbound)
    inbound2 = NormalisedInbound(
        channel="telegram", update_id="g2", chat_id="-100", user_id="333",
        message_id="2", timestamp=datetime.utcnow(), chat_type=ChatType.GROUP,
        text="ещё раз",
    )
    second = await handle_inbound(db, inbound2)
    assert len(first) == 1
    assert len(second) == 0, "the second group message in the same chat must not re-send the notice"


# --- Scenario 5 / AC-001-03, AC-001-11, AC-011-09: invite binds; reused/expired don't ---

@pytest.mark.asyncio
async def test_valid_invite_binds_reused_and_expired_do_not(db: AsyncSession):
    owner = await _make_owner(db)
    good = Invite(org_id=DEFAULT_ORG_ID, token="good-token", role="operator",
                   operator_name="Иван", created_by=owner.id,
                   expires_at=datetime.utcnow() + timedelta(hours=1))
    expired = Invite(org_id=DEFAULT_ORG_ID, token="expired-token", role="operator",
                      operator_name="Пётр", created_by=owner.id,
                      expires_at=datetime.utcnow() - timedelta(hours=1))
    db.add_all([good, expired])
    await db.flush()

    result = await onboarding_service.bind_invite(db, "good-token", 111)
    assert result.outcome == onboarding_service.BindOutcome.BOUND

    reused = await onboarding_service.bind_invite(db, "good-token", 222)
    assert reused.outcome == onboarding_service.BindOutcome.INVALID_OR_EXPIRED

    expired_result = await onboarding_service.bind_invite(db, "expired-token", 333)
    assert expired_result.outcome == onboarding_service.BindOutcome.INVALID_OR_EXPIRED


# --- Scenario 6 / AC-015-03, AC-004-01 (deviates): CONFIRM route stages, no TimelineEvent ---

@pytest.mark.asyncio
async def test_confirm_route_creates_pending_not_timeline_event(db: AsyncSession):
    from app.schemas.fleet_update import ConfidenceRoute, FleetUpdate, Intent, MessageSource, Modality, SessionContext
    from app.services.event_processor import event_processor

    machine = await _make_machine(db)
    operator = User(org_id=DEFAULT_ORG_ID, platform_user_id=444, mobile="", name="Иван",
                     user_type="OPERATOR", owner_id=(await _make_owner(db)).id)
    db.add(operator)
    await db.flush()

    update = FleetUpdate.from_raw(source=MessageSource.TELEGRAM, operator_id="444", chat_id="444",
                                   raw_text="залил 50", modality=Modality.TEXT)
    update.operator_db_id = operator.id
    update.intent = Intent.FUEL_LOG
    update.entities = {"fuel_volume": 50}
    update.session = SessionContext(machine_id=machine.id)
    update.confidence_route = ConfidenceRoute.CONFIRM

    await event_processor._write_events(db, update)

    assert update.timeline_event_id is None
    assert getattr(update, "_pending_confirmation_id", None) is not None

    from sqlalchemy import select
    from app.db.models import TimelineEvent
    tl_count = (await db.execute(select(TimelineEvent))).scalars().all()
    assert len(tl_count) == 0


# --- Scenario 7 / AC-015-04: double tap on ✅ creates exactly one event ---

@pytest.mark.asyncio
async def test_double_confirm_tap_creates_exactly_one_event(db: AsyncSession):
    machine = await _make_machine(db)
    owner = await _make_owner(db)
    operator = User(org_id=DEFAULT_ORG_ID, platform_user_id=555, mobile="", name="Иван",
                     user_type="OPERATOR", owner_id=owner.id)
    db.add(operator)
    await db.flush()

    pending = PendingConfirmation(
        org_id=DEFAULT_ORG_ID, operator_id=operator.id, machine_id=machine.id,
        event_type="FUEL_LOG", payload={"fuel_volume": 50}, raw_text="залил 50",
        proposed_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(pending)
    await db.flush()

    first = await confirmation_service.promote_pending_confirmation(db, pending.id)
    second = await confirmation_service.promote_pending_confirmation(db, pending.id)

    assert first.result == confirmation_service.PromotionResult.COMMITTED
    assert second.result == confirmation_service.PromotionResult.ALREADY_RESOLVED
    assert second.timeline_event_id == first.timeline_event_id

    from sqlalchemy import select
    from app.db.models import TimelineEvent
    events = (await db.execute(select(TimelineEvent).where(TimelineEvent.event_type == "FUEL_LOG"))).scalars().all()
    assert len(events) == 1


# --- Scenario 8 / AC-015-06: ✏️ on a committed event creates a linked correction ---

@pytest.mark.asyncio
async def test_correction_on_committed_event_links_to_original(db: AsyncSession):
    from app.services.correction_service import apply_correction

    machine = await _make_machine(db)
    from app.db.models import TimelineEvent
    original = TimelineEvent(machine_id=machine.id, operator_id=None, event_type="FUEL_LOG",
                              content={"fuel_volume": 150})
    db.add(original)
    await db.flush()

    correction = await apply_correction(db, original.id, "fuel_volume", 105)
    await db.commit()

    assert correction.corrected_event_id == original.id
    assert correction.content["new_value"] == 105
    assert correction.content["old_value"] == 150


# --- Scenario 11 / AC-015-07: voice/photo get polite replies, no event ---

@pytest.mark.asyncio
async def test_voice_message_gets_polite_reply_and_no_event(db: AsyncSession):
    owner = await _make_owner(db)
    invite = Invite(org_id=DEFAULT_ORG_ID, token="voice-token", role="operator",
                     operator_name="Иван", created_by=owner.id,
                     expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(invite)
    await db.flush()
    bound = await onboarding_service.bind_invite(db, "voice-token", 666)
    await onboarding_service.record_consent(db, bound.user, "v1-draft")

    inbound = NormalisedInbound(
        channel="telegram", update_id="v1", chat_id="666", user_id="666",
        message_id="1", timestamp=datetime.utcnow(), chat_type=ChatType.PRIVATE,
        media_kind=MediaKind.VOICE, media_file_unique_id="file-abc",
    )
    replies = await handle_inbound(db, inbound)
    assert len(replies) == 1
    assert "голос" in replies[0].text.lower()

    from sqlalchemy import select
    from app.db.models import TimelineEvent
    assert len((await db.execute(select(TimelineEvent))).scalars().all()) == 0


# --- Scenario 1 / AC-014-01, AC-001-10: missing/wrong webhook secret rejected ---
# Needs fastapi + httpx's TestClient, also not installed in this sandbox.
# Authored against the actual route for a human to run once dependencies exist.

@pytest.mark.asyncio
async def test_webhook_rejects_missing_or_wrong_secret(monkeypatch):
    import os
    os.environ["WEBHOOK_SECRET"] = "the-real-secret"
    os.environ["TELEGRAM_MODE"] = "webhook"
    os.environ["BOT_ENV"] = "dev"
    os.environ["TELEGRAM_BOT_TOKEN_DEV"] = "123:fake-token-for-test"
    os.environ["WEBHOOK_BASE_URL"] = "https://example.invalid"
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    missing = client.post("/api/v1/channels/telegram/webhook", json={"update_id": 1})
    assert missing.status_code == 401

    wrong = client.post(
        "/api/v1/channels/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert wrong.status_code == 401
