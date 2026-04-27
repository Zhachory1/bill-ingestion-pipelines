"""Chat endpoint: POST /api/chat/{bill_id} — stateless LLM conversation about a bill."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.schemas import ChatRequest, ChatResponse
from app.chat.llm import get_llm_client
from app.chat.service import ChatService
from app.db import models

router = APIRouter()


@router.post("/chat/{bill_id}", response_model=ChatResponse)
def chat(bill_id: str, request: ChatRequest, db: Session = Depends(get_db)):
    """Send a message about a specific bill and receive an LLM response.

    Client owns conversation history — include the full messages list on every request.
    """
    bill = db.query(models.Bill).filter(models.Bill.bill_id == bill_id).first()
    if bill is None:
        raise HTTPException(status_code=404, detail=f"Bill {bill_id!r} not found")

    parts = [bill.title or "", bill.summary or ""]
    bill_text = "\n\n".join(p for p in parts if p).strip() or bill_id

    llm = get_llm_client()
    service = ChatService(llm=llm)
    reply = service.chat(
        bill_text=bill_text,
        messages=[m.model_dump() for m in request.messages],
    )
    return ChatResponse(bill_id=bill_id, response=reply)
