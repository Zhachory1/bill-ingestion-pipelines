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
