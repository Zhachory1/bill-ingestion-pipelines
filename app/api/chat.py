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
from app.config import settings
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

    def _get_bill_text(b, bid: str) -> str:
        text = None
        if b.text_url:
            try:
                text = fetch_bill_text(b.text_url)
                logger.info(f"Using full govinfo text for {bid!r} ({len(text)} chars)")
            except Exception as e:
                logger.warning(f"Full text fetch failed for {bid!r}, falling back: {e}")
        if not text:
            parts = [b.title or "", b.summary or ""]
            text = "\n\n".join(p for p in parts if p).strip() or bid
        return text

    # Primary bill
    bill_text = _get_bill_text(bill, bill_id)
    bills = [(bill.title or bill_id, bill_text)]

    # Additional bills from client request
    for extra_id in request.additional_bill_ids:
        extra = db.query(models.Bill).filter(models.Bill.bill_id == extra_id).first()
        if extra is None:
            logger.warning(f"Chat: additional bill not found: {extra_id!r}, skipping")
            continue
        extra_text = _get_bill_text(extra, extra_id)
        bills.append((extra.title or extra_id, extra_text))
        logger.debug(f"Added additional bill {extra_id!r} to chat context")

    if not x_llm_api_key and settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=401, detail="An API key is required. Add yours via the 'Set API key' button.")

    logger.debug(f"chat bill_id={bill_id!r} turns={len(request.messages)} bills={len(bills)} user_key={'yes' if x_llm_api_key else 'no'}")
    llm = get_llm_client(api_key=x_llm_api_key)
    service = ChatService(llm=llm)
    reply = service.chat(
        bills=bills,
        messages=[m.model_dump() for m in request.messages],
    )
    logger.debug(f"chat bill_id={bill_id!r} reply_chars={len(reply)}")
    return ChatResponse(bill_id=bill_id, response=reply)
