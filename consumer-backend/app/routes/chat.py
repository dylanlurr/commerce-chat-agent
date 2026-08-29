"""Chat route — the consumer's conversation endpoint."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException

from app.database import get_merchant_session
from app.schemas import ChatRequest, ChatResponse
from app.services.agent import chat

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
    """
    Process a consumer chat message through the AI agent.
    Connects dynamically to the merchant's dedicated database.
    """
    try:
        merchant_uuid = uuid.UUID(payload.merchant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid merchant UUID")

    tenant_db = await get_merchant_session(merchant_uuid)
    try:
        reply = await chat(
            db=tenant_db,
            session_id=payload.session_id,
            user_message=payload.message,
        )
        await tenant_db.commit()
        return ChatResponse(reply=reply)
    except Exception as e:
        await tenant_db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Agent error: {str(e)}",
        )
    finally:
        await tenant_db.close()
