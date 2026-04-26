import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_bill_insert_and_retrieve(db):
    bill = models.Bill(
        bill_id="118-hr-1234",
        congress=118,
        bill_type="hr",
        bill_number=1234,
        title="A Test Bill",
        latest_action="Passed House",
        latest_action_date="2023-01-15",
        last_updated="2023-01-15T10:00:00",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-1234").one()
    assert result.title == "A Test Bill"


def test_sponsor_join_table(db):
    bill = models.Bill(
        bill_id="118-hr-1", congress=118, bill_type="hr", bill_number=1,
        title="T", latest_action="", latest_action_date="2023-01-01", last_updated="2023-01-01"
    )
    sponsor = models.Sponsor(bioguide_id="A000001", full_name="Jane Doe", party="D", state="CA")
    bill.sponsors.append(sponsor)
    db.add(bill)
    db.commit()
    assert db.query(models.Bill).first().sponsors[0].full_name == "Jane Doe"


def test_parse_failure_log(db):
    failure = models.ParseFailure(
        file_path="/data/bills/118/hr/1/fdsys_billstatus.xml",
        error_message="KeyError: billType"
    )
    db.add(failure)
    db.commit()
    assert db.query(models.ParseFailure).count() == 1


def test_bill_embedding_column_exists(db):
    bill = models.Bill(
        bill_id="118-hr-9", congress=118, bill_type="hr", bill_number=9,
        title="Embedding Test", latest_action="", latest_action_date="2023-01-01", last_updated="2023-01-01",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-9").one()
    assert result.embedding is None  # null until embedding pipeline runs


def test_bill_new_fields(db):
    bill = models.Bill(
        bill_id="118-hr-99", congress=118, bill_type="hr", bill_number=99,
        title="Test", latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/99",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-99").one()
    assert result.introduced_date == "2023-01-05"
    assert result.chamber == "House"
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/house-bill/99"


def test_legislative_subjects(db):
    bill = models.Bill(
        bill_id="118-hr-55", congress=118, bill_type="hr", bill_number=55,
        title="Health Bill", latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
    )
    subject = models.LegislativeSubject(name="Health care")
    bill.subjects.append(subject)
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-55").one()
    assert len(result.subjects) == 1
    assert result.subjects[0].name == "Health care"


def test_subject_unique_constraint_enforced(db):
    """Unique constraint on name must reject raw duplicate inserts."""
    from sqlalchemy.exc import IntegrityError
    db.add(models.LegislativeSubject(name="Taxation"))
    db.commit()
    db.add(models.LegislativeSubject(name="Taxation"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
