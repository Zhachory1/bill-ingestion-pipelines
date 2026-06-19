from unittest.mock import Mock, patch

from app.config import settings
from app.text_cache import clear_text_cache, get_cached_text, truncate_text
from tests.api.conftest import make_bill


def test_get_cached_text_fetches_once_per_key():
    clear_text_cache()
    fetcher = Mock(return_value="Bill text")

    assert get_cached_text("https://example.com/bill.xml", fetcher) == "Bill text"
    assert get_cached_text("https://example.com/bill.xml", fetcher) == "Bill text"

    fetcher.assert_called_once_with("https://example.com/bill.xml")


def test_truncate_text_caps_bill_context(monkeypatch):
    monkeypatch.setattr(settings, "MAX_BILL_TEXT_CHARS", 10)

    truncated = truncate_text("x" * 20)

    assert truncated.startswith("x" * 10)
    assert "Truncated" in truncated


def test_chat_uses_cached_and_truncated_full_text(client, db, monkeypatch):
    clear_text_cache()
    monkeypatch.setattr(settings, "MAX_BILL_TEXT_CHARS", 12)
    make_bill(db, bill_id="118-hr-1234", text_url="https://example.com/bill.xml")
    mock_llm = Mock()
    mock_llm.complete.return_value = "answer"

    with patch("app.api.chat.fetch_bill_text", return_value="abcdefghijklmnopqrstuvwxyz") as fetch_text, patch(
        "app.api.chat.get_llm_client", return_value=mock_llm
    ):
        for _ in range(2):
            response = client.post(
                "/api/chat/118-hr-1234",
                json={"messages": [{"role": "user", "content": "summarize"}]},
            )
            assert response.status_code == 200

    fetch_text.assert_called_once_with("https://example.com/bill.xml")
    system_prompt = mock_llm.complete.call_args.kwargs["system"]
    assert "abcdefghijkl" in system_prompt
    assert "mnopqrstuvwxyz" not in system_prompt
    assert "Truncated" in system_prompt
