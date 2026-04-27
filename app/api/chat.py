"""Chat endpoint: POST /api/chat/{bill_id} — stateless LLM conversation about a bill."""

import httpx
from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.schemas import ChatRequest, ChatResponse
from app.api.bills import fetch_bill_text
from app.chat.llm import get_llm_client
from app.chat.service import ChatService
from app.db import models

router = APIRouter()


@router.post("/chat/{bill_id}", response_model=ChatResponse)
def chat(
    bill_id: str,
    request: ChatRequest,
    db: Session = Depends(get_db),
    x_llm_api_key: str | None = Header(default=None),
):
    """Send a message about a specific bill and receive an LLM response.

    Client owns conversation history — include the full messages list on every request.
    Uses full govinfo legislative text when available; falls back to title+summary.
    """
    bill = db.query(models.Bill).filter(models.Bill.bill_id == bill_id).first()
    if bill is None:
        logger.warning(f"Chat: bill not found: {bill_id!r}")
        raise HTTPException(status_code=404, detail=f"Bill {bill_id!r} not found")

    # Try to get full legislative text (HTML for structured headers); fall back to title+summary
    bill_text = None
    if bill.text_url:
        try:
            bill_text = fetch_bill_text(bill.text_url)
            logger.info(f"Using full govinfo text for {bill_id!r} ({len(bill_text)} chars)")
        except Exception as e:
            logger.warning(f"Full text fetch failed for {bill_id!r}, falling back: {e}")

    if not bill_text:
        parts = [bill.title or "", bill.summary or ""]
        bill_text = "\n\n".join(p for p in parts if p).strip() or bill_id

    logger.debug(f"chat bill_id={bill_id!r} turns={len(request.messages)} user_key={'yes' if x_llm_api_key else 'no'}")
    llm = get_llm_client(api_key=x_llm_api_key)
    service = ChatService(llm=llm)
    reply = service.chat(
        bill_text=bill_text,
        messages=[m.model_dump() for m in request.messages],
    )
    logger.debug(f"chat bill_id={bill_id!r} reply_chars={len(reply)}")
    return ChatResponse(bill_id=bill_id, response=reply)
