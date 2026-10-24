#!/usr/bin/env python3
"""
scripts/seed_pilot.py

WP-D: seeds machines and operators from a local YAML/CSV file (not
committed — see .gitignore) and prints operator invite links. Run manually
against a disposable local database; never against production data from
this script without reviewing what it does first.

Usage:
    python -m scripts.seed_pilot --file pilot_data.yaml --bot-username my_dev_bot

Expected YAML shape:

    owner:
      name: "Иван Петров"
      mobile: "+70000000000"
    machines:
      - alias: "КАТ-101"
        reg_number: "А771МР77"
        type: "excavator"
        model: "CAT 320"
        year: 2020
    operators:
      - name: "Пётр"
        machine_alias: "КАТ-101"   # optional — pre-binds the invite to one machine
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path


async def _seed(file_path: Path, bot_username: str, invite_expiry_hours: int) -> None:
    import yaml
    from sqlalchemy import select

    from app.db.database import get_async_session
    from app.db.models import DEFAULT_ORG_ID, Invite, Machine, Org, User

    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))

    async for db in get_async_session():
        existing_org = await db.execute(select(Org).where(Org.id == DEFAULT_ORG_ID))
        if existing_org.scalar_one_or_none() is None:
            db.add(Org(id=DEFAULT_ORG_ID, name="Pilot Org", created_at=datetime.utcnow()))
            await db.flush()

        owner_data = data.get("owner", {})
        owner = User(
            org_id=DEFAULT_ORG_ID,
            mobile=owner_data.get("mobile", ""),
            name=owner_data.get("name", "Owner"),
            user_type="OWNER",
        )
        db.add(owner)
        await db.flush()

        alias_to_machine_id: dict[str, int] = {}
        for m in data.get("machines", []):
            machine = Machine(
                org_id=DEFAULT_ORG_ID,
                alias=m["alias"],
                reg_number=m["reg_number"],
                machine_type=m.get("type", "unknown"),
                model=m.get("model", "unknown"),
                year=m.get("year", 2020),
                owner_id=owner.id,
            )
            db.add(machine)
            await db.flush()
            alias_to_machine_id[m["alias"]] = machine.id

        print(f"Owner created: {owner.name} (id={owner.id})")
        print(f"Machines created: {len(alias_to_machine_id)}")
        print()
        print("Operator invite links:")

        for op in data.get("operators", []):
            token = secrets.token_urlsafe(24)
            machine_alias = op.get("machine_alias")
            invite = Invite(
                org_id=DEFAULT_ORG_ID,
                token=token,
                role="operator",
                operator_name=op["name"],
                machine_id=alias_to_machine_id.get(machine_alias) if machine_alias else None,
                created_by=owner.id,
                expires_at=datetime.utcnow() + timedelta(hours=invite_expiry_hours),
            )
            db.add(invite)
            print(f"  {op['name']}: https://t.me/{bot_username}?start={token}")

        await db.commit()
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to the local YAML pilot-data file (not committed)")
    parser.add_argument("--bot-username", required=True, help="e.g. my_dev_bot (no leading @)")
    parser.add_argument("--invite-expiry-hours", type=int, default=72)   # SPEC-001 OQ-001-2 starting value
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: {file_path} not found.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_seed(file_path, args.bot_username, args.invite_expiry_hours))


if __name__ == "__main__":
    main()
