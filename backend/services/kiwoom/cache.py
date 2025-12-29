"""
Kiwoom API Data Cache

In-memory TTL cache for reducing API calls and improving response time.
Implements cache invalidation strategy for order-related data.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class CacheEntry:
    """캐시 엔트리"""
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """만료 여부 확인"""
        return time.time() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        """남은 TTL (초)"""
        remaining = self.expires_at - time.time()
        return max(0, remaining)


class KiwoomCache:
    """
    Kiwoom API 데이터 캐시

    Rate Limit (초당 5건) 대응 및 응답 속도 향상을 위한 메모리 캐시.
    주문 API 호출 시 계좌 관련 캐시가 자동으로 무효화됩니다.

    Usage:
        cache = KiwoomCache()

        # 캐시에 저장
        cache.set("stock_info:005930", stock_info, ttl=3.0)

        # 캐시에서 조회
        cached = cache.get("stock_info:005930")
        if cached is not None:
            return cached

        # 계좌 관련 캐시 무효화 (주문 후)
        cache.invalidate_account_cache()
    """

    # 기본 TTL 설정 (초)
    DEFAULT_TTL = {
        "stock_info": 3.0,      # 현재가/시세: 3초
        "orderbook": 2.0,       # 호가: 2초
        "daily_chart": 3600.0,  # 일봉 차트: 1시간
        "cash_balance": 30.0,   # 예수금: 30초
        "account_balance": 30.0, # 계좌 잔고: 30초
        "pending_orders": 5.0,  # 미체결: 5초
        "filled_orders": 5.0,   # 체결 내역: 5초
    }

    # 계좌 관련 캐시 키 프리픽스 (주문 시 무효화 대상)
    ACCOUNT_CACHE_PREFIXES = [
        "cash_balance",
        "account_balance",
        "pending_orders",
        "filled_orders",
    ]

    def __init__(self, max_size: int = 1000, enabled: bool = True):
        """
        캐시 초기화

        Args:
            max_size: 최대 캐시 엔트리 수
            enabled: 캐시 활성화 여부
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._enabled = enabled

        # 통계
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

        logger.info(
            "kiwoom_cache_initialized",
            max_size=max_size,
            enabled=enabled,
        )

    def get(self, key: str) -> Optional[Any]:
        """
        캐시에서 값 조회

        Args:
            key: 캐시 키

        Returns:
            캐시된 값 또는 None (미스 또는 만료)
        """
        if not self._enabled:
            return None

        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            # 만료된 엔트리 삭제
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        logger.debug(
            "kiwoom_cache_hit",
            key=key,
            ttl_remaining=f"{entry.ttl_remaining:.1f}s",
        )
        return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """
        캐시에 값 저장

        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초). None이면 키 타입에 따른 기본값 사용
        """
        if not self._enabled:
            return

        # TTL 결정
        if ttl is None:
            ttl = self._get_default_ttl(key)

        # 캐시 크기 제한 확인
        if len(self._cache) >= self._max_size:
            self._evict_expired()
            # 여전히 초과하면 가장 오래된 것 삭제
            if len(self._cache) >= self._max_size:
                self._evict_oldest()

        entry = CacheEntry(
            value=value,
            expires_at=time.time() + ttl,
        )
        self._cache[key] = entry

        logger.debug(
            "kiwoom_cache_set",
            key=key,
            ttl=f"{ttl:.1f}s",
        )

    def delete(self, key: str) -> bool:
        """
        캐시에서 키 삭제

        Args:
            key: 삭제할 키

        Returns:
            삭제 성공 여부
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_account_cache(self) -> int:
        """
        계좌 관련 캐시 무효화 (주문 후 호출)

        Returns:
            무효화된 엔트리 수
        """
        invalidated = 0

        keys_to_delete = [
            key for key in self._cache
            if any(key.startswith(prefix) for prefix in self.ACCOUNT_CACHE_PREFIXES)
        ]

        for key in keys_to_delete:
            del self._cache[key]
            invalidated += 1

        if invalidated > 0:
            self._invalidations += invalidated
            logger.info(
                "kiwoom_cache_account_invalidated",
                invalidated_count=invalidated,
            )

        return invalidated

    def clear(self) -> int:
        """
        모든 캐시 삭제

        Returns:
            삭제된 엔트리 수
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info("kiwoom_cache_cleared", cleared_count=count)
        return count

    def _get_default_ttl(self, key: str) -> float:
        """키 타입에 따른 기본 TTL 반환"""
        for prefix, ttl in self.DEFAULT_TTL.items():
            if key.startswith(prefix):
                return ttl
        return 60.0  # 기본 60초

    def _evict_expired(self) -> int:
        """만료된 엔트리 삭제"""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def _evict_oldest(self) -> None:
        """가장 오래된 엔트리 삭제 (LRU)"""
        if not self._cache:
            return

        oldest_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].created_at
        )
        del self._cache[oldest_key]

    @property
    def enabled(self) -> bool:
        """캐시 활성화 여부"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """캐시 활성화 설정"""
        self._enabled = value
        if not value:
            self.clear()

    @property
    def size(self) -> int:
        """현재 캐시 엔트리 수"""
        return len(self._cache)

    @property
    def stats(self) -> dict:
        """
        캐시 통계

        Returns:
            통계 딕셔너리
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0

        return {
            "enabled": self._enabled,
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "invalidations": self._invalidations,
        }

    def reset_stats(self) -> None:
        """통계 초기화"""
        self._hits = 0
        self._misses = 0
        self._invalidations = 0


# 캐시 키 생성 헬퍼 함수
def make_cache_key(prefix: str, *args) -> str:
    """
    캐시 키 생성

    Args:
        prefix: 키 프리픽스 (예: "stock_info")
        *args: 추가 파라미터

    Returns:
        캐시 키 문자열

    Example:
        >>> make_cache_key("stock_info", "005930")
        "stock_info:005930"
        >>> make_cache_key("daily_chart", "005930", "20241225")
        "daily_chart:005930:20241225"
    """
    parts = [prefix] + [str(arg) for arg in args if arg is not None]
    return ":".join(parts)
