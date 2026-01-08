"""
Trading Strategy Module

Provides strategy configuration, presets, and the strategy engine
for making trading decisions based on analysis results.
"""

import json
import logging
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# -------------------------------------------
# Enums
# -------------------------------------------

class RiskTolerance(str, Enum):
    """Risk tolerance levels"""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class TradingStyle(str, Enum):
    """Trading style types"""
    VALUE = "value"           # 가치투자
    GROWTH = "growth"         # 성장주 투자
    MOMENTUM = "momentum"     # 모멘텀 투자
    SWING = "swing"           # 스윙 트레이딩
    POSITION = "position"     # 포지션 트레이딩
    DIVIDEND = "dividend"     # 배당 투자


class StrategyPreset(str, Enum):
    """Pre-defined strategy presets"""
    CONSERVATIVE_INCOME = "conservative_income"
    GROWTH_MOMENTUM = "growth_momentum"
    TECHNICAL_BREAKOUT = "technical_breakout"
    VALUE_INVESTING = "value_investing"
    CUSTOM = "custom"


# -------------------------------------------
# Models
# -------------------------------------------

class EntryConditions(BaseModel):
    """Conditions for entering a position"""
    min_technical_score: int = Field(default=50, ge=0, le=100)
    min_fundamental_score: int = Field(default=50, ge=0, le=100)
    min_sentiment_score: int = Field(default=40, ge=0, le=100)
    max_risk_score: int = Field(default=70, ge=0, le=100)

    # Technical indicators
    rsi_oversold: int = Field(default=30, ge=0, le=100)  # Buy when RSI below this
    rsi_overbought: int = Field(default=70, ge=0, le=100)  # Sell when RSI above this
    require_uptrend: bool = Field(default=False)
    require_volume_increase: bool = Field(default=False)

    # Market conditions
    avoid_high_volatility: bool = Field(default=True)
    prefer_dividend: bool = Field(default=False)


class ExitConditions(BaseModel):
    """Conditions for exiting a position"""
    stop_loss_pct: float = Field(default=0.07, ge=0.01, le=0.50)  # 7% default
    take_profit_pct: float = Field(default=0.15, ge=0.01, le=1.0)  # 15% default
    trailing_stop_enabled: bool = Field(default=False)
    trailing_stop_pct: float = Field(default=0.05, ge=0.01, le=0.30)

    # Time-based exits
    max_holding_days: Optional[int] = Field(default=None, ge=1)

    # News-based exits
    exit_on_negative_news: bool = Field(default=True)
    news_sentiment_threshold: int = Field(default=-50, ge=-100, le=0)


class PositionSizingRules(BaseModel):
    """Rules for position sizing"""
    max_position_pct: float = Field(default=0.10, ge=0.01, le=0.50)  # Max 10% per position
    min_position_pct: float = Field(default=0.02, ge=0.01, le=0.20)  # Min 2% per position
    min_cash_ratio: float = Field(default=0.20, ge=0.0, le=0.90)  # Keep 20% cash
    max_total_stock_pct: float = Field(default=0.80, ge=0.10, le=1.0)  # Max 80% in stocks

    # Risk-adjusted sizing
    adjust_by_risk_score: bool = Field(default=True)
    risk_adjustment_factor: float = Field(default=0.5, ge=0.1, le=1.0)

    # Diversification
    max_sector_concentration: float = Field(default=0.30, ge=0.10, le=1.0)
    max_positions: int = Field(default=10, ge=1, le=50)


