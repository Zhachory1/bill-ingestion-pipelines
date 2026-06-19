"""Application settings loaded from environment variables or a .env file."""

from enum import Enum
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


# Provider-specific default models
DEFAULT_MODELS = {
    LLMProvider.ANTHROPIC: "claude-opus-4-5",
    LLMProvider.OPENAI: "gpt-4o",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "sqlite:///:memory:"

    # Logging / runtime
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"

    # ETL pipeline
    ETL_BATCH_SIZE: int = 100
    ETL_RATE_LIMIT_DELAY: float = 1.0

    # Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # Retrieval
    DEFAULT_RETRIEVAL_STRATEGY: str = "semantic"
    MAX_RESULTS: int = 10

    # LLM
    LLM_PROVIDER: LLMProvider = LLMProvider.ANTHROPIC
    LLM_MODEL: str | None = None
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2000
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Web server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = False

    # Rate limiting (requests per minute per IP)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_SEARCH: str = "20/minute"  # Search is less expensive
    RATE_LIMIT_CHAT: str = "10/minute"    # Chat calls LLM, more expensive
    RATE_LIMIT_FULLTEXT: str = "15/minute"  # External HTTP fetch

    # Input validation limits
    MAX_QUERY_LENGTH: int = 500          # Max search query length
    MAX_MESSAGE_LENGTH: int = 5000       # Max single message content
    MAX_MESSAGE_COUNT: int = 50          # Max conversation history length
    MAX_BILL_TEXT_CHARS: int = 20000     # Max bill context sent to the LLM
    FULLTEXT_CACHE_MAX_ENTRIES: int = 256

    @field_validator("RATE_LIMIT_ENABLED", mode="before")
    @classmethod
    def parse_rate_limit_enabled(cls, v: bool | str) -> bool:
        """Allow RATE_LIMIT_ENABLED=false in env vars."""
        if isinstance(v, str):
            return v.lower() not in ("false", "0", "no", "off")
        return bool(v)

    @field_validator("LLM_MODEL", mode="before")
    @classmethod
    def set_default_model(cls, v: str | None, info) -> str:
        """Use provider-specific default if LLM_MODEL not explicitly set."""
        if v is None or v == "":
            provider = info.data.get("LLM_PROVIDER", LLMProvider.ANTHROPIC)
            # Handle string provider values during validation
            if isinstance(provider, str):
                try:
                    provider = LLMProvider(provider)
                except ValueError:
                    raise ValueError(
                        f"Invalid LLM_PROVIDER: {provider}. "
                        f"Must be one of: {', '.join(p.value for p in LLMProvider)}"
                    )
            return DEFAULT_MODELS[provider]
        return v


settings = Settings()
