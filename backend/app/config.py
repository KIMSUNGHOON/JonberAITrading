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
    # DeepSeek-R1 recommended: temperature 0.5-0.7 (0.6 optimal)
    # -------------------------------------------
    LLM_PROVIDER: Literal["vllm", "ollama"] = "ollama"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "deepseek-r1:14b"
    LLM_TEMPERATURE: float = Field(default=0.6, ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=4096, ge=1, le=32768)
    LLM_TIMEOUT: int = Field(default=300, ge=10, le=600)  # Increased for complex LLM analysis

    # -------------------------------------------
    # Market Data Configuration
    # -------------------------------------------
    MARKET_DATA_MODE: Literal["live", "mock"] = "live"

    # -------------------------------------------
    # Storage Configuration (SQLite - no server required)
    # -------------------------------------------
    STORAGE_DB_PATH: str = "data/storage.db"

    # -------------------------------------------
    # Upbit API Configuration (Cryptocurrency)
    # -------------------------------------------
    UPBIT_ACCESS_KEY: str | None = None
    UPBIT_SECRET_KEY: str | None = None
    UPBIT_TRADING_MODE: Literal["paper", "live"] = "paper"

    # -------------------------------------------
    # Kiwoom REST API Configuration (Korean Stocks)
    # -------------------------------------------
    KIWOOM_APP_KEY: str | None = None
    KIWOOM_SECRET_KEY: str | None = None
    KIWOOM_ACCOUNT_NO: str | None = None
    KIWOOM_IS_MOCK: bool = True  # True: 모의투자, False: 실거래

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

    @property
    def kiwoom_base_url(self) -> str:
        """
        Kiwoom API Base URL.
        Returns mock URL for paper trading, live URL for real trading.

        Note: 모의투자(mockapi)는 KRX(한국거래소) 종목만 지원합니다.
              NXT(대체거래소), SOR(스마트오더라우팅)는 실서버에서만 사용 가능합니다.
        """
        return (
            "https://mockapi.kiwoom.com"  # KRX만 지원
            if self.KIWOOM_IS_MOCK
            else "https://api.kiwoom.com"  # KRX, NXT, SOR 모두 지원
        )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Settings are loaded once and cached for performance.
    """
    return Settings()


# Convenience alias for direct import
settings = get_settings()
