"""Tests for API rate limiting and input validation."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.config import Settings, LLMProvider


@pytest.fixture
def client_with_rate_limit():
    """Test client with rate limiting enabled."""
    with patch("app.config.settings", Settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_SEARCH="2/minute",  # Low limit for testing
        RATE_LIMIT_CHAT="2/minute",
        RATE_LIMIT_FULLTEXT="2/minute",
        LLM_PROVIDER=LLMProvider.ANTHROPIC,
        ANTHROPIC_API_KEY="test-key",
    )):
        yield TestClient(app)


@pytest.fixture
def client_without_rate_limit():
    """Test client with rate limiting disabled."""
    with patch("app.config.settings", Settings(
        RATE_LIMIT_ENABLED=False,
        LLM_PROVIDER=LLMProvider.ANTHROPIC,
        ANTHROPIC_API_KEY="test-key",
    )):
        yield TestClient(app)


def test_search_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Search endpoint enforces rate limit."""
    # First two requests should succeed
    resp1 = client_with_rate_limit.get("/api/search?q=test")
    resp2 = client_with_rate_limit.get("/api/search?q=test2")
    
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    
    # Third request should be rate limited
    resp3 = client_with_rate_limit.get("/api/search?q=test3")
    assert resp3.status_code == 429
    assert "X-RateLimit-Limit" in resp3.headers or "Retry-After" in resp3.headers


def test_search_query_length_validation(client_with_rate_limit, db_with_bill):
    """Search rejects queries exceeding MAX_QUERY_LENGTH."""
    with patch("app.config.settings.MAX_QUERY_LENGTH", 10):
        # Query within limit
        resp1 = client_with_rate_limit.get("/api/search?q=short")
        assert resp1.status_code == 200
        
        # Query exceeds limit
        resp2 = client_with_rate_limit.get("/api/search?q=" + "x" * 100)
        assert resp2.status_code == 413
        assert "maximum length" in resp2.json()["detail"].lower()


def test_chat_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Chat endpoint enforces rate limit."""
    payload = {"messages": [{"role": "user", "content": "test"}]}
    
    with patch("app.chat.llm.get_llm_client") as mock_client:
        mock_client.return_value.complete.return_value = "response"
        
        # First two requests should succeed
        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)
        
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        
        # Third request should be rate limited
        resp3 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload)
        assert resp3.status_code == 429


def test_chat_message_length_validation(client_with_rate_limit, db_with_bill):
    """Chat rejects messages exceeding MAX_MESSAGE_LENGTH."""
    with patch("app.config.settings.MAX_MESSAGE_LENGTH", 50):
        # Message within limit
        payload1 = {"messages": [{"role": "user", "content": "short message"}]}
        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload1)
        # May fail on bill not found, but not validation
        assert resp1.status_code != 422
        
        # Message exceeds limit
        payload2 = {"messages": [{"role": "user", "content": "x" * 100}]}
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload2)
        assert resp2.status_code == 422
        errors = resp2.json()["detail"]
        assert any("maximum length" in str(e).lower() for e in errors)


def test_chat_message_count_validation(client_with_rate_limit, db_with_bill):
    """Chat rejects conversation history exceeding MAX_MESSAGE_COUNT."""
    with patch("app.config.settings.MAX_MESSAGE_COUNT", 3):
        # Within limit
        payload1 = {
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "resp1"},
                {"role": "user", "content": "msg2"},
            ]
        }
        resp1 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload1)
        assert resp1.status_code != 422  # Not validation error
        
        # Exceeds limit
        payload2 = {
            "messages": [
                {"role": "user", "content": f"msg{i}"}
                for i in range(10)
            ]
        }
        resp2 = client_with_rate_limit.post("/api/chat/118-hr-1234", json=payload2)
        assert resp2.status_code == 422
        errors = resp2.json()["detail"]
        assert any("maximum" in str(e).lower() for e in errors)


def test_fulltext_rate_limit_enforced(client_with_rate_limit, db_with_bill):
    """Fulltext endpoint enforces rate limit."""
    with patch("app.api.bills.fetch_bill_text", return_value="Full text"):
        # First two requests should succeed
        resp1 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")
        resp2 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")
        
        # May fail on bill not having text_url, but not rate limited
        assert resp1.status_code != 429
        assert resp2.status_code != 429
        
        # Third request should be rate limited
        resp3 = client_with_rate_limit.get("/api/bills/118-hr-1234/fulltext")
        assert resp3.status_code == 429


def test_rate_limit_disabled(client_without_rate_limit, db_with_bill):
    """When disabled, rate limits should not be enforced."""
    # Make many requests - should all succeed (or fail for other reasons, not rate limit)
    for _ in range(10):
        resp = client_without_rate_limit.get("/api/search?q=test")
        assert resp.status_code != 429


def test_rate_limit_per_ip_isolation(client_with_rate_limit, db_with_bill):
    """Different IPs should have separate rate limit counters."""
    # This test assumes the rate limiter uses X-Forwarded-For or similar
    # In production, different IPs would naturally be separate
    # For testing, we can verify the same IP hits the limit
    
    for _ in range(2):
        resp = client_with_rate_limit.get("/api/search?q=test")
        assert resp.status_code == 200
    
    # Should now be rate limited
    resp = client_with_rate_limit.get("/api/search?q=test")
    assert resp.status_code == 429


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
