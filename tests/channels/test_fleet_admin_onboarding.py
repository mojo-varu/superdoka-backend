"""
tests/channels/test_fleet_admin_onboarding.py

AUTHORED, NOT EXECUTED in this sandbox — sqlalchemy/aiosqlite/pytest are not
installed here (same situation as tests/channels/test_integration_authored.py;
see that file's docstring). Written to the same standard (in-memory SQLite via
aiosqlite, Base.metadata.create_all) and should run as-is once `poetry
install` succeeds, but that has not been verified by running them.

Covers SPEC-001-R05/R06/R13: app/services/fleet_admin_service.py (chat-driven
and REST-shared owner fleet admin), the bound_user_id consolidation of the
old MachineAssignment link-token mechanism onto Invite
(app/services/onboarding_service.bind_invite), and the /addmachine,
/addoperator bot commands (app/services/engine_entrypoint.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db import models  # noqa: F401 — registers all models on Base.metadata
from app.db.models import ConversationLog, DEFAULT_ORG_ID, Invite, Machine, MachineAssignment, Org, User
from app.channels.base import ChatType, NormalisedInbound
from app.services import fleet_admin_service, onboarding_service
from app.services.engine_entrypoint import _handle_add_machine, _handle_add_operator


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


async def _make_owner(db: AsyncSession, platform_user_id: int = 1) -> User:
    owner = User(org_id=DEFAULT_ORG_ID, platform_user_id=platform_user_id, mobile="", name="Владелец", user_type="OWNER")
    db.add(owner)
    await db.flush()
    await db.commit()
    return owner


def _inbound(command: str, args: str, chat_id: str = "1") -> NormalisedInbound:
    return NormalisedInbound(
        channel="telegram", update_id=f"upd-{chat_id}-{command}", chat_id=chat_id, user_id=chat_id,
        message_id="1", timestamp=datetime.utcnow(), chat_type=ChatType.PRIVATE,
        text=f"{command} {args}", command=command, command_args=args,
    )


async def _conv_row(db: AsyncSession, inbound: NormalisedInbound) -> ConversationLog:
    row = ConversationLog(channel=inbound.channel, update_id=inbound.update_id, chat_id=inbound.chat_id,
                           raw_text=inbound.text, source="telegram", processing_status="processing")
    db.add(row)
    await db.flush()
    return row


# --- fleet_admin_service.add_machine: alias scoping, R05 ---------------------

@pytest.mark.asyncio
async def test_duplicate_alias_rejected_same_owner_allowed_across_owners(db: AsyncSession):
    owner_a = await _make_owner(db, 1)
    owner_b = await _make_owner(db, 2)

    first = await fleet_admin_service.add_machine(
        db, owner=owner_a, reg_number="А771МР77", machine_type="экскаватор", model="CAT", year=2020, alias="КАТ-101",
    )
    assert first.outcome == fleet_admin_service.MachineOutcome.CREATED

    dup_same_owner = await fleet_admin_service.add_machine(
        db, owner=owner_a, reg_number="В222ОР77", machine_type="экскаватор", model="CAT", year=2020, alias="КАТ-101",
    )
    assert dup_same_owner.outcome == fleet_admin_service.MachineOutcome.DUPLICATE_ALIAS

    other_owner_same_alias = await fleet_admin_service.add_machine(
        db, owner=owner_b, reg_number="С333ТР77", machine_type="экскаватор", model="CAT", year=2020, alias="КАТ-101",
    )
    assert other_owner_same_alias.outcome == fleet_admin_service.MachineOutcome.CREATED


@pytest.mark.asyncio
async def test_duplicate_reg_number_rejected(db: AsyncSession):
    owner = await _make_owner(db, 1)
    first = await fleet_admin_service.add_machine(
        db, owner=owner, reg_number="А771МР77", machine_type="экскаватор", model="CAT", year=2020, alias="КАТ-101",
    )
    assert first.outcome == fleet_admin_service.MachineOutcome.CREATED

    second = await fleet_admin_service.add_machine(
        db, owner=owner, reg_number="А771МР77", machine_type="бульдозер", model="KOMATSU", year=2021, alias="БУЛ-101",
    )
    assert second.outcome == fleet_admin_service.MachineOutcome.DUPLICATE_REG_NUMBER


# --- onboarding_service.bind_invite: bound_user_id consolidation -------------

@pytest.mark.asyncio
async def test_bind_invite_with_bound_user_id_attaches_existing_user(db: AsyncSession):
    owner = await _make_owner(db, 1)
    pre_created = User(org_id=DEFAULT_ORG_ID, platform_user_id=None, mobile="+79990000000",
                        name="Иван Петров", user_type="OPERATOR", owner_id=owner.id)
    db.add(pre_created)
    await db.flush()

    invite = Invite(org_id=DEFAULT_ORG_ID, token="bound-token", role="operator",
                     operator_name=pre_created.name, created_by=owner.id, bound_user_id=pre_created.id,
                     expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(invite)
    await db.flush()
    await db.commit()

    result = await onboarding_service.bind_invite(db, "bound-token", 999)
    assert result.outcome == onboarding_service.BindOutcome.BOUND
    assert result.user.id == pre_created.id
    assert result.user.platform_user_id == 999

    from sqlalchemy import select, func
    count = (await db.execute(select(func.count(User.id)).where(User.user_type == "OPERATOR"))).scalar_one()
    assert count == 1, "must attach to the pre-created row, not create a second User"


@pytest.mark.asyncio
async def test_bind_invite_without_bound_user_id_creates_new_user(db: AsyncSession):
    owner = await _make_owner(db, 1)
    invite = Invite(org_id=DEFAULT_ORG_ID, token="owner-self-reg", role="owner",
                     created_by=None, bound_user_id=None,
                     expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(invite)
    await db.flush()
    await db.commit()

    result = await onboarding_service.bind_invite(db, "owner-self-reg", 888)
    assert result.outcome == onboarding_service.BindOutcome.BOUND
    assert result.user is not None
    assert result.user.platform_user_id == 888
    assert result.user.user_type == "OWNER"


# --- /addmachine, /addoperator bot commands -----------------------------------

@pytest.mark.asyncio
async def test_addmachine_wrong_token_count_creates_no_machine(db: AsyncSession):
    owner = await _make_owner(db, 1)
    inbound = _inbound("/addmachine", "А771МР77 экскаватор")  # missing alias — 2 tokens, not 3
    conv_row = await _conv_row(db, inbound)

    replies = await _handle_add_machine(db, inbound, owner, conv_row)
    assert len(replies) == 1
    from app.channels.telegram import copy_ru
    assert replies[0].text == copy_ru.ADDMACHINE_USAGE

    from sqlalchemy import select, func
    count = (await db.execute(select(func.count(Machine.id)))).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_addoperator_bad_machine_alias_creates_operator_but_no_assignment(db: AsyncSession):
    owner = await _make_owner(db, 1)
    inbound = _inbound("/addoperator", "Иван Петров, +79991234567, НЕСУЩЕСТВУЮЩИЙ")
    conv_row = await _conv_row(db, inbound)

    replies = await _handle_add_operator(db, inbound, owner, conv_row)
    assert len(replies) == 1
    from app.channels.telegram import copy_ru
    assert replies[0].text == copy_ru.addoperator_unknown_machine_alias("НЕСУЩЕСТВУЮЩИЙ")

    from sqlalchemy import select, func
    operator_count = (await db.execute(
        select(func.count(User.id)).where(User.user_type == "OPERATOR")
    )).scalar_one()
    assert operator_count == 1, "the operator row must still be created"

    assignment_count = (await db.execute(select(func.count(MachineAssignment.id)))).scalar_one()
    assert assignment_count == 0

    invite_count = (await db.execute(select(func.count(Invite.id)))).scalar_one()
    assert invite_count == 0, "no invite should be created when the given machine alias doesn't resolve"
