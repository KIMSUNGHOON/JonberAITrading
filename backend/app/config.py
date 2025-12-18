"""
Application Configuration
Loads settings from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # -------------------------------------------
    # Environment
    # -------------------------------------------
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True

    # -------------------------------------------
    # LLM Configuration
    # -------------------------------------------
    LLM_PROVIDER: Literal["vllm", "ollama"] = "vllm"
    LLM_BASE_URL: str = "http://localhost:8080/v1"
    LLM_MODEL: str = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
    LLM_TEMPERATURE: float = Field(default=0.7, ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=4096, ge=1, le=32768)
    LLM_TIMEOUT: int = Field(default=120, ge=10, le=600)

    # -------------------------------------------
    # Market Data Configuration
    # -------------------------------------------
    MARKET_DATA_MODE: Literal["live", "mock"] = "live"

    # -------------------------------------------
    # Redis Configuration (State Persistence)
    # -------------------------------------------
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = Field(default=0, ge=0, le=15)

    # -------------------------------------------
    # API Server Configuration
    # -------------------------------------------
    API_HOST: str = "0.0.0.0"
    API_PORT: int = Field(default=8000, ge=1, le=65535)

    # -------------------------------------------
    # CORS Configuration
    # -------------------------------------------
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT == "production"

    @property
    def llm_api_key(self) -> str:
        """
        Return API key for LLM provider.
        Local providers (vLLM, Ollama) don't require API keys.
        """
        return "not-needed-for-local"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Settings are loaded once and cached for performance.
    """
    return Settings()


# Convenience alias for direct import
settings = get_settings()
