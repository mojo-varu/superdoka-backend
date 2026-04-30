# Group Message Endpoint Implementation Summary

All missing components have been added to support the `/api/v1/groups/messages` endpoint.

## Changes Made

### 1. Database Models (`app/db/models.py`)
Added two new SQLAlchemy models:

**Group Model**
- `group_id` (BigInteger, unique) - Telegram group identifier (e.g., "-1001234567890")
- `group_name` (String) - Human-readable group name
- `owner_id` (ForeignKey) - Links to User (OWNER type)
- `is_active` (Boolean) - Toggle group message collection
- Relationship to GroupMessage records

**GroupMessage Model**
- `group_id` (ForeignKey) - Links to Group
- `user_id` (ForeignKey, nullable) - Links to User if operator is recognized
- `telegram_user_id` (BigInteger) - Original Telegram user ID from message
- `username`, `first_name`, `last_name` - User info from message
- `telegram_message_id` (BigInteger, unique) - Message ID from Telegram (prevents duplicates)
- `message_text` (Text) - Message content
- `message_type` (String) - "regular|forwarded|forwarded_channel"
- `reply_to_message_id`, `original_sender` - For message threading/forwards
- `parsed_data` (Text) - JSON results from NER processing
- `processing_status` (String) - "pending|processed|failed"
- `created_at`, `updated_at` - Timestamps
- Comprehensive indexes for queries by group, date, and user

### 2. Endpoint Handler (`app/api/v1/endpoints/groups.py`)
New endpoint file with two routes:

**POST /api/v1/groups/messages**
- Receives message from Telegram bot sitting in group
- Authentication: `X-Secret-Key` header (secret token auth)
- Request validation using Pydantic model
- Workflow:
  1. Verify secret key
  2. Find group by `group_id`
  3. Match `telegram_user_id` to existing operator for that owner
  4. Create GroupMessage record (even if user not found)
  5. Return message ID and user match status
- Error handling for missing groups and internal errors
- Comprehensive logging

**POST /api/v1/groups/register**
- Register new groups for message collection
- Authentication: `X-Secret-Key` header
- Parameters: `group_id`, `group_name`, `owner_id`
- Returns registered group details

### 3. Configuration (`app/config.py`)
Added new setting:
- `GROUP_MESSAGE_SECRET_KEY` - Secret key for bot authentication
- Default: "your-secret-key-change-in-env"
- Should be set via `.env` file or environment variable

**Update your `.env` file:**
```
GROUP_MESSAGE_SECRET_KEY=your-actual-secret-key-here
```

### 4. Router Registration (`app/api/v1/api.py`)
- Imported groups module
- Registered groups_router with `/groups` prefix
- Automatically available at `/api/v1/groups/*`

### 5. Database Migration (`alembic/versions/001_add_group_tables.py`)
- Creates `groups` table with indexes
- Creates `group_messages` table with indexes
- Includes downgrade function for rollback
- Upgrade: `alembic upgrade head`
- Downgrade: `alembic downgrade -1`

---

## How It Works

### Message Flow
```
Telegram Group Bot
    ↓
POST /api/v1/groups/messages (with X-Secret-Key header)
    ↓
Validate bot secret key
    ↓
Lookup Group by group_id
    ↓
Match telegram_user_id to existing operator
    ↓
Store GroupMessage record
    ↓
Return: { message_id, status, user_matched }
```

### User Matching Logic
- Bot sends `user_id` (telegram_user_id) with message
- System looks for User with:
  - `telegram_id == user_id` from message
  - `owner_id == group.owner_id` (same owner)
- If found: `user_id` set in GroupMessage, `user_matched=true`
- If not found: `user_id` stays NULL, `user_matched=false`
- Message stored regardless of match (for manual review)

### Example Request
```bash
curl -X POST http://localhost:8000/api/v1/groups/messages \
  -H "X-Secret-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "-1001234567890",
    "group_name": "My Group",
    "user_id": 123456789,
    "username": "john_doe",
    "first_name": "John",
    "last_name": "Doe",
    "message_text": "#fuel 50 литров",
    "message_type": "regular",
    "message_id": 42,
    "timestamp": "2025-01-15T10:30:00.000000",
    "original_sender": null,
    "reply_to_message": null
  }'
```

### Example Response
```json
{
  "message_id": 1,
  "status": "received",
  "user_matched": true
}
```

---

## Running the Migration

```bash
# Apply migration
alembic upgrade head

# Check migration status
alembic current

# Rollback if needed
alembic downgrade -1
```

---

## Next Steps

1. **Update `.env` file** with actual secret key:
   ```
   GROUP_MESSAGE_SECRET_KEY=your-strong-secret-key-here
   ```

2. **Run migration** to create tables:
   ```bash
   alembic upgrade head
   ```

3. **Register groups** for each owner using the `/groups/register` endpoint
   
4. **Configure bot** to call this endpoint with messages from groups

5. **Implement NER processing** (next phase):
   - Queue messages for NER extraction
   - Create FuelLog/HoursLog/IssueReport from parsed results
   - Update GroupMessage with parsed_data and processing_status

6. **Add admin endpoints** (optional):
   - GET /groups - List groups for owner
   - GET /groups/{group_id}/messages - Get messages for group
   - DELETE /groups/{group_id} - Deactivate group
   - PATCH /groups/{group_id} - Update group settings

---

## Database Schema

### groups table
```
id (int) PRIMARY KEY
group_id (bigint) UNIQUE
group_name (varchar)
owner_id (int) FOREIGN KEY → users.id
is_active (boolean)
created_at (timestamp)
updated_at (timestamp)
INDEX: idx_groups_owner (owner_id)
```

### group_messages table
```
id (int) PRIMARY KEY
group_id (int) FOREIGN KEY → groups.id
user_id (int) FOREIGN KEY → users.id (nullable)
telegram_user_id (bigint)
username (varchar)
first_name (varchar)
last_name (varchar)
telegram_message_id (bigint) UNIQUE
message_text (text)
message_type (varchar)
reply_to_message_id (bigint)
original_sender (varchar)
parsed_data (text)
processing_status (varchar)
created_at (timestamp)
updated_at (timestamp)
INDEXES:
  - idx_group_messages_date_group (created_at, group_id)
  - idx_group_messages_user_date (telegram_user_id, created_at)
  - idx_group_messages_group_id (group_id)
  - idx_group_messages_user_id (user_id)
```

---

## Authentication & Security

### Current Approach
- **Secret Token Authentication** via `X-Secret-Key` header
- Token set in config: `GROUP_MESSAGE_SECRET_KEY`
- Must be included in every request to group endpoints

### Recommendations
- Use strong random string for secret key (min 32 chars)
- Store in environment variable, not in code
- Rotate periodically if compromised
- Log failed auth attempts
- Consider implementing token expiration/refresh in future

---

## Error Handling

| Status | Case |
|--------|------|
| 400 | Invalid request payload |
| 401 | Missing or invalid X-Secret-Key header |
| 404 | Group not found / Owner not found |
| 409 | Group already registered |
| 500 | Internal server error |

All errors logged with full context for debugging.

---

## Testing Checklist

- [ ] Run alembic migration successfully
- [ ] Test `/groups/messages` with valid payload
- [ ] Test auth failure without secret key
- [ ] Test auth failure with wrong secret key
- [ ] Test group not found error
- [ ] Test user matching (matched and unmatched)
- [ ] Test message deduplication (same telegram_message_id)
- [ ] Verify database records created correctly
- [ ] Check log output for proper logging
- [ ] Test `/groups/register` endpoint
