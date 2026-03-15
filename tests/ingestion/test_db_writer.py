import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.db_writer import upsert_bill
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
