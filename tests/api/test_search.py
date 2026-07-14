import numpy as np
from unittest.mock import patch, MagicMock
from tests.api.conftest import make_bill
from app.api.search import _vector_search
from app.db import models


def _mock_model():
    model = MagicMock()
    model.encode.return_value = np.zeros(384, dtype=np.float32)
    return model


def test_search_returns_200(client, db):
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[]):
        resp = client.get("/api/search?q=healthcare")
    assert resp.status_code == 200


def test_search_missing_query_returns_422(client, db):
    resp = client.get("/api/search")
    assert resp.status_code == 422


def test_search_returns_matching_results(client, db):
    make_bill(db)
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[
             {
                 "bill_id": "118-hr-1",
                 "score": 0.95,
                 "match_source": "full_text",
                 "snippet": "Section 1. Public health language.",
             }
         ]):
        data = client.get("/api/search?q=health").json()
    assert data["query"] == "health"
    assert len(data["results"]) == 1
    assert data["results"][0]["bill_id"] == "118-hr-1"
    assert data["results"][0]["score"] == 0.95
    assert data["results"][0]["match_source"] == "full_text"
    assert data["results"][0]["snippet"] == "Section 1. Public health language."


def test_search_encodes_query_string(client, db):
    model = _mock_model()
    with patch("app.api.search._get_model", return_value=model), \
         patch("app.api.search._vector_search", return_value=[]):
        client.get("/api/search?q=climate+change")
    model.encode.assert_called_once_with("climate change")


def test_search_passes_limit_to_vector_search(client, db):
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[]) as mock_vs:
        client.get("/api/search?q=test&limit=5")
    _, kwargs = mock_vs.call_args
    assert kwargs["limit"] == 5


def test_search_default_limit_is_10(client, db):
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[]) as mock_vs:
        client.get("/api/search?q=test")
    _, kwargs = mock_vs.call_args
    assert kwargs["limit"] == 10


def test_search_unknown_bill_ids_dropped_from_results(client, db):
    """Bills returned by vector search but missing from DB are silently dropped."""
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[
             {"bill_id": "999-hr-9999", "score": 0.80}
         ]):
        data = client.get("/api/search?q=ghost").json()
    assert len(data["results"]) == 0


def test_vector_search_combines_metadata_and_full_text_chunks(db):
    query_vec = [1.0] + [0.0] * 383
    off_axis = [0.0, 1.0] + [0.0] * 382
    make_bill(db, bill_id="118-hr-1", bill_number=1, title="Metadata Bill", embedding=off_axis)
    make_bill(db, bill_id="118-hr-2", bill_number=2, title="Full Text Bill", embedding=off_axis)
    db.add(
        models.BillTextChunk(
            bill_id="118-hr-2",
            chunk_index=0,
            text="Section 1. Appropriations language appears only in full text.",
            source_url="https://example.com/bill.xml",
            embedding=query_vec,
        )
    )
    db.commit()

    rows = _vector_search(db, query_vec, limit=10)

    assert rows[0]["bill_id"] == "118-hr-2"
    assert rows[0]["match_source"] == "full_text"
    assert rows[0]["snippet"] == "Section 1. Appropriations language appears only in full text."
