"""Persist parsed bill data to the database via upsert logic."""

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import models
from app.ingestion.xml_parser import ParsedBill, ParsedSponsor


def _upsert_sponsor(db: Session, s: ParsedSponsor) -> None:
    """Insert sponsor if not exists; update fields if they changed.

    Uses a SAVEPOINT so that a concurrent-insert IntegrityError only rolls back
    the nested transaction, keeping the parent session intact.
    """
    existing = db.get(models.Sponsor, s.bioguide_id)
    if existing is not None:
        existing.full_name = s.full_name
        existing.party = s.party
        existing.state = s.state
        return
    try:
        with db.begin_nested():
            db.add(models.Sponsor(
                bioguide_id=s.bioguide_id,
                full_name=s.full_name,
                party=s.party,
                state=s.state,
            ))
    except IntegrityError:
        existing = db.get(models.Sponsor, s.bioguide_id)
        if existing is not None:
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
        logger.debug(f"Inserting new bill {parsed.bill_id!r}")
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
        logger.debug(f"Updating bill {parsed.bill_id!r}")
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

    # Deduplicate by bioguide_id: some XMLs list the same person twice,
    # which would cause a unique violation on the association table PK.
    seen: set[str] = set()
    bill.sponsors = []
    for s in parsed.sponsors:
        if s.bioguide_id not in seen and (sp := db.get(models.Sponsor, s.bioguide_id)):
            bill.sponsors.append(sp)
            seen.add(s.bioguide_id)
    seen.clear()
    bill.cosponsors = []
    for s in parsed.cosponsors:
        if s.bioguide_id not in seen and (sp := db.get(models.Sponsor, s.bioguide_id)):
            bill.cosponsors.append(sp)
            seen.add(s.bioguide_id)
    bill.subjects = [_upsert_subject(db, name) for name in parsed.subjects]
