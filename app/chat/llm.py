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
    """Anthropic Claude backend. System prompt passed as top-level param.

    SDK client created once and reused across calls (maintains HTTP connection pool).
    """

    def __init__(self) -> None:
        self._client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def complete(self, system: str, messages: list[dict]) -> str:
        resp = self._client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return resp.content[0].text  # type: ignore[union-attr]


class OpenAIClient(LLMClient):
    """OpenAI ChatGPT backend. System prompt prepended as a system message.

    SDK client created once and reused across calls (maintains HTTP connection pool).
    """

    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def complete(self, system: str, messages: list[dict]) -> str:
        all_messages = [{"role": "system", "content": system}] + messages
        resp = self._client.chat.completions.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            messages=all_messages,
        )
        return resp.choices[0].message.content or ""


def get_llm_client() -> LLMClient:
    """Return configured LLM client based on LLM_PROVIDER setting."""
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient()
    return OpenAIClient()
