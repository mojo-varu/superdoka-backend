# Group Message Endpoint Review - `/api/v1/groups/messages`

## Current State Analysis

### Existing Architecture
- **FastAPI** framework with async/await support
- **SQLAlchemy** ORM with PostgreSQL
- Authentication via `X-Telegram-User-Id` header
- Existing endpoints for individual operators logging fuel, hours, and issues
- User model with `telegram_id`, `owner_id`, and `user_type` (OWNER/OPERATOR)

### Missing Components for Group Messages

#### 1. **Database Models** ⚠️
No `Group` or `GroupMessage` models exist. Need to add:

```python
class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(BigInteger, unique=True, nullable=False, index=True)  # "-1001234567890"
    group_name = Column(String(255), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    owner = relationship("User")
    messages: Mapped[List["GroupMessage"]] = relationship("GroupMessage", back_populates="group")

class GroupMessage(Base):
    __tablename__ = "group_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # NULL for unknown users
    
    # Telegram data
    telegram_user_id = Column(BigInteger, nullable=False, index=True)  # 123456789
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    telegram_message_id = Column(BigInteger, nullable=False, unique=True, index=True)  # 42
    
    # Message content
    message_text = Column(Text, nullable=False)
    message_type = Column(String(50), nullable=False)  # "regular|forwarded|forwarded_channel"
    
    # Message metadata
    reply_to_message_id = Column(BigInteger, nullable=True)  # For reply tracking
    original_sender = Column(String(255), nullable=True)  # For forwarded messages
    
    # Parsing/Processing
    parsed_data = Column(Text, nullable=True)  # JSON of NER extraction results
    processing_status = Column(String(50), default="pending", nullable=False)  # pending, processed, failed
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    group = relationship("Group", back_populates="messages")
    user = relationship("User")  # Optional, for recognized operators
    
    __table_args__ = (
        Index('idx_group_messages_date_group', 'created_at', 'group_id'),
        Index('idx_group_messages_user_date', 'telegram_user_id', 'created_at'),
        {"extend_existing": True}
    )
```

---

## Endpoint Implementation Required

### Route: `POST /api/v1/groups/messages`

**Payload Structure:**
```json
{
    "group_id": "-1001234567890",
    "group_name": "My Group",
    "user_id": 123456789,
    "username": "john_doe",
    "first_name": "John",
    "last_name": "Doe",
    "message_text": "Hello everyone",
    "message_type": "regular|forwarded|forwarded_channel",
    "message_id": 42,
    "timestamp": "2025-01-15T10:30:00.000000",
    "original_sender": null,
    "reply_to_message": null
}
```

**Authentication & Authorization:**
- **Current approach:** Uses `X-Telegram-User-Id` header
- **Problem:** This endpoint receives messages from an **admin bot**, not from authenticated users
- **Recommendation:** Implement one of these approaches:
  1. **Secret Token Auth** (Recommended for bot-to-server):
     - Add `GROUP_MESSAGE_SECRET_KEY` to config
     - Accept `X-Secret-Key` header on this endpoint
     - Validate: `X-Secret-Key == GROUP_MESSAGE_SECRET_KEY`
  
  2. **Bot Token-based Auth**:
     - Validate using `TELEGRAM_BOT_TOKEN`
     - Extract bot identity from token
  
  3. **IP Whitelist** (simple but less secure):
     - Restrict to known bot server IP

**Implementation Steps:**

1. **Create Pydantic models** for request/response:
   ```python
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
   ```

2. **Create endpoint handler** (`app/api/v1/endpoints/groups.py`):
   ```python
   from fastapi import APIRouter, Depends, HTTPException, Header
   from sqlalchemy.ext.asyncio import AsyncSession
   from sqlalchemy import select, and_
   from pydantic import BaseModel
   from typing import Optional
   from datetime import datetime
   
   groups_router = APIRouter(tags=["Group Operations"])
   
   # Dependency for bot authentication
   async def verify_bot_token(x_secret_key: str = Header(...)):
       if x_secret_key != settings.GROUP_MESSAGE_SECRET_KEY:
           raise HTTPException(status_code=401, detail="Invalid bot token")
       return True
   
   @groups_router.post("/messages")
   async def receive_group_message(
       message: GroupMessageRequest,
       db: AsyncSession = Depends(get_db),
       _: bool = Depends(verify_bot_token)
   ):
       """Receive message from Telegram group bot"""
       try:
           # 1. Get or create group
           group_result = await db.execute(
               select(Group).where(Group.group_id == message.group_id)
           )
           group = group_result.scalar_one_or_none()
           
           if not group:
               # Find the owner (group may be new)
               # For now, assume we need to look up or create
               raise HTTPException(status_code=404, detail="Group not found")
           
           # 2. Try to match user to existing operator
           user_result = await db.execute(
               select(User).where(
                   and_(
                       User.telegram_id == message.user_id,
                       User.owner_id == group.owner_id
                   )
               )
           )
           user = user_result.scalar_one_or_none()
           
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
           
           # 4. Optionally trigger NER parsing async
           # await process_message_async(group_message.id)
           
           return {
               "message_id": group_message.id,
               "status": "received",
               "user_matched": user is not None
           }
           
       except HTTPException:
           raise
       except Exception as e:
           logger.error(f"Error receiving group message: {str(e)}")
           raise HTTPException(status_code=500, detail="Internal server error")
   ```

