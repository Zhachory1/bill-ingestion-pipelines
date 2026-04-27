"""Tests for static file serving via the mounted StaticFiles route."""

import numpy as np
from unittest.mock import patch, MagicMock
import pytest
from tests.api.conftest import make_bill  # noqa: F401 — used indirectly via fixture chain


def _mock_model():
    model = MagicMock()
    model.encode.return_value = np.zeros(384, dtype=np.float32)
    return model


def test_index_html_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_chat_html_served(client):
    resp = client.get("/chat.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_api_bills_not_shadowed(client):
    """API route /api/bills/{id} should return 404 for unknown IDs, not serve static."""
    resp = client.get("/api/bills/nonexistent")
    assert resp.status_code == 404


def test_api_search_not_shadowed(client):
    """API route /api/search should respond normally, not be shadowed by StaticFiles."""
    with patch("app.api.search._get_model", return_value=_mock_model()), \
         patch("app.api.search._vector_search", return_value=[]):
        resp = client.get("/api/search?q=test")
    assert resp.status_code == 200


def test_missing_static_file(client):
    resp = client.get("/nonexistent-xyz.js")
    assert resp.status_code == 404
