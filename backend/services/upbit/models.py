"""
Upbit API Response Models

Pydantic models for type-safe Upbit API responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# -------------------------------------------
# Market Data Models (QUOTATION API)
# -------------------------------------------


class Market(BaseModel):
    """Market information."""

    market: str = Field(..., description="마켓 코드 (예: KRW-BTC)")
    korean_name: str = Field(..., description="한글명")
    english_name: str = Field(..., description="영문명")
    market_warning: Optional[str] = Field(
        default=None, description="유의 종목 여부 (CAUTION)"
    )


class Ticker(BaseModel):
    """Current ticker information."""

    market: str = Field(..., description="마켓 코드")
    trade_date: str = Field(..., description="최근 거래 일자 (UTC)")
    trade_time: str = Field(..., description="최근 거래 시각 (UTC)")
    trade_timestamp: int = Field(..., description="최근 거래 타임스탬프")
    opening_price: float = Field(..., description="시가")
    high_price: float = Field(..., description="고가")
    low_price: float = Field(..., description="저가")
    trade_price: float = Field(..., description="현재가")
    prev_closing_price: float = Field(..., description="전일 종가")
    change: str = Field(..., description="RISE, EVEN, FALL")
    change_price: float = Field(..., description="변화액")
    change_rate: float = Field(..., description="변화율")
    signed_change_price: float = Field(..., description="부호가 있는 변화액")
    signed_change_rate: float = Field(..., description="부호가 있는 변화율")
    trade_volume: float = Field(..., description="가장 최근 거래량")
    acc_trade_price: float = Field(..., description="누적 거래대금 (UTC 0시 기준)")
    acc_trade_price_24h: float = Field(..., description="24시간 누적 거래대금")
    acc_trade_volume: float = Field(..., description="누적 거래량 (UTC 0시 기준)")
    acc_trade_volume_24h: float = Field(..., description="24시간 누적 거래량")
    highest_52_week_price: float = Field(..., description="52주 최고가")
    highest_52_week_date: str = Field(..., description="52주 최고가 달성일")
    lowest_52_week_price: float = Field(..., description="52주 최저가")
    lowest_52_week_date: str = Field(..., description="52주 최저가 달성일")
    timestamp: int = Field(..., description="타임스탬프")


class Candle(BaseModel):
    """Candlestick data."""

    market: str = Field(..., description="마켓 코드")
    candle_date_time_utc: str = Field(..., description="캔들 기준 시각 (UTC)")
    candle_date_time_kst: str = Field(..., description="캔들 기준 시각 (KST)")
    opening_price: float = Field(..., description="시가")
    high_price: float = Field(..., description="고가")
    low_price: float = Field(..., description="저가")
    trade_price: float = Field(..., description="종가")
    timestamp: int = Field(..., description="마지막 틱이 저장된 시각")
    candle_acc_trade_price: float = Field(..., description="누적 거래 금액")
    candle_acc_trade_volume: float = Field(..., description="누적 거래량")


class MinuteCandle(Candle):
    """Minute candlestick data."""

    unit: int = Field(..., description="분 단위")


class DayCandle(Candle):
    """Daily candlestick data."""

    prev_closing_price: Optional[float] = Field(None, description="전일 종가")
    change_price: Optional[float] = Field(None, description="전일 대비 값")
    change_rate: Optional[float] = Field(None, description="전일 대비 등락률")
    converted_trade_price: Optional[float] = Field(
        None, description="종가 환산 화폐 단위"
    )


class OrderbookUnit(BaseModel):
    """Individual orderbook entry."""

    ask_price: float = Field(..., description="매도호가")
    bid_price: float = Field(..., description="매수호가")
    ask_size: float = Field(..., description="매도 잔량")
    bid_size: float = Field(..., description="매수 잔량")


class Orderbook(BaseModel):
    """Orderbook data."""

    market: str = Field(..., description="마켓 코드")
    timestamp: int = Field(..., description="호가 생성 시각")
    total_ask_size: float = Field(..., description="호가 매도 총 잔량")
    total_bid_size: float = Field(..., description="호가 매수 총 잔량")
    orderbook_units: list[OrderbookUnit] = Field(..., description="호가 리스트")


class Trade(BaseModel):
    """Recent trade/tick data."""

    market: str = Field(..., description="마켓 코드")
    trade_date_utc: str = Field(..., description="체결 일자 (UTC)")
    trade_time_utc: str = Field(..., description="체결 시각 (UTC)")
    timestamp: int = Field(..., description="체결 타임스탬프")
    trade_price: float = Field(..., description="체결 가격")
    trade_volume: float = Field(..., description="체결량")
    prev_closing_price: float = Field(..., description="전일 종가")
    change_price: float = Field(..., description="변화량")
    ask_bid: str = Field(..., description="매도/매수 (ASK, BID)")
    sequential_id: int = Field(..., description="체결 번호 (고유 ID)")


# -------------------------------------------
# Account & Order Models (EXCHANGE API)
# -------------------------------------------


class Account(BaseModel):
    """Account balance information."""

    currency: str = Field(..., description="화폐 코드")
    balance: str = Field(..., description="주문 가능 수량")
    locked: str = Field(..., description="주문 중 묶여있는 수량")
    avg_buy_price: str = Field(..., description="매수 평균가")
    avg_buy_price_modified: bool = Field(..., description="매수 평균가 수정 여부")
    unit_currency: str = Field(..., description="평단가 기준 화폐")


class OrderChance(BaseModel):
    """Order chance (constraints) information."""

    bid_fee: str = Field(..., description="매수 수수료 비율")
    ask_fee: str = Field(..., description="매도 수수료 비율")
    market: dict = Field(..., description="마켓 정보")
    bid_account: dict = Field(..., description="매수 계좌")
    ask_account: dict = Field(..., description="매도 계좌")


class Order(BaseModel):
    """Order information."""

    uuid: str = Field(..., description="주문 고유 ID")
    side: str = Field(..., description="주문 종류 (bid, ask)")
    ord_type: str = Field(..., description="주문 방식 (limit, price, market)")
    price: Optional[str] = Field(None, description="주문 당시 가격")
    state: str = Field(..., description="주문 상태")
    market: str = Field(..., description="마켓 코드")
    created_at: str = Field(..., description="주문 생성 시간")
    volume: Optional[str] = Field(None, description="사용자가 입력한 주문 양")
    remaining_volume: Optional[str] = Field(None, description="체결 후 남은 주문 양")
    reserved_fee: str = Field(..., description="수수료로 예약된 비용")
    remaining_fee: str = Field(..., description="남은 수수료")
    paid_fee: str = Field(..., description="사용된 수수료")
    locked: str = Field(..., description="거래에 사용 중인 비용")
    executed_volume: str = Field(..., description="체결된 양")
    trades_count: int = Field(..., description="해당 주문에 걸린 체결 수")


# -------------------------------------------
# Analysis Models
# -------------------------------------------


class CoinAnalysisData(BaseModel):
    """Aggregated coin analysis data for AI agents."""

    market: str
    korean_name: str
    english_name: str

    # Current price info
    current_price: float
    change_rate_24h: float
    change_price_24h: float

    # Volume
    volume_24h: float
    trade_value_24h: float

    # Price range
    high_24h: float
    low_24h: float
    high_52w: float
    low_52w: float

    # Orderbook summary
    bid_ask_ratio: float  # bid_size / ask_size
    total_bid_size: float
    total_ask_size: float

    # Candles (recent OHLCV)
    candles: list[dict]

    # Recent trades
    recent_trades: list[dict]
