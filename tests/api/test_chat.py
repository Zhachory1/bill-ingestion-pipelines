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
