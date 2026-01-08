"""
Kiwoom API Rate Limiter

Token bucket algorithm implementation for Kiwoom API rate limiting.
Based on Terms of Service Article 11 (API 호출 횟수 제한):
- Query requests: 5 per second
- Order requests: 5 per second
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger()


class RequestType(Enum):
    """API 요청 유형"""
    QUERY = "query"    # 조회 요청 (ka*, kt00001~kt00004)
    ORDER = "order"    # 주문 요청 (kt10000~kt10003)


@dataclass
class RateLimitConfig:
    """Rate Limit 설정"""
    max_requests: int = 5       # 초당 최대 요청 수
    time_window: float = 1.0    # 시간 윈도우 (초)
    min_interval: float = 0.2   # 최소 요청 간격 (초) = 1/5


@dataclass
class TokenBucket:
    """토큰 버킷 구현 with 최소 요청 간격"""
    max_tokens: int
    refill_rate: float  # tokens per second
    min_interval: float = 0.7  # 최소 요청 간격 (초) - 초당 ~1.4건으로 보수적 제한 (Kiwoom Mock API 호환)
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    last_request: float = field(init=False)
    _lock: asyncio.Lock = field(init=False)

    def __post_init__(self):
        self.tokens = float(self.max_tokens)
        self.last_refill = time.monotonic()
        self.last_request = 0.0  # 첫 요청은 즉시 허용
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        토큰 획득 시도

        Args:
            timeout: 대기 최대 시간 (초). None이면 토큰 획득까지 대기

        Returns:
            True if token acquired, False if timeout
        """
        start_time = time.monotonic()

        while True:
            async with self._lock:
                self._refill()
                now = time.monotonic()

                # 최소 간격 체크 (burst 방지)
                time_since_last = now - self.last_request
                if time_since_last < self.min_interval:
                    wait_time = self.min_interval - time_since_last
                elif self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self.last_request = now
                    return True
                else:
                    # 다음 토큰까지 대기 시간 계산
                    wait_time = (1.0 - self.tokens) / self.refill_rate

            # 타임아웃 체크
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed + wait_time > timeout:
                    return False

            # 대기
            await asyncio.sleep(min(wait_time, 0.1))

    def _refill(self):
        """토큰 리필"""
        now = time.monotonic()
        elapsed = now - self.last_refill

        # 경과 시간에 비례하여 토큰 추가
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
        self.last_refill = now

    @property
    def available_tokens(self) -> float:
        """현재 사용 가능한 토큰 수 (근사값)"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        tokens = self.tokens + (elapsed * self.refill_rate)
        return min(self.max_tokens, tokens)


class KiwoomRateLimiter:
    """
    Kiwoom API Rate Limiter

    이용약관 제11조에 따른 API 호출 횟수 제한:
    - 조회횟수: 초당 5건
    - 주문횟수: 초당 5건

    Usage:
        rate_limiter = KiwoomRateLimiter()

        # 조회 요청 전
        await rate_limiter.acquire(RequestType.QUERY)
        result = await api.get_stock_info("005930")

        # 주문 요청 전
        await rate_limiter.acquire(RequestType.ORDER)
        result = await api.place_buy_order("005930", 1)
    """

    # 기본 설정 (이용약관 기준)
    DEFAULT_QUERY_LIMIT = 5   # 조회 초당 5건
    DEFAULT_ORDER_LIMIT = 5   # 주문 초당 5건

    def __init__(
        self,
        query_limit: int = DEFAULT_QUERY_LIMIT,
        order_limit: int = DEFAULT_ORDER_LIMIT,
    ):
        """
        Rate Limiter 초기화

        Args:
            query_limit: 조회 초당 요청 수 (기본: 5)
            order_limit: 주문 초당 요청 수 (기본: 5)
        """
        self._query_bucket = TokenBucket(
            max_tokens=query_limit,
            refill_rate=float(query_limit),
        )
        self._order_bucket = TokenBucket(
            max_tokens=order_limit,
            refill_rate=float(order_limit),
        )

        # 통계
        self._query_count = 0
        self._order_count = 0
        self._wait_time_total = 0.0

        logger.info(
            "kiwoom_rate_limiter_initialized",
            query_limit=query_limit,
            order_limit=order_limit,
        )

    async def acquire(
        self,
        request_type: RequestType,
        timeout: Optional[float] = 30.0,
    ) -> bool:
        """
        API 요청 전 rate limit 토큰 획득

        Args:
            request_type: 요청 유형 (QUERY or ORDER)
            timeout: 대기 최대 시간 (초)

        Returns:
            True if acquired, False if timeout

        Raises:
            asyncio.TimeoutError: timeout 발생 시 (timeout=None이 아닐 때)
        """
        start_time = time.monotonic()

        bucket = (
            self._query_bucket
            if request_type == RequestType.QUERY
            else self._order_bucket
        )

        acquired = await bucket.acquire(timeout)

        # 통계 업데이트
        elapsed = time.monotonic() - start_time
        self._wait_time_total += elapsed

        if request_type == RequestType.QUERY:
            self._query_count += 1
        else:
            self._order_count += 1

        if elapsed > 0.01:  # 10ms 이상 대기했을 경우만 로그
            logger.debug(
                "kiwoom_rate_limit_wait",
                request_type=request_type.value,
                wait_time=f"{elapsed:.3f}s",
            )

        return acquired

    async def acquire_query(self, timeout: Optional[float] = 30.0) -> bool:
        """조회 요청 토큰 획득 (편의 메서드)"""
        return await self.acquire(RequestType.QUERY, timeout)

    async def acquire_order(self, timeout: Optional[float] = 30.0) -> bool:
        """주문 요청 토큰 획득 (편의 메서드)"""
        return await self.acquire(RequestType.ORDER, timeout)

    @property
    def query_tokens_available(self) -> float:
        """현재 사용 가능한 조회 토큰 수"""
        return self._query_bucket.available_tokens

    @property
    def order_tokens_available(self) -> float:
        """현재 사용 가능한 주문 토큰 수"""
        return self._order_bucket.available_tokens

    @property
    def stats(self) -> dict:
        """Rate limiter 통계"""
        return {
            "query_count": self._query_count,
            "order_count": self._order_count,
            "total_wait_time": f"{self._wait_time_total:.3f}s",
            "query_tokens_available": round(self.query_tokens_available, 2),
            "order_tokens_available": round(self.order_tokens_available, 2),
        }


# API ID별 요청 유형 매핑
API_REQUEST_TYPE_MAP = {
    # 조회 API (QUERY)
    "ka10001": RequestType.QUERY,  # 주식기본정보
    "ka10004": RequestType.QUERY,  # 주식호가
    "ka10081": RequestType.QUERY,  # 일봉차트
    "ka10075": RequestType.QUERY,  # 미체결
    "ka10076": RequestType.QUERY,  # 체결
    "kt00001": RequestType.QUERY,  # 예수금상세
    "kt00004": RequestType.QUERY,  # 계좌평가현황

    # 주문 API (ORDER)
    "kt10000": RequestType.ORDER,  # 매수주문
    "kt10001": RequestType.ORDER,  # 매도주문
    "kt10002": RequestType.ORDER,  # 정정주문
    "kt10003": RequestType.ORDER,  # 취소주문
}


def get_request_type(api_id: str) -> RequestType:
    """
    API ID로 요청 유형 판단

    Args:
        api_id: API ID (예: "ka10001")

    Returns:
        RequestType (QUERY or ORDER)
    """
    # 명시적 매핑 확인
    if api_id in API_REQUEST_TYPE_MAP:
        return API_REQUEST_TYPE_MAP[api_id]

    # kt10xxx는 주문, 나머지는 조회
    if api_id.startswith("kt10"):
        return RequestType.ORDER

    return RequestType.QUERY