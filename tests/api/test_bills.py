from unittest.mock import patch, MagicMock

import pytest

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


# ---------------------------------------------------------------------------
# BillOut now includes text_url
# ---------------------------------------------------------------------------

def test_get_bill_includes_text_url_field(client, db):
    make_bill(db)
    data = client.get("/api/bills/118-hr-1").json()
    assert "text_url" in data


def test_get_bill_text_url_is_none_by_default(client, db):
    make_bill(db)
    data = client.get("/api/bills/118-hr-1").json()
    assert data["text_url"] is None


def test_get_bill_text_url_returned_when_set(client, db):
    make_bill(db, text_url="https://govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml")
    data = client.get("/api/bills/118-hr-1").json()
    assert data["text_url"] == "https://govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml"


# ---------------------------------------------------------------------------
# /api/bills/{id}/fulltext
# ---------------------------------------------------------------------------

_XML_URL = "https://govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml"
_HTML_URL = "https://govinfo.gov/content/pkg/BILLS-118hr1ih/html/BILLS-118hr1ih.htm"
_SAMPLE_HTML = b"<html><body><pre>SECTION 1. Hello World</pre></body></html>"


def test_fulltext_returns_404_when_no_text_url(client, db):
    make_bill(db)  # text_url=None by default
    resp = client.get("/api/bills/118-hr-1/fulltext")
    assert resp.status_code == 404


def test_fulltext_returns_404_for_unknown_bill(client, db):
    resp = client.get("/api/bills/999-hr-9999/fulltext")
    assert resp.status_code == 404


def test_fulltext_returns_plain_text_from_govinfo(client, db):
    """text_url in response is the HTML URL; text is extracted from <pre>."""
    make_bill(db, text_url=_XML_URL)

    mock_resp = MagicMock()
    mock_resp.content = _SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()

    with patch("app.api.bills.httpx.get", return_value=mock_resp):
        data = client.get("/api/bills/118-hr-1/fulltext").json()

    assert data["bill_id"] == "118-hr-1"
    assert data["text_url"] == _HTML_URL
    assert "Hello World" in data["text"]


def test_fulltext_returns_502_when_govinfo_fails(client, db):
    import httpx as _httpx

    make_bill(db, text_url=_XML_URL)

    with patch("app.api.bills.httpx.get", side_effect=_httpx.HTTPError("timeout")):
        resp = client.get("/api/bills/118-hr-1/fulltext")

    assert resp.status_code == 502


def test_fulltext_collapses_whitespace(client, db):
    make_bill(db, text_url=_XML_URL)

    spaced_html = b"<html><body><pre>   Hello     World   </pre></body></html>"
    mock_resp = MagicMock()
    mock_resp.content = spaced_html
    mock_resp.raise_for_status = MagicMock()

    with patch("app.api.bills.httpx.get", return_value=mock_resp):
        data = client.get("/api/bills/118-hr-1/fulltext").json()

    assert "  " not in data["text"]
    assert "Hello" in data["text"]
    assert "World" in data["text"]
