import pytest

from app.chat import llm
from app.config import settings


def test_anthropic_uses_provider_default_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL", "")

    assert llm.configured_provider() == "anthropic"
    assert llm.configured_model() == "claude-opus-4-5"


def test_openai_uses_provider_default_model(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_MODEL", "")

    assert llm.configured_provider() == "openai"
    assert llm.configured_model() == "gpt-4o-mini"


def test_model_override_wins(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-4.1")

    assert llm.configured_model() == "gpt-4.1"


def test_invalid_provider_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        llm.configured_provider()
