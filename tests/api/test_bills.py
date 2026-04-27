from tests.api.conftest import make_bill
from app.db import models


def test_get_bill_returns_200(client, db):
    make_bill(db)
    resp = client.get("/api/bills/118-hr-1")
    assert resp.status_code == 200


def test_get_bill_returns_correct_fields(client, db):
    make_bill(db)
    data = client.get("/api/bills/118-hr-1").json()
    assert data["bill_id"] == "118-hr-1"
    assert data["title"] == "Test Bill"
    assert data["chamber"] == "House"
    assert data["introduced_date"] == "2023-01-05"
    assert data["bill_url"] == "https://www.congress.gov/bill/118th-congress/house-bill/1"
    assert isinstance(data["subjects"], list)
    assert isinstance(data["sponsors"], list)


def test_get_bill_includes_subjects(client, db):
    bill = make_bill(db)
    subject = models.LegislativeSubject(name="Health care")
    bill.subjects.append(subject)
    db.commit()
    data = client.get("/api/bills/118-hr-1").json()
    assert "Health care" in data["subjects"]


def test_get_bill_includes_sponsors(client, db):
    bill = make_bill(db)
    sponsor = models.Sponsor(
        bioguide_id="A000001", full_name="Jane Doe", party="D", state="CA"
    )
    bill.sponsors.append(sponsor)
    db.commit()
    data = client.get("/api/bills/118-hr-1").json()
    assert len(data["sponsors"]) == 1
    assert data["sponsors"][0]["bioguide_id"] == "A000001"
    assert data["sponsors"][0]["full_name"] == "Jane Doe"


def test_get_bill_not_found(client, db):
    resp = client.get("/api/bills/999-hr-9999")
    assert resp.status_code == 404


def test_get_bill_text_returns_200(client, db):
    make_bill(db)
    resp = client.get("/api/bills/118-hr-1/text")
    assert resp.status_code == 200


def test_get_bill_text_contains_title_and_summary(client, db):
    make_bill(db, title="Climate Bill", summary="Reduces emissions.")
    data = client.get("/api/bills/118-hr-1/text").json()
    assert data["bill_id"] == "118-hr-1"
    assert data["title"] == "Climate Bill"
    assert "Climate Bill" in data["text"]
    assert "Reduces emissions." in data["text"]


def test_get_bill_text_fallback_when_no_content(client, db):
    make_bill(db, title=None, summary=None)
    data = client.get("/api/bills/118-hr-1/text").json()
    assert data["text"] == "118-hr-1"


def test_get_bill_text_not_found(client, db):
    resp = client.get("/api/bills/999-hr-9999/text")
    assert resp.status_code == 404
