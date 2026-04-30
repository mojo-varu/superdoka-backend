from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import logging

from app.db.database import get_db
from app.db.models import Group, GroupMessage, User
from app.config import settings

logger = logging.getLogger(__name__)

groups_router = APIRouter(tags=["Group Operations"])


# ============================================================================
# Request/Response Models
# ============================================================================

class GroupMessageRequest(BaseModel):
    group_id: str
    group_name: str
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    message_text: str
    message_type: str  # "regular|forwarded|forwarded_channel"
    message_id: int
    timestamp: datetime
    original_sender: Optional[str] = None
    reply_to_message: Optional[int] = None


class GroupMessageResponse(BaseModel):
    message_id: int
    status: str
    user_matched: bool


# ============================================================================
# Dependencies
# ============================================================================

async def verify_bot_token(x_secret_key: str = Header(...)):
    """Verify the bot secret key"""
    if x_secret_key != settings.GROUP_MESSAGE_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid bot token")
    return True


# ============================================================================
# Endpoints
# ============================================================================

@groups_router.post("/messages", response_model=GroupMessageResponse)
async def receive_group_message(
    message: GroupMessageRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_bot_token)
):
    """
    Receive a message from Telegram group bot and store it.
    
    This endpoint is called by a bot sitting in a Telegram group as an admin.
    It relays each message from group participants for processing.
    
    Headers required:
    - X-Secret-Key: GROUP_MESSAGE_SECRET_KEY from config
    """
    try:
        # 1. Get or create group
        group_result = await db.execute(
            select(Group).where(Group.group_id == int(message.group_id))
        )
        group = group_result.scalar_one_or_none()
        
        if not group:
            logger.warning(
                f"Group not found: {message.group_id} ({message.group_name}). "
                "Message will not be processed."
            )
            raise HTTPException(
                status_code=404,
                detail="Group not registered. Please register the group first."
            )
        
        # 2. Try to match telegram_user_id to existing operator in this owner's account
        user = None
        user_matched = False
        
        user_result = await db.execute(
            select(User).where(
                and_(
                    User.platform_user_id == message.user_id,
                    User.owner_id == group.owner_id
                )
            )
        )
        user = user_result.scalar_one_or_none()
        
        if user:
            user_matched = True
            logger.info(
                f"Matched user {message.user_id} to operator {user.name} "
                f"for group {message.group_id}"
            )
        else:
            logger.info(
                f"No matching operator found for telegram_user_id {message.user_id} "
                f"in owner {group.owner_id}"
            )
        
        # 3. Create group message record
        group_message = GroupMessage(
            group_id=group.id,
            user_id=user.id if user else None,
            telegram_user_id=message.user_id,
            username=message.username,
            first_name=message.first_name,
            last_name=message.last_name,
            telegram_message_id=message.message_id,
            message_text=message.message_text,
            message_type=message.message_type,
            reply_to_message_id=message.reply_to_message,
            original_sender=message.original_sender,
            created_at=message.timestamp
        )
        
        db.add(group_message)
        await db.commit()
        await db.refresh(group_message)
        
        logger.info(
            f"Group message stored: id={group_message.id}, "
            f"group={message.group_id}, telegram_user={message.user_id}"
        )
        
        return GroupMessageResponse(
            message_id=group_message.id,
            status="received",
            user_matched=user_matched
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error receiving group message: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@groups_router.post("/register")
async def register_group(
    group_id: str,
    group_name: str,
    owner_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_bot_token)
):
    """
    Register a new group for message collection.
    
    Only bot can call this endpoint (requires X-Secret-Key header).
    """
    try:
        # Check if owner exists
        owner_result = await db.execute(
            select(User).where(User.id == owner_id)
        )
        owner = owner_result.scalar_one_or_none()
        
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
        
        # Check if group already exists
        existing_group = await db.execute(
            select(Group).where(Group.group_id == int(group_id))
        )
        if existing_group.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Group already registered")
        
        # Create group
        group = Group(
            group_id=int(group_id),
            group_name=group_name,
            owner_id=owner_id
        )
        
        db.add(group)
        await db.commit()
        await db.refresh(group)
        
        logger.info(f"Group registered: {group_id} ({group_name}) for owner {owner_id}")
        
        return {
            "group_id": group.id,
            "telegram_group_id": group.group_id,
            "group_name": group.group_name,
            "status": "registered"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering group: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
