"""
Application Configuration
Loads settings from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import Literal

import structlog
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = structlog.get_logger()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",  # .env is in project root, not backend/
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
    # OpenRouter (cloud LLM — the ONLY secret in the intelligence layer)
    # CLIs (claude/codex) are keyless: they authenticate via local subscription OAuth.
    # -------------------------------------------
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "deepseek-v4-flash"
    OPENROUTER_DAILY_BUDGET_USD: float | None = 5.0

    # Local backend (Ollama/vLLM) — retired from default chains; opt-in for Windows GPU.
    LLM_LOCAL_ENABLED: bool = False

    # CLI backends (keyless — auth via local OAuth subscription).
    CLAUDE_CLI_PATH: str = "claude"
    CODEX_CLI_PATH: str = "codex"
    CLAUDE_STRATEGIC_MODEL: str = "opus"
    CLAUDE_FALLBACK_MODEL: str = "sonnet"
    CODEX_MODEL: str | None = None  # None -> codex account default

    # Per-backend concurrency + timeouts (seconds).
    LLM_OPENROUTER_CONCURRENCY: int = 8
    LLM_CLI_CONCURRENCY: int = 2
    LLM_LOCAL_CONCURRENCY: int = 3
    LLM_CLI_TIMEOUT: int = 180
    LLM_CIRCUIT_FAIL_THRESHOLD: int = 3
    LLM_CIRCUIT_COOLDOWN: int = 60

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

    # Per-API-ID minimum interval (seconds) between two requests to the SAME
    # Kiwoom api_id (e.g. ka10001). Kiwoom error 1700 ("허용된 API 요청 개수를
    # 초과") is a PER-API-ID limit — distinct from 1701 (total) and 1702
    # (group), which the existing global QUERY/ORDER buckets already guard.
    # A single hot API (e.g. ka10001, called by RiskMonitor + watch-refresh +
    # agent-chat) can monopolize the shared global budget and still exceed
    # ITS OWN server-side limit even though other APIs sit idle — the global
    # bucket alone cannot protect an individual API. This gate is layered on
    # top of (not a replacement for) the global buckets. See
    # `services/kiwoom/rate_limiter.py::KiwoomRateLimiter`.
    KIWOOM_PER_API_MIN_INTERVAL: float = Field(default=1.0, ge=0)

    # Autonomy master gate (R3). False = trading_mode toggles are inert and
    # every autonomous execution path is denied at the shared gate.
    AUTONOMY_ENABLED: bool = False

    # -------------------------------------------
    # EOD Review / Agent Calibration (Phase2 Task 1)
    # -------------------------------------------
    # A closed decision's realized P&L within this many KRW of zero (either
    # direction) is labeled "flat" rather than correct/incorrect — small
    # noise-level P&L shouldn't count as a directional win or loss for
    # per-agent calibration (services/trading/calibration.py). Config-driven
    # per audit requirement, not a hardcoded literal (mirrors
    # KIWOOM_PER_API_MIN_INTERVAL's single-field pattern above).
    EOD_FLAT_THRESHOLD_KRW: float = Field(default=10000.0, ge=0)

    # Breadth ratio magnitude above which the background scanner's
    # buy/sell/hold distribution for a day is labeled a directional regime
    # ("risk_on"/"risk_off") rather than "neutral" (services/trading/
    # regime.py::compute_regime_snapshot). Config-driven per the same
    # pattern as EOD_FLAT_THRESHOLD_KRW above.
    EOD_REGIME_BREADTH_THRESHOLD: float = Field(default=0.15, ge=0)

    # Phase 5: 시장전체 레짐 심화(지수·수급·시장심리). False면 페처 전부 skip,
    # 레짐 = 순수 breadth(레거시 byte-동일).
    PHASE5_MARKET_DATA_ENABLED: bool = True
    # 복합 시장심리 라벨 경계(EOD_REGIME_BREADTH_THRESHOLD 패턴).
    PHASE5_SENTIMENT_THRESHOLD: float = Field(default=0.1, ge=0)

    # -------------------------------------------
    # Phase3: EOD strategy consensus (strategy_orchestrator.py). ENABLED
    # gates the market-close LLM panel (3 structured calls via the
    # STRATEGIC_DECISION chain); the produced strategy stays dormant until
    # Phase4 wires tactical consumption, so this is analysis-only — but the
    # flag exists to kill the LLM spend without a code change. The timeout
    # bounds how long the close-edge scheduler tick may stall (market is
    # already closed at that point; the next open is the following day).
    STRATEGY_CONSENSUS_ENABLED: bool = True
    STRATEGY_CONSENSUS_TIMEOUT_SECONDS: float = Field(default=420.0, gt=0)
    # Consensus gates (strategy_consensus.aggregate_stance): fewer than
    # MIN_VALID_VOTES valid panelist votes -- or a dominant-stance share
    # below THRESHOLD -- keeps the current strategy (the single-vote=100%
    # agent-chat defect, corrected by construction).
    STRATEGY_MIN_VALID_VOTES: int = Field(default=2, ge=1)
    STRATEGY_CONSENSUS_THRESHOLD: float = Field(default=0.5, ge=0, le=1.0)

    # -------------------------------------------
    # Naver API Configuration (News Search)
    # https://developers.naver.com/apps
    # -------------------------------------------
    NAVER_CLIENT_ID: str | None = None
    NAVER_CLIENT_SECRET: str | None = None

    # -------------------------------------------
    # Redis Configuration (Optional - for caching)
    # -------------------------------------------
    REDIS_URL: str | None = None

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
    instance = Settings()
    return instance


# Convenience alias for direct import
settings = get_settings()


# -------------------------------------------
# Paper Fill Settings (P2-4 fill-realism, Task P1)
# -------------------------------------------


class PaperFillSettings(BaseSettings):
    """Conservative (real-or-higher) round-trip cost assumptions for paper
    trading P&L.

    Background: `docs/superpowers/audits/2026-07-14-paper-fill-realism-audit.md`
    (§C priority 1) found that paper "profit" was structurally overstated
    because round-trip commission/tax/fees were never modeled anywhere.

    DESIGN PRINCIPLE — do not violate elsewhere in the codebase:
    - KR headline returns come from the mock BROKER ledger (kt00004 account
      equity / ka10074 realized P&L), which ALREADY deducts its own
      commission+tax. These KR rates must therefore NEVER be added to the
      KR ledger calculation (`ManagedPosition.unrealized_pnl`,
      `fill_confirm`, coordinator avg_price, `paper_performance`) — that
      would double-count and desync the app from the broker's own numbers.
      They exist ONLY for the KR display-layer cost helper
      (`services/trading/fill_costs.py`), which shows a realistic
      "what would I actually keep if I exited now" number without touching
      the ledger.
    - coin paper trading has NO broker ledger — the app's own SQLite
      storage IS the ledger (see
      `agents/graph/coin_nodes.py::_execute_paper_order`) — so
      `coin_fee_bps` IS simulated directly into the coin cost
      basis/realized P&L there (and into the displayed unrealized P&L in
      `app/api/routes/coin/helpers.py::calculate_position_pnl`).

    Rates deliberately err high rather than trying to be exact (real rates
    vary by year/broker/rebate tier and are not this app's concern) — the
    whole point of this settings group is that paper P&L should never be
    MORE optimistic than reality. Env-overridable with the `PAPER_FILL_`
    prefix, e.g. `PAPER_FILL_COIN_FEE_BPS=10`.
    """

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        env_prefix="PAPER_FILL_",
        case_sensitive=False,
        extra="ignore",
    )

    # KR commission, charged PER SIDE (both entry and exit legs of a round
    # trip). Real KR discount-brokerage commission is usually ~0.015%;
    # kept small but non-zero and slightly above that.
    kr_commission_bps: float = Field(default=2.0, ge=0)

    # KR securities transaction tax, SELL SIDE ONLY. Real KRX rates have
    # been ~0.18-0.23% depending on market/year (KOSDAQ/KOSPI, rural
    # special tax portion) — use the higher end so this never understates
    # the real exit cost.
    kr_sell_tax_bps: float = Field(default=23.0, ge=0)

    # Upbit KRW-market fee is ~0.05% per side. coin paper trading has no
    # broker ledger, so this is simulated directly (see class docstring).
    coin_fee_bps: float = Field(default=5.0, ge=0)

    # Reserved for P2-4 Task P2 (adverse execution-price slippage
    # simulation) — the field exists now so config stays stable across
    # P1/P2; unused by Task P1.
    slippage_bps: float = Field(default=10.0, ge=0)


@lru_cache
def get_paper_fill_settings() -> PaperFillSettings:
    """Get cached PaperFillSettings instance (mirrors get_settings())."""
    return PaperFillSettings()


# Convenience alias for direct import (mirrors `settings` above).
paper_fill_settings = get_paper_fill_settings()
