"""Tests for API rate limiting and input validation."""

import pytest
from unittest.mock import patch

from app.config import settings
from app.rate_limit import limiter


@pytest.fixture
def client_with_rate_limit(client, monkeypatch):
    """Test client with low dynamic rate limits enabled."""
    original_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    monkeypatch.setattr(settings, "RATE_LIMIT_SEARCH", "2/minute")
    monkeypatch.setattr(settings, "RATE_LIMIT_CHAT", "2/minute")
    monkeypatch.setattr(settings, "RATE_LIMIT_FULLTEXT", "2/minute")
    yield client
    limiter.reset()
    limiter.enabled = original_enabled


@pytest.fixture
def client_without_rate_limit(client):
    """Test client with rate limiting disabled."""
    original_enabled = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    yield client
    limiter.reset()
    limiter.enabled = original_enabled


def test_search_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Search endpoint enforces rate limit."""
    with patch("app.api.search._get_model") as mock_model, patch(
        "app.api.search._vector_search", return_value=[]
    ):
        mock_model.return_value.encode.return_value.tolist.return_value = [0.1]

        resp1 = client_with_rate_limit.get("/api/search?q=test")
        resp2 = client_with_rate_limit.get("/api/search?q=test2")
        resp3 = client_with_rate_limit.get("/api/search?q=test3")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429
    assert "X-RateLimit-Limit" in resp3.headers or "Retry-After" in resp3.headers


def test_search_query_length_validation(client_with_rate_limit, db_with_bill, monkeypatch):
    """Search rejects queries exceeding MAX_QUERY_LENGTH."""
    monkeypatch.setattr(settings, "MAX_QUERY_LENGTH", 10)
    with patch("app.api.search._get_model") as mock_model, patch(
        "app.api.search._vector_search", return_value=[]
    ):
        mock_model.return_value.encode.return_value.tolist.return_value = [0.1]

        resp1 = client_with_rate_limit.get("/api/search?q=short")
        resp2 = client_with_rate_limit.get("/api/search?q=" + "x" * 100)

    assert resp1.status_code == 200
    assert resp2.status_code == 413
    assert "maximum length" in resp2.json()["detail"].lower()


def test_chat_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Chat endpoint enforces rate limit."""
    payload = {"messages": [{"role": "user", "content": "test"}]}

    with patch("app.api.chat.get_llm_client") as mock_client, patch(
        "app.api.chat.fetch_bill_text", return_value="Full text"
    ):
        mock_client.return_value.complete.return_value = "response"

        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)
        resp3 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429


def test_chat_message_length_validation(client_with_rate_limit, db_with_bill, monkeypatch):
    """Chat rejects messages exceeding MAX_MESSAGE_LENGTH."""
    monkeypatch.setattr(settings, "MAX_MESSAGE_LENGTH", 50)

    payload1 = {"messages": [{"role": "user", "content": "short message"}]}
    payload2 = {"messages": [{"role": "user", "content": "x" * 100}]}

    with patch("app.api.chat.get_llm_client") as mock_client, patch(
        "app.api.chat.fetch_bill_text", return_value="Full text"
    ):
        mock_client.return_value.complete.return_value = "response"
        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload1)
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload2)

    assert resp1.status_code == 200
    assert resp2.status_code == 422
    assert any("maximum length" in str(e).lower() for e in resp2.json()["detail"])


def test_chat_message_count_validation(client_with_rate_limit, db_with_bill, monkeypatch):
    """Chat rejects conversation history exceeding MAX_MESSAGE_COUNT."""
    monkeypatch.setattr(settings, "MAX_MESSAGE_COUNT", 3)

    payload1 = {
        "messages": [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
        ]
    }
    payload2 = {"messages": [{"role": "user", "content": f"msg{i}"} for i in range(10)]}

    with patch("app.api.chat.get_llm_client") as mock_client, patch(
        "app.api.chat.fetch_bill_text", return_value="Full text"
    ):
        mock_client.return_value.complete.return_value = "response"
        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload1)
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload2)

    assert resp1.status_code == 200
    assert resp2.status_code == 422
    assert any("maximum" in str(e).lower() for e in resp2.json()["detail"])


def test_fulltext_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Fulltext endpoint enforces rate limit."""
    with patch("app.api.bills.fetch_bill_text", return_value="Full text"):
        resp1 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")
        resp2 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")
        resp3 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 429


def test_rate_limit_disabled(client_without_rate_limit, db_with_bill):
    """When disabled, rate limits should not be enforced."""
    with patch("app.api.search._get_model") as mock_model, patch(
        "app.api.search._vector_search", return_value=[]
    ):
        mock_model.return_value.encode.return_value.tolist.return_value = [0.1]
        responses = [client_without_rate_limit.get("/api/search?q=test") for _ in range(10)]

    assert all(resp.status_code == 200 for resp in responses)


def test_rate_limit_per_ip_isolation(client_with_rate_limit, db_with_bill):
    """The same client IP hits its own rate limit bucket."""
    with patch("app.api.search._get_model") as mock_model, patch(
        "app.api.search._vector_search", return_value=[]
    ):
        mock_model.return_value.encode.return_value.tolist.return_value = [0.1]
        responses = [client_with_rate_limit.get("/api/search?q=test") for _ in range(3)]

    assert [resp.status_code for resp in responses] == [200, 200, 429]


@pytest.fixture
def db_with_bill(db):
    """Database with a sample bill for testing."""
    from app.db import models

    bill = models.Bill(
        bill_id="118-hr-1234",
        congress=118,
        bill_type="hr",
        bill_number=1234,
        title="Test Bill",
        summary="A test bill",
        chamber="House",
        text_url="https://example.com/bill.xml",
    )
    db.add(bill)
    db.commit()
    return db
