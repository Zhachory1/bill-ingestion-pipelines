from unittest.mock import MagicMock
from app.chat.service import ChatService


def _mock_llm(reply: str = "test reply") -> MagicMock:
    llm = MagicMock()
    llm.complete.return_value = reply
    return llm


def test_chat_returns_llm_reply():
    service = ChatService(llm=_mock_llm("This bill addresses taxes."))
    result = service.chat(
        bills=[("H.R. 1 — Tax Reform Act", "Full text here...")],
        messages=[{"role": "user", "content": "What is this bill about?"}],
    )
    assert result == "This bill addresses taxes."


def test_chat_includes_bill_text_in_system_prompt():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(
        bills=[("Climate Act", "SECTION 1. Climate provisions.")],
        messages=[{"role": "user", "content": "Tell me about climate."}],
    )
    system_arg = llm.complete.call_args[1]["system"]
    assert "SECTION 1. Climate provisions." in system_arg


def test_chat_includes_bill_title_in_system_prompt():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(
        bills=[("Climate Act", "SECTION 1. Climate provisions.")],
        messages=[{"role": "user", "content": "Tell me about climate."}],
    )
    system_arg = llm.complete.call_args[1]["system"]
    assert "Climate Act" in system_arg


def test_chat_includes_multiple_bills_in_system_prompt():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(
        bills=[
            ("H.R. 1 — Tax Reform Act", "SECTION 1. Tax provisions."),
            ("S. 2 — Climate Act", "SECTION 1. Climate provisions."),
        ],
        messages=[{"role": "user", "content": "Compare these bills."}],
    )
    system_arg = llm.complete.call_args[1]["system"]
    assert "H.R. 1 — Tax Reform Act" in system_arg
    assert "S. 2 — Climate Act" in system_arg
    assert "SECTION 1. Tax provisions." in system_arg
    assert "SECTION 1. Climate provisions." in system_arg


def test_chat_passes_messages_to_llm():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    messages = [
        {"role": "user", "content": "What does section 3 say?"},
        {"role": "assistant", "content": "Section 3 covers..."},
        {"role": "user", "content": "How much funding?"},
    ]
    service.chat(bills=[("Some Bill", "bill text")], messages=messages)
    messages_arg = llm.complete.call_args[1]["messages"]
    assert messages_arg == messages


def test_chat_system_prompt_is_nonpartisan():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(bills=[("Any Bill", "anything")], messages=[{"role": "user", "content": "q"}])
    system_arg = llm.complete.call_args[1]["system"]
    assert "non-partisan" in system_arg.lower() or "neutral" in system_arg.lower()


def test_chat_system_prompt_instructs_citation():
    llm = _mock_llm()
    service = ChatService(llm=llm)
    service.chat(bills=[("Any Bill", "text")], messages=[{"role": "user", "content": "q"}])
    system_arg = llm.complete.call_args[1]["system"]
    assert "section" in system_arg.lower() or "cite" in system_arg.lower()
