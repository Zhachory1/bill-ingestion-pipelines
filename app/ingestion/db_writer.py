from sqlalchemy.orm import Session
from app.db import models
from app.ingestion.xml_parser import ParsedBill, ParsedSponsor


def _upsert_sponsor(db: Session, s: ParsedSponsor) -> None:
    """Insert sponsor if not exists; update fields if they changed."""
    existing = db.get(models.Sponsor, s.bioguide_id)
    if existing is None:
        db.add(models.Sponsor(
            bioguide_id=s.bioguide_id,
            full_name=s.full_name,
            party=s.party,
            state=s.state,
        ))
    else:
        existing.full_name = s.full_name
        existing.party = s.party
        existing.state = s.state


def upsert_bill(db: Session, parsed: ParsedBill) -> None:
    """Insert or update a Bill and its sponsor/cosponsor relationships."""
    existing = db.get(models.Bill, parsed.bill_id)

    if existing is None:
        bill = models.Bill(
            bill_id=parsed.bill_id,
            congress=parsed.congress,
            bill_type=parsed.bill_type,
            bill_number=parsed.bill_number,
            title=parsed.title,
            summary=parsed.summary,
            latest_action=parsed.latest_action,
            latest_action_date=parsed.latest_action_date,
            last_updated=parsed.last_updated,
        )
        db.add(bill)
        db.flush()
    else:
        bill = existing
        bill.title = parsed.title
        bill.summary = parsed.summary
        bill.latest_action = parsed.latest_action
        bill.latest_action_date = parsed.latest_action_date
        bill.last_updated = parsed.last_updated

    for s in parsed.sponsors:
        _upsert_sponsor(db, s)
    for s in parsed.cosponsors:
        _upsert_sponsor(db, s)
    db.flush()

    bill.sponsors = [db.get(models.Sponsor, s.bioguide_id) for s in parsed.sponsors]
    bill.cosponsors = [db.get(models.Sponsor, s.bioguide_id) for s in parsed.cosponsors]
