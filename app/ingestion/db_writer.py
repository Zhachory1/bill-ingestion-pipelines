"""Persist parsed bill data to the database via upsert logic."""

from sqlalchemy.exc import IntegrityError
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


def _upsert_subject(db: Session, name: str) -> models.LegislativeSubject:
    """Return the LegislativeSubject with the given name, creating it if absent.

    Uses a SAVEPOINT (begin_nested) so that a concurrent-insert IntegrityError
    only rolls back this nested transaction and not the enclosing upsert_bill
    session state.
    """
    existing = db.query(models.LegislativeSubject).filter_by(name=name).first()
    if existing is not None:
        return existing
    try:
        # Savepoint: rollback here only undoes the nested transaction, not the
        # parent session (which may have already flushed bill/sponsor rows).
        with db.begin_nested():
            obj = models.LegislativeSubject(name=name)
            db.add(obj)
        return obj
    except IntegrityError:
        return db.query(models.LegislativeSubject).filter_by(name=name).one()


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
            introduced_date=parsed.introduced_date,
            chamber=parsed.chamber,
            bill_url=parsed.bill_url,
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
        bill.introduced_date = parsed.introduced_date
        bill.chamber = parsed.chamber
        bill.bill_url = parsed.bill_url

    for s in parsed.sponsors:
        _upsert_sponsor(db, s)
    for s in parsed.cosponsors:
        _upsert_sponsor(db, s)
    db.flush()

    bill.sponsors = [sp for s in parsed.sponsors if (sp := db.get(models.Sponsor, s.bioguide_id)) is not None]
    bill.cosponsors = [sp for s in parsed.cosponsors if (sp := db.get(models.Sponsor, s.bioguide_id)) is not None]
    bill.subjects = [_upsert_subject(db, name) for name in parsed.subjects]
