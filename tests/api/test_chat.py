from unittest.mock import patch, MagicMock
from tests.api.conftest import make_bill


def _mock_llm_client(reply: str = "LLM reply") -> MagicMock:
    client = MagicMock()
    client.complete.return_value = reply
    return client


def test_chat_returns_200(client, db):
    make_bill(db)
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client()):
        resp = client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "What is this bill?"}]},
        )
    assert resp.status_code == 200


def test_chat_returns_response_body(client, db):
    make_bill(db)
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client("Great bill.")):
        data = client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "Tell me about it."}]},
        ).json()
    assert data["bill_id"] == "118-hr-1"
    assert data["response"] == "Great bill."


def test_chat_bill_not_found(client, db):
    with patch("app.api.chat.get_llm_client", return_value=_mock_llm_client()):
        resp = client.post(
            "/api/chat/999-hr-9999",
            json={"messages": [{"role": "user", "content": "q"}]},
        )
    assert resp.status_code == 404


def test_chat_passes_bill_text_to_service(client, db):
    make_bill(db, title="Climate Reform Act", summary="Reduces carbon emissions.")
    captured = {}
    with patch("app.api.chat.get_llm_client") as mock_factory:
        llm = MagicMock()
        llm.complete.side_effect = lambda system, messages: (
            captured.update({"system": system}) or "ok"
        )
        mock_factory.return_value = llm
        client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "q"}]},
        )
    assert "Climate Reform Act" in captured["system"]
    assert "Reduces carbon emissions." in captured["system"]


def test_chat_invalid_role_returns_422(client, db):
    make_bill(db)
    resp = client.post(
        "/api/chat/118-hr-1",
        json={"messages": [{"role": "admin", "content": "hack"}]},
    )
    assert resp.status_code == 422


def test_chat_empty_messages_returns_422(client, db):
    make_bill(db)
    resp = client.post("/api/chat/118-hr-1", json={"messages": []})
    assert resp.status_code == 422


def test_chat_uses_full_govinfo_text_when_available(client, db):
    """When text_url is set and govinfo responds, the full text should reach the LLM."""
    import httpx as _httpx
    from unittest.mock import MagicMock

    make_bill(
        db,
        title="Climate Bill",
        summary="Short summary.",
        text_url="https://govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml",
    )

    gov_xml = b"<bill><text>FULL LEGISLATIVE TEXT CONTENT HERE</text></bill>"
    mock_http_resp = MagicMock()
    mock_http_resp.content = gov_xml
    mock_http_resp.raise_for_status = MagicMock()

    captured = {}
    with patch("app.api.bills.httpx.get", return_value=mock_http_resp), \
         patch("app.api.chat.get_llm_client") as mock_factory:
        llm = MagicMock()
        llm.complete.side_effect = lambda system, messages: (
            captured.update({"system": system}) or "ok"
        )
        mock_factory.return_value = llm
        client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "q"}]},
        )

    assert "FULL LEGISLATIVE TEXT CONTENT HERE" in captured.get("system", "")


def test_chat_falls_back_to_summary_when_govinfo_fails(client, db):
    """If govinfo fetch fails, chat should fall back to title+summary."""
    import httpx as _httpx

    make_bill(
        db,
        title="Climate Bill",
        summary="Short summary.",
        text_url="https://govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml",
    )

    captured = {}
    with patch("app.api.bills.httpx.get", side_effect=_httpx.HTTPError("timeout")), \
         patch("app.api.chat.get_llm_client") as mock_factory:
        llm = MagicMock()
        llm.complete.side_effect = lambda system, messages: (
            captured.update({"system": system}) or "ok"
        )
        mock_factory.return_value = llm
        resp = client.post(
            "/api/chat/118-hr-1",
            json={"messages": [{"role": "user", "content": "q"}]},
        )

    assert resp.status_code == 200
    assert "Climate Bill" in captured.get("system", "")
    assert "Short summary." in captured.get("system", "")


def test_chat_with_additional_bill_ids(client, db):
    """additional_bill_ids bills are fetched and passed to the service."""
    from unittest.mock import patch, MagicMock
    from app.db.models import Bill

    primary = Bill(bill_id="multi-primary", congress=118, bill_type="hr",
                   bill_number=8001, title="Primary Bill", summary="Primary summary")
    extra = Bill(bill_id="multi-extra", congress=118, bill_type="s",
                 bill_number=8002, title="Extra Bill", summary="Extra summary")
    db.add_all([primary, extra])
    db.commit()

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "ok"
    with patch("app.api.chat.ChatService.chat", return_value="ok") as mock_chat, \
         patch("app.api.chat.get_llm_client", return_value=mock_llm):
        resp = client.post("/api/chat/multi-primary", json={
            "messages": [{"role": "user", "content": "Compare these bills"}],
            "additional_bill_ids": ["multi-extra"],
        })
    assert resp.status_code == 200
    call_bills = mock_chat.call_args[1]["bills"]
    bill_titles = [t for t, _ in call_bills]
    assert "Primary Bill" in bill_titles
    assert "Extra Bill" in bill_titles
