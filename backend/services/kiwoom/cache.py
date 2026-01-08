"""
Kiwoom API Data Cache

Multi-tier TTL cache for reducing API calls and improving response time.
Supports:
- L1: In-memory cache (fast, local)
- L2: Redis cache (distributed, optional)

Implements cache invalidation strategy for order-related data.
"""

import asyncio
import json
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
    Kiwoom API 데이터 캐시 (Multi-Tier)

    Rate Limit (초당 5건) 대응 및 응답 속도 향상을 위한 멀티티어 캐시.
    - L1: 인메모리 캐시 (빠른 접근)
    - L2: Redis 캐시 (분산 캐시, 선택적)

    주문 API 호출 시 계좌 관련 캐시가 자동으로 무효화됩니다.

    Usage:
        cache = KiwoomCache()
        await cache.initialize_redis()  # Optional: Redis 연결

        # 캐시에 저장
        await cache.set_async("stock_info:005930", stock_info, ttl=3.0)

        # 캐시에서 조회
        cached = await cache.get_async("stock_info:005930")
        if cached is not None:
            return cached

        # 계좌 관련 캐시 무효화 (주문 후)
        await cache.invalidate_account_cache_async()
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
        "stock_list": 86400.0,  # 종목 리스트: 24시간
    }

    # L2 Redis TTL 배수 (L1 TTL × REDIS_TTL_MULTIPLIER)
    REDIS_TTL_MULTIPLIER = 10

    # 계좌 관련 캐시 키 프리픽스 (주문 시 무효화 대상)
    ACCOUNT_CACHE_PREFIXES = [
        "cash_balance",
        "account_balance",
        "pending_orders",
        "filled_orders",
    ]

    # Redis 캐시 대상 (장기 TTL 데이터)
    REDIS_CACHE_PREFIXES = [
        "stock_info",
        "daily_chart",
        "stock_list",
    ]

    def __init__(self, max_size: int = 1000, enabled: bool = True, redis_url: Optional[str] = None):
        """
        캐시 초기화

        Args:
            max_size: 최대 캐시 엔트리 수 (L1)
            enabled: 캐시 활성화 여부
            redis_url: Redis 연결 URL (None이면 L2 비활성화)
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._enabled = enabled

        # L2 Redis
        self._redis = None
        self._redis_url = redis_url
        self._redis_available = False
        self._redis_prefix = "kiwoom"

        # 통계
        self._hits = 0
        self._misses = 0
        self._l2_hits = 0
        self._l2_misses = 0
        self._invalidations = 0

        logger.info(
            "kiwoom_cache_initialized",
            max_size=max_size,
            enabled=enabled,
            redis_url=bool(redis_url),
        )

    async def initialize_redis(self, redis_url: Optional[str] = None) -> bool:
        """
        Redis L2 캐시 초기화

        Args:
            redis_url: Redis 연결 URL

        Returns:
            연결 성공 여부
        """
        url = redis_url or self._redis_url
        if not url:
            return False

        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(url, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("kiwoom_redis_cache_connected", url=url)
            return True
        except ImportError:
            logger.warning("redis_package_not_installed")
            return False
        except Exception as e:
            logger.warning("kiwoom_redis_connection_failed", error=str(e))
            return False

    async def close_redis(self) -> None:
        """Redis 연결 종료"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._redis_available = False

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

    # -------------------------------------------
    # Async Multi-Tier Methods (L1 + L2)
    # -------------------------------------------

    async def get_async(self, key: str) -> Optional[Any]:
        """
        멀티티어 캐시에서 값 조회 (L1 → L2)

        Args:
            key: 캐시 키

        Returns:
            캐시된 값 또는 None
        """
        if not self._enabled:
            return None

        # L1: 메모리 캐시 확인
        value = self.get(key)
        if value is not None:
            return value

        # L2: Redis 캐시 확인
        if self._redis_available and self._should_use_redis(key):
            try:
                redis_key = f"{self._redis_prefix}:{key}"
                redis_value = await self._redis.get(redis_key)
                if redis_value is not None:
                    # JSON 역직렬화
                    value = json.loads(redis_value)
                    self._l2_hits += 1

                    # L1으로 승격
                    ttl = self._get_default_ttl(key)
                    self.set(key, value, ttl)

                    logger.debug(
                        "kiwoom_cache_l2_hit",
                        key=key,
                    )
                    return value
                else:
                    self._l2_misses += 1
            except Exception as e:
                logger.warning("kiwoom_redis_get_failed", key=key, error=str(e))

        return None

    async def set_async(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """
        멀티티어 캐시에 값 저장 (L1 + L2)

        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초)
        """
        if not self._enabled:
            return

        # TTL 결정
        if ttl is None:
            ttl = self._get_default_ttl(key)

        # L1: 메모리 캐시에 저장
        self.set(key, value, ttl)

        # L2: Redis 캐시에 저장 (장기 데이터만)
        if self._redis_available and self._should_use_redis(key):
            try:
                redis_key = f"{self._redis_prefix}:{key}"
                redis_ttl = int(ttl * self.REDIS_TTL_MULTIPLIER)
                serialized = json.dumps(value, default=str, ensure_ascii=False)
                await self._redis.setex(redis_key, redis_ttl, serialized)

                logger.debug(
                    "kiwoom_cache_l2_set",
                    key=key,
                    ttl=redis_ttl,
                )
            except Exception as e:
                logger.warning("kiwoom_redis_set_failed", key=key, error=str(e))

    async def delete_async(self, key: str) -> bool:
        """
        멀티티어 캐시에서 키 삭제 (L1 + L2)

        Args:
            key: 삭제할 키

        Returns:
            삭제 성공 여부
        """
        deleted = self.delete(key)

        # L2: Redis에서도 삭제
        if self._redis_available:
            try:
                redis_key = f"{self._redis_prefix}:{key}"
                await self._redis.delete(redis_key)
                deleted = True
            except Exception as e:
                logger.warning("kiwoom_redis_delete_failed", key=key, error=str(e))

        return deleted

    async def invalidate_account_cache_async(self) -> int:
        """
        계좌 관련 캐시 무효화 (주문 후 호출) - 비동기 버전

        Returns:
            무효화된 엔트리 수
        """
        # L1 무효화
        invalidated = self.invalidate_account_cache()

        # L2 무효화
        if self._redis_available:
            try:
                for prefix in self.ACCOUNT_CACHE_PREFIXES:
                    pattern = f"{self._redis_prefix}:{prefix}:*"
                    async for key in self._redis.scan_iter(match=pattern):
                        await self._redis.delete(key)
                        invalidated += 1
            except Exception as e:
                logger.warning("kiwoom_redis_invalidate_failed", error=str(e))

        return invalidated

    def _should_use_redis(self, key: str) -> bool:
        """Redis 캐시 대상 여부 확인"""
        return any(key.startswith(prefix) for prefix in self.REDIS_CACHE_PREFIXES)

    # -------------------------------------------
    # Cache Warming (프리페칭)
    # -------------------------------------------

    async def warm_cache(self, keys: list, fetch_func) -> int:
        """
        캐시 워밍 (프리페칭)

        Args:
            keys: 프리페칭할 키 목록
            fetch_func: 데이터 조회 함수 (async callable)

        Returns:
            워밍된 엔트리 수
        """
        warmed = 0
        for key in keys:
            # 이미 캐시에 있으면 스킵
            if await self.get_async(key) is not None:
                continue

            try:
                value = await fetch_func(key)
                if value is not None:
                    await self.set_async(key, value)
                    warmed += 1
            except Exception as e:
                logger.warning("kiwoom_cache_warm_failed", key=key, error=str(e))

        logger.info("kiwoom_cache_warmed", count=warmed, total=len(keys))
        return warmed

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
    def redis_available(self) -> bool:
        """Redis L2 캐시 사용 가능 여부"""
        return self._redis_available

    @property
    def stats(self) -> dict:
        """
        캐시 통계

        Returns:
            통계 딕셔너리
        """
        # L1 통계
        l1_total = self._hits + self._misses
        l1_hit_rate = (self._hits / l1_total * 100) if l1_total > 0 else 0.0

        # L2 통계
        l2_total = self._l2_hits + self._l2_misses
        l2_hit_rate = (self._l2_hits / l2_total * 100) if l2_total > 0 else 0.0

        # 전체 통계
        total_hits = self._hits + self._l2_hits
        total_requests = l1_total
        overall_hit_rate = (total_hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "enabled": self._enabled,
            "l1": {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{l1_hit_rate:.1f}%",
            },
            "l2": {
                "available": self._redis_available,
                "hits": self._l2_hits,
                "misses": self._l2_misses,
                "hit_rate": f"{l2_hit_rate:.1f}%",
            },
            "overall": {
                "hit_rate": f"{overall_hit_rate:.1f}%",
                "total_hits": total_hits,
            },
            "invalidations": self._invalidations,
        }

    def reset_stats(self) -> None:
        """통계 초기화"""
        self._hits = 0
        self._misses = 0
        self._l2_hits = 0
        self._l2_misses = 0
        self._invalidations = 0

    async def clear_async(self) -> int:
        """
        모든 캐시 삭제 (L1 + L2)

        Returns:
            삭제된 엔트리 수
        """
        # L1 삭제
        count = self.clear()

        # L2 삭제
        if self._redis_available:
            try:
                pattern = f"{self._redis_prefix}:*"
                async for key in self._redis.scan_iter(match=pattern):
                    await self._redis.delete(key)
                    count += 1
            except Exception as e:
                logger.warning("kiwoom_redis_clear_failed", error=str(e))

        return count


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
