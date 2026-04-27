from unittest.mock import patch, MagicMock
from app.chat.llm import AnthropicClient, OpenAIClient, get_llm_client
from app.config import settings


def test_anthropic_client_calls_messages_create():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="Bills address taxation.")]
    with patch("app.chat.llm.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_resp
        client = AnthropicClient()
        result = client.complete(
            system="You are a legislative analyst.",
            messages=[{"role": "user", "content": "What is this about?"}],
        )
    assert result == "Bills address taxation."
    MockAnthropic.return_value.messages.create.assert_called_once()


def test_anthropic_client_passes_system_and_messages():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="reply")]
    with patch("app.chat.llm.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_resp
        client = AnthropicClient()
        client.complete(
            system="sys prompt",
            messages=[{"role": "user", "content": "q"}],
        )
    call_kwargs = MockAnthropic.return_value.messages.create.call_args[1]
    assert call_kwargs["system"] == "sys prompt"
    assert call_kwargs["messages"] == [{"role": "user", "content": "q"}]


def test_openai_client_calls_chat_completions():
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI reply"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    with patch("app.chat.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
        client = OpenAIClient()
        result = client.complete(
            system="sys",
            messages=[{"role": "user", "content": "q"}],
        )
    assert result == "OpenAI reply"


def test_openai_client_prepends_system_message():
    mock_choice = MagicMock()
    mock_choice.message.content = "reply"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    with patch("app.chat.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
        client = OpenAIClient()
        client.complete(system="sys", messages=[{"role": "user", "content": "q"}])
    call_kwargs = MockOpenAI.return_value.chat.completions.create.call_args[1]
    msgs = call_kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "q"}


def test_get_llm_client_returns_anthropic_by_default():
    with patch.object(settings, "LLM_PROVIDER", "anthropic"):
        client = get_llm_client()
    assert isinstance(client, AnthropicClient)


def test_get_llm_client_returns_openai():
    with patch.object(settings, "LLM_PROVIDER", "openai"):
        client = get_llm_client()
    assert isinstance(client, OpenAIClient)
