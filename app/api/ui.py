# app/api/ui.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional
from pathlib import Path
import json
import logging

from app.db.database import get_db
from app.db.models import GroupMessage

logger = logging.getLogger(__name__)

ui_router = APIRouter(prefix="/ui", tags=["UI"])


@ui_router.get("/group-messages", response_class=HTMLResponse)
async def group_messages_dashboard(
    group_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Display group messages in a web dashboard with filtering by auto-detected tags.
    
    Query parameters:
    - group_id: Optional group ID to filter messages from a specific group
    """
    try:
        # Build query
        query = select(GroupMessage).order_by(desc(GroupMessage.created_at))
        
        if group_id:
            query = query.where(GroupMessage.group_id == group_id)
        
        result = await db.execute(query)
        messages = result.scalars().all()
        
        # Convert to dict format for JSON serialization
        messages_data = []
        for msg in messages:
            messages_data.append({
                "id": msg.id,
                "message_text": msg.message_text,
                "first_name": msg.first_name,
                "username": msg.username,
                "telegram_user_id": msg.telegram_user_id,
                "created_at": msg.created_at.isoformat(),
                "message_type": msg.message_type
            })
        
        # Read template
        template_path = Path(__file__).parent.parent / "templates" / "group_messages.html"
        with open(template_path, 'r') as f:
            template = f.read()
        
        # Inject data into template
        messages_json = json.dumps(messages_data)
        html = template.replace(
            "<body>",
            f'<body data-messages=\'{messages_json}\'>'
        )
        
        return html
        
    except Exception as e:
        logger.error(f"Error rendering group messages dashboard: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