class TradingStrategy(BaseModel):
    """Complete trading strategy configuration"""
    id: str = Field(default_factory=lambda: f"strategy_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    name: str = Field(default="My Strategy")
    description: str = Field(default="")

    # Preset or custom
    preset: StrategyPreset = Field(default=StrategyPreset.CUSTOM)

    # User preferences
    risk_tolerance: RiskTolerance = Field(default=RiskTolerance.MODERATE)
    trading_style: TradingStyle = Field(default=TradingStyle.POSITION)

    # System prompt (natural language instructions)
    system_prompt: str = Field(default="")

    # Detailed rules
    entry_conditions: EntryConditions = Field(default_factory=EntryConditions)
    exit_conditions: ExitConditions = Field(default_factory=ExitConditions)
    position_sizing: PositionSizingRules = Field(default_factory=PositionSizingRules)

    # Custom instructions for LLM
    custom_instructions: str = Field(default="")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = Field(default=True)


class EntryDecision(BaseModel):
    """Decision for entering a position"""
    action: str  # BUY, SELL, HOLD, SKIP
    confidence: int = Field(ge=0, le=100)
    entry_price: Optional[float] = None
    position_size_pct: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    rationale: str = ""
    key_factors: List[str] = Field(default_factory=list)
    strategy_alignment: int = Field(default=0, ge=0, le=100)  # How well it fits the strategy


class ExitDecision(BaseModel):
    """Decision for exiting a position"""
    action: str  # HOLD, STOP_LOSS, TAKE_PROFIT, STRATEGIC_EXIT, EMERGENCY_EXIT
    urgency: str = "normal"  # normal, high, critical
    reason: str = ""
    recommended_price: Optional[float] = None
    partial_exit_pct: Optional[float] = None  # For partial exits


# -------------------------------------------
# Strategy Presets
# -------------------------------------------

STRATEGY_PRESETS: Dict[StrategyPreset, TradingStrategy] = {
    StrategyPreset.CONSERVATIVE_INCOME: TradingStrategy(
        name="안정적 배당투자",
        description="안정적인 배당 수익을 추구하는 보수적 전략. 저위험 우량주 중심.",
        preset=StrategyPreset.CONSERVATIVE_INCOME,
        risk_tolerance=RiskTolerance.CONSERVATIVE,
        trading_style=TradingStyle.DIVIDEND,
        system_prompt="""당신은 보수적인 배당 투자 전략을 따르는 투자 에이전트입니다.

주요 원칙:
1. 안정적인 배당 수익이 있는 우량주를 선호합니다
2. 변동성이 높은 종목은 피합니다
3. 손실 최소화를 최우선으로 합니다
4. 장기 보유를 전제로 투자합니다
5. 급등주나 테마주는 투자 대상에서 제외합니다

투자 판단 시 고려사항:
- PER, PBR이 적정 수준인가
- 배당 수익률이 안정적인가
- 부채비율이 낮은가
- 영업이익이 꾸준한가""",
        entry_conditions=EntryConditions(
            min_technical_score=45,
            min_fundamental_score=70,
            min_sentiment_score=40,
            max_risk_score=40,
            prefer_dividend=True,
            avoid_high_volatility=True,
        ),
        exit_conditions=ExitConditions(
            stop_loss_pct=0.05,
            take_profit_pct=0.15,
            exit_on_negative_news=True,
        ),
        position_sizing=PositionSizingRules(
            max_position_pct=0.10,
            min_cash_ratio=0.30,
            max_total_stock_pct=0.70,
            adjust_by_risk_score=True,
        ),
    ),

    StrategyPreset.GROWTH_MOMENTUM: TradingStrategy(
        name="성장 모멘텀",
        description="고성장 종목의 상승 추세에 편승하는 적극적 전략.",
        preset=StrategyPreset.GROWTH_MOMENTUM,
        risk_tolerance=RiskTolerance.AGGRESSIVE,
        trading_style=TradingStyle.MOMENTUM,
        system_prompt="""당신은 성장 모멘텀 전략을 따르는 적극적인 투자 에이전트입니다.

주요 원칙:
1. 강한 상승 추세에 있는 성장주를 찾습니다
2. 거래량 증가와 함께 상승하는 종목을 선호합니다
3. 빠른 손절과 이익 실현을 중시합니다
4. 시장 심리와 뉴스에 민감하게 반응합니다
5. 기술적 지표를 적극 활용합니다

투자 판단 시 고려사항:
- 최근 거래량이 평균 대비 증가했는가
- 이동평균선 배열이 정배열인가
- RSI가 과매수 구간이 아닌가
- 실적 성장률이 높은가
- 긍정적 뉴스나 모멘텀이 있는가""",
        entry_conditions=EntryConditions(
            min_technical_score=65,
            min_fundamental_score=50,
            min_sentiment_score=55,
            max_risk_score=65,
            require_uptrend=True,
            require_volume_increase=True,
        ),
        exit_conditions=ExitConditions(
            stop_loss_pct=0.08,
            take_profit_pct=0.25,
            trailing_stop_enabled=True,
            trailing_stop_pct=0.06,
        ),
        position_sizing=PositionSizingRules(
            max_position_pct=0.15,
            min_cash_ratio=0.20,
            max_total_stock_pct=0.80,
        ),
    ),

    StrategyPreset.TECHNICAL_BREAKOUT: TradingStrategy(
        name="기술적 돌파",
        description="기술적 분석 기반 돌파 매매 전략. 저항선 돌파 시 진입.",
        preset=StrategyPreset.TECHNICAL_BREAKOUT,
        risk_tolerance=RiskTolerance.MODERATE,
        trading_style=TradingStyle.SWING,
        system_prompt="""당신은 기술적 분석 기반 돌파 매매 전략을 따르는 투자 에이전트입니다.

주요 원칙:
1. 주요 저항선/지지선 돌파 시점을 포착합니다
2. 거래량 동반 돌파를 확인합니다
3. RSI, MACD 등 보조지표로 확인합니다
4. 가짜 돌파(false breakout)를 피합니다
5. 명확한 손절라인을 설정합니다

투자 판단 시 고려사항:
- 주요 저항선을 거래량과 함께 돌파했는가
- MACD 골든크로스/데드크로스 확인
- RSI가 극단적 구간이 아닌가 (30-70 사이 선호)
- 볼린저 밴드 상단 돌파 여부
- 이전 고점 대비 위치""",
        entry_conditions=EntryConditions(
            min_technical_score=70,
            min_fundamental_score=40,
            min_sentiment_score=45,
            max_risk_score=60,
            rsi_oversold=30,
            rsi_overbought=70,
        ),
        exit_conditions=ExitConditions(
            stop_loss_pct=0.06,
            take_profit_pct=0.20,
            trailing_stop_enabled=True,
            trailing_stop_pct=0.05,
        ),
        position_sizing=PositionSizingRules(
            max_position_pct=0.12,
            min_cash_ratio=0.25,
        ),
    ),

    StrategyPreset.VALUE_INVESTING: TradingStrategy(
        name="가치 투자",
        description="저평가된 우량주를 발굴하여 장기 투자하는 전략.",
        preset=StrategyPreset.VALUE_INVESTING,
        risk_tolerance=RiskTolerance.MODERATE,
        trading_style=TradingStyle.VALUE,
        system_prompt="""당신은 벤저민 그레이엄 스타일의 가치 투자 전략을 따르는 투자 에이전트입니다.

주요 원칙:
1. 내재가치 대비 저평가된 종목을 찾습니다
2. 안전마진(Margin of Safety)을 중시합니다
3. 재무제표 분석을 철저히 합니다
4. 단기 시세 변동에 흔들리지 않습니다
5. 인내심을 가지고 장기 투자합니다

투자 판단 시 고려사항:
- PER이 업종 평균 대비 낮은가
- PBR이 1 이하인가 (자산가치 대비 저평가)
- ROE가 꾸준히 높은가
- 부채비율이 적정한가
- 영업이익률이 안정적인가
- 현금흐름이 양호한가""",
        entry_conditions=EntryConditions(
            min_technical_score=40,
            min_fundamental_score=75,
            min_sentiment_score=35,
            max_risk_score=50,
            avoid_high_volatility=True,
        ),
        exit_conditions=ExitConditions(
            stop_loss_pct=0.10,
            take_profit_pct=0.30,
            max_holding_days=365,
        ),
        position_sizing=PositionSizingRules(
            max_position_pct=0.15,
            min_cash_ratio=0.25,
            max_positions=8,
        ),
    ),
}


def get_strategy_preset(preset: StrategyPreset) -> TradingStrategy:
    """Get a strategy preset by name"""
    if preset == StrategyPreset.CUSTOM:
        return TradingStrategy(preset=StrategyPreset.CUSTOM)
    return STRATEGY_PRESETS.get(preset, TradingStrategy())


def get_all_presets() -> Dict[str, Dict[str, Any]]:
    """Get all strategy presets as dict for API response"""
    result = {}
    for preset_enum, strategy in STRATEGY_PRESETS.items():
        result[preset_enum.value] = {
            "name": strategy.name,
            "description": strategy.description,
            "risk_tolerance": strategy.risk_tolerance.value,
            "trading_style": strategy.trading_style.value,
            "entry_conditions": strategy.entry_conditions.model_dump(),
            "exit_conditions": strategy.exit_conditions.model_dump(),
            "position_sizing": strategy.position_sizing.model_dump(),
        }
    return result