3. **Register endpoint** in `app/api/v1/api.py`:
   ```python
   from app.api.v1.endpoints import groups
   
   api_router.include_router(groups.groups_router, prefix="/groups", tags=["Group Operations"])
   ```

---

## Key Considerations

### 1. **User Matching Strategy**
- **Current issue:** Endpoint receives messages from any group participant
- **Solution:** Match `user_id` (telegram_user_id) to existing operators under the group owner
- **Fallback:** Store message even if user not found (for manual review/parsing)

### 2. **Group Association**
- Need to establish relationship between owners and their groups
- Groups must be pre-registered in DB (by owner or admin)
- Each group message must be linked to a group and owner

### 3. **Message Processing Flow**
```
Bot sends message → POST /api/v1/groups/messages
                  ↓
         Validate bot token
                  ↓
      Get/Create Group record
                  ↓
      Match user to operator
                  ↓
    Store GroupMessage record
                  ↓
   Trigger NER processing (async)
                  ↓
   Extract fuel/hours/issue intents
                  ↓
  Create corresponding log records
```

### 4. **NER Integration**
- Current system has NER handler at `app/core/ner_handler.py`
- Group messages should be queued for NER processing
- Results should populate existing FuelLog, HoursLog, IssueReport tables
- Use `GroupMessage.parsed_data` to store extraction results

### 5. **Message Types Handling**
- **"regular"** - Direct message from user, process normally
- **"forwarded"** - Message forwarded from another chat, use `original_sender`
- **"forwarded_channel"** - Message from channel, may not have identified sender

### 6. **Deduplication**
- Use unique constraint on `telegram_message_id` to prevent duplicate processing
- `reply_to_message_id` tracks message threading

---

## Database Migration Required

```python
# alembic/versions/xxx_add_group_tables.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.BigInteger(), nullable=False),
        sa.Column('group_name', sa.String(255), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id'),
        sa.Index('idx_group_owner', 'owner_id')
    )
    
    op.create_table(
        'group_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(50), nullable=False),
        sa.Column('reply_to_message_id', sa.BigInteger(), nullable=True),
        sa.Column('original_sender', sa.String(255), nullable=True),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('processing_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_message_id'),
        sa.Index('idx_group_messages_date_group', 'created_at', 'group_id'),
        sa.Index('idx_group_messages_user_date', 'telegram_user_id', 'created_at')
    )
```

---

## Configuration Changes Required

**Update `app/config.py`:**
```python
class Settings(BaseSettings):
    # ... existing settings ...
    GROUP_MESSAGE_SECRET_KEY: str = "your-secret-key"  # Set in .env
```

---

## Testing Considerations

```python
# Example test payload
POST /api/v1/groups/messages
X-Secret-Key: your-secret-key

{
    "group_id": "-1001234567890",
    "group_name": "Test Group",
    "user_id": 123456789,
    "username": "testuser",
    "first_name": "Test",
    "last_name": "User",
    "message_text": "#fuel 50 литров",
    "message_type": "regular",
    "message_id": 42,
    "timestamp": "2025-01-15T10:30:00.000000",
    "original_sender": null,
    "reply_to_message": null
}
```

---

## Recommendations Summary

| Item | Status | Priority |
|------|--------|----------|
| Add Group model | ❌ Missing | High |
| Add GroupMessage model | ❌ Missing | High |
| Create groups.py endpoint | ❌ Missing | High |
| Implement bot auth (secret key) | ❌ Missing | High |
| Add config for secret key | ❌ Missing | High |
| Create DB migration | ❌ Missing | High |
| Integrate with NER pipeline | ⚠️ Partial | Medium |
| Add group management endpoints | ❌ Missing | Medium |
| Add message filtering/search | ❌ Missing | Low |
| Add message statistics | ❌ Missing | Low |
