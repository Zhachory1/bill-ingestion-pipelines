import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from app.chat.llm import AnthropicClient, OpenAIClient, get_llm_client
from app.config import settings, Settings, LLMProvider


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


def test_get_llm_client_raises_on_invalid_enum():
    """get_llm_client defensive check (should never happen due to validation)."""
    with patch.object(settings, "LLM_PROVIDER", "invalid"):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_client()


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
    with patch.object(settings, "LLM_PROVIDER", LLMProvider.ANTHROPIC):
        client = get_llm_client()
    assert isinstance(client, AnthropicClient)


def test_get_llm_client_returns_openai():
    with patch.object(settings, "LLM_PROVIDER", LLMProvider.OPENAI):
        client = get_llm_client()
    assert isinstance(client, OpenAIClient)


def test_settings_validates_llm_provider_enum():
    """Valid provider string is converted to enum."""
    test_settings = Settings(
        _env_file=None,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="test-key",
    )
    assert test_settings.LLM_PROVIDER == LLMProvider.ANTHROPIC
    assert test_settings.LLM_MODEL == "claude-opus-4-5"


def test_settings_rejects_invalid_provider():
    """Invalid provider raises ValidationError at settings load time."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, LLM_PROVIDER="invalid-provider")
    assert "anthropic" in str(exc_info.value).lower()
    assert "openai" in str(exc_info.value).lower()


def test_settings_uses_anthropic_default_model():
    """Anthropic provider gets claude default when LLM_MODEL not set."""
    test_settings = Settings(
        _env_file=None,
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="test-key",
    )
    assert test_settings.LLM_MODEL == "claude-opus-4-5"


def test_settings_uses_openai_default_model():
    """OpenAI provider gets gpt default when LLM_MODEL not set."""
    test_settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key",
    )
    assert test_settings.LLM_MODEL == "gpt-4o"


def test_settings_respects_explicit_model_override():
    """Explicit LLM_MODEL overrides provider default."""
    test_settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-3.5-turbo",
        OPENAI_API_KEY="test-key",
    )
    assert test_settings.LLM_MODEL == "gpt-3.5-turbo"


def test_settings_allows_custom_anthropic_model():
    """Can use custom Anthropic model."""
    test_settings = Settings(
        _env_file=None,
        LLM_PROVIDER="anthropic",
        LLM_MODEL="claude-sonnet-4-5",
        ANTHROPIC_API_KEY="test-key",
    )
    assert test_settings.LLM_MODEL == "claude-sonnet-4-5"
