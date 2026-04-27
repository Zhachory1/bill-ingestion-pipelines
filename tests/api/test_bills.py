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


# ---------------------------------------------------------------------------
# Similar bills endpoint
# ---------------------------------------------------------------------------

def test_get_similar_bills_returns_200(client, db):
    """Bill with embedding returns 200, a list, and the expected payload fields."""
    import numpy as np
    vec = np.random.rand(384).tolist()
    make_bill(db, bill_id="test-similar-1", bill_number=9001, title="Source Bill", embedding=vec)
    make_bill(db, bill_id="test-similar-2", bill_number=9002, title="Neighbour Bill", embedding=vec)

    resp = client.get("/api/bills/test-similar-1/similar")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [r["bill_id"] for r in data]
    assert "test-similar-1" not in ids

    first = data[0]
    assert set(["bill_id", "title", "score", "chamber", "introduced_date", "bill_url"]).issubset(first.keys())
    assert isinstance(first["score"], float)


def test_get_similar_bills_excludes_self(client, db):
    """Source bill never appears in its own similar results."""
    import numpy as np
    vec = np.random.rand(384).tolist()
    make_bill(db, bill_id="test-self-excl", bill_number=9003, title="Self Exclusion Test", embedding=vec)

    resp = client.get("/api/bills/test-self-excl/similar")
    assert resp.status_code == 200
    ids = [r["bill_id"] for r in resp.json()]
    assert "test-self-excl" not in ids


def test_get_similar_bills_no_embedding_returns_404(client, db):
    """Bill with no embedding returns 404."""
    make_bill(db, bill_id="test-no-embed", bill_number=9004, title="No Embedding Bill", embedding=None)

    resp = client.get("/api/bills/test-no-embed/similar")
    assert resp.status_code == 404


def test_get_similar_bills_not_found_returns_404(client):
    """Non-existent bill_id returns 404."""
    resp = client.get("/api/bills/does-not-exist-xyz/similar")
    assert resp.status_code == 404


def test_get_similar_bills_respects_limit(client, db):
    """Limit param caps the result count (5 neighbours in DB, limit=3 must return exactly 3)."""
    import numpy as np
    vec = np.random.rand(384).tolist()
    make_bill(db, bill_id="test-limit-src", bill_number=9010, title="Limit Source", embedding=vec)
    for i in range(5):
        make_bill(
            db, bill_id=f"test-limit-n{i}", bill_number=9011 + i,
            title=f"Neighbour {i}", embedding=np.random.rand(384).tolist(),
        )

    resp = client.get("/api/bills/test-limit-src/similar?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
