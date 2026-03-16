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
