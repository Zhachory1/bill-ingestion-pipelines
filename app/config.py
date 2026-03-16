from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///:memory:"
    LOG_LEVEL: str = "INFO"
    ETL_BATCH_SIZE: int = 100
    ETL_RATE_LIMIT_DELAY: float = 1.0

    class Config:
        env_file = ".env"


settings = Settings()
