"""Application settings loaded from environment variables or a .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    CONGRESS_GOV_API_KEY: str = ""
    GOVTRACK_API_KEY: str = ""

    # Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # Retrieval
    DEFAULT_RETRIEVAL_STRATEGY: str = "semantic"
    MAX_RESULTS: int = 10

    # LLM
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-opus-4-5"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2000
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Web server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = False


settings = Settings()
