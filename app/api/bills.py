from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.api.deps import get_db
from app.api.schemas import BillOut, BillTextOut
from app.db import models

router = APIRouter()


def _get_bill_or_404(db: Session, bill_id: str) -> models.Bill:
    bill = (
        db.query(models.Bill)
        .options(
            joinedload(models.Bill.subjects),
            joinedload(models.Bill.sponsors),
            joinedload(models.Bill.cosponsors),
        )
        .filter(models.Bill.bill_id == bill_id)
        .first()
    )
    if bill is None:
        raise HTTPException(status_code=404, detail=f"Bill {bill_id!r} not found")
    return bill


@router.get("/bills/{bill_id}", response_model=BillOut)
def get_bill(bill_id: str, db: Session = Depends(get_db)):
    return BillOut.from_orm_bill(_get_bill_or_404(db, bill_id))


@router.get("/bills/{bill_id}/text", response_model=BillTextOut)
def get_bill_text(bill_id: str, db: Session = Depends(get_db)):
    bill = _get_bill_or_404(db, bill_id)
    parts = [bill.title or "", bill.summary or ""]
    text = "\n\n".join(p for p in parts if p).strip() or bill_id
    return BillTextOut(bill_id=bill.bill_id, title=bill.title, text=text)
