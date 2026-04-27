import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.db_writer import upsert_bill, _upsert_subject
from app.ingestion.xml_parser import ParsedBill, ParsedSponsor


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_parsed_bill(**kwargs) -> ParsedBill:
    defaults = dict(
        bill_id="118-hr-1",
        congress=118,
        bill_type="hr",
        bill_number=1,
        title="Test Bill",
        summary="A summary",
        latest_action="Passed",
        latest_action_date="2023-01-15",
        last_updated="2023-01-15T10:00:00Z",
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/1",
        subjects=[],
        sponsors=[ParsedSponsor("A000001", "Jane Doe", "D", "CA")],
        cosponsors=[],
    )
    defaults.update(kwargs)
    return ParsedBill(**defaults)


def test_insert_new_bill(db):
    upsert_bill(db, make_parsed_bill())
    db.commit()
    bill = db.query(models.Bill).one()
    assert bill.bill_id == "118-hr-1"
    assert bill.title == "Test Bill"


def test_upsert_updates_existing_bill(db):
    upsert_bill(db, make_parsed_bill(title="Old Title"))
    db.commit()
    upsert_bill(db, make_parsed_bill(title="New Title", latest_action="Enacted"))
    db.commit()
    bills = db.query(models.Bill).all()
    assert len(bills) == 1  # no duplicate
    assert bills[0].title == "New Title"
    assert bills[0].latest_action == "Enacted"


def test_upsert_creates_sponsors(db):
    upsert_bill(db, make_parsed_bill())
    db.commit()
    sponsor = db.query(models.Sponsor).filter_by(bioguide_id="A000001").one()
    assert sponsor.full_name == "Jane Doe"
    bill = db.query(models.Bill).one()
    assert len(bill.sponsors) == 1


def test_upsert_does_not_duplicate_sponsors(db):
    upsert_bill(db, make_parsed_bill())
    upsert_bill(db, make_parsed_bill())
    db.commit()
    assert db.query(models.Sponsor).count() == 1


def test_upsert_creates_subjects(db):
    bill = make_parsed_bill(
        subjects=["Health care", "Taxation"],
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/1",
    )
    upsert_bill(db, bill)
    db.commit()
    result = db.query(models.Bill).one()
    assert len(result.subjects) == 2
    assert {s.name for s in result.subjects} == {"Health care", "Taxation"}


def test_upsert_does_not_duplicate_subjects(db):
    """Inserting the same bill twice must not create duplicate subject rows."""
    bill = make_parsed_bill(subjects=["Health care"])
    upsert_bill(db, bill)
    db.commit()
    upsert_bill(db, bill)
    db.commit()
    assert db.query(models.LegislativeSubject).count() == 1


def test_upsert_shares_subjects_across_bills(db):
    """Same subject name from two different bills -> one LegislativeSubject row."""
    upsert_bill(db, make_parsed_bill(bill_id="118-hr-1", bill_number=1, subjects=["Health care"]))
    upsert_bill(db, make_parsed_bill(bill_id="118-hr-2", bill_number=2, subjects=["Health care"]))
    db.commit()
    assert db.query(models.LegislativeSubject).count() == 1
    assert db.query(models.Bill).count() == 2


def test_upsert_subject_returns_existing(db):
    """_upsert_subject must return the existing row without raising when called twice."""
    s1 = _upsert_subject(db, "Education")
    db.commit()
    s2 = _upsert_subject(db, "Education")
    db.commit()
    assert s1.id == s2.id
    assert db.query(models.LegislativeSubject).count() == 1
