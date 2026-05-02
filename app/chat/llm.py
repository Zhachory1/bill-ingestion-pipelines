"""LLM client abstraction: Anthropic and OpenAI backends behind a common interface."""

from abc import ABC, abstractmethod
from anthropic import Anthropic
from openai import OpenAI
from app.config import settings


class LLMClient(ABC):
    """Common interface for LLM backends."""

    @abstractmethod
    def complete(self, system: str, messages: list[dict]) -> str: ...


class AnthropicClient(LLMClient):
    """Anthropic Claude backend. System prompt passed as top-level param."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = Anthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    def complete(self, system: str, messages: list[dict]) -> str:
        resp = self._client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return resp.content[0].text  # type: ignore[union-attr]


class OpenAIClient(LLMClient):
    """OpenAI ChatGPT backend. System prompt prepended as a system message."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = OpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    def complete(self, system: str, messages: list[dict]) -> str:
        all_messages = [{"role": "system", "content": system}] + messages
        resp = self._client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            messages=all_messages,
        )
        return resp.choices[0].message.content or ""


def get_llm_client(api_key: str | None = None) -> LLMClient:
    """Return configured LLM client. api_key overrides the server .env key."""
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient(api_key=api_key)
    return OpenAIClient(api_key=api_key)
