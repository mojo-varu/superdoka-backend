from fastapi import Header, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Annotated, Optional, List
from datetime import datetime

from app.db.models import User, UserType
from app.db.database import get_db
import logging

logger = logging.getLogger(__name__)


def get_any_platform_user():
    async def checker(
        x_platform_user_id: int = Header(..., alias="X-Platform-User-Id"),
        db: AsyncSession = Depends(get_db)
    ):
        result = await db.execute(
            select(User).where(
                and_(
                    User.platform_user_id == x_platform_user_id,
                    User.is_active == True
                )
            )
        )
        users = result.scalars().all()

        if not users:
            raise HTTPException(status_code=404, detail="User not found")

        return users[0]

    return checker


def require_owner():
    async def checker(
        x_platform_user_id: int = Header(..., alias="X-Platform-User-Id"),
        db: AsyncSession = Depends(get_db)
    ):
        result = await db.execute(
            select(User).where(
                and_(
                    User.platform_user_id == x_platform_user_id,
                    User.is_active == True
                )
            ).order_by(User.user_type.desc())
        )
        users = result.scalars().all()

        if not users:
            raise HTTPException(status_code=404, detail="User not found")

        for user in users:
            if user.user_type == UserType.OWNER.value:
                return user

        raise HTTPException(status_code=403, detail="Owner access required")

    return checker
