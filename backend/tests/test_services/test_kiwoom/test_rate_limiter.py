"""
Kiwoom Rate Limiter Unit Tests

Tests for rate limiting functionality based on Terms of Service Article 11.
"""

import asyncio
import time

import pytest

from services.kiwoom.rate_limiter import (
    KiwoomRateLimiter,
    RequestType,
    TokenBucket,
    get_request_type,
)


class TestTokenBucket:
    """TokenBucket unit tests"""

    @pytest.mark.asyncio
    async def test_bucket_initialization(self):
        """Test bucket initializes with full tokens"""
        bucket = TokenBucket(max_tokens=5, refill_rate=5.0)
        assert bucket.max_tokens == 5
        assert bucket.tokens == 5.0

    @pytest.mark.asyncio
    async def test_acquire_single_token(self):
        """Test acquiring a single token"""
        bucket = TokenBucket(max_tokens=5, refill_rate=5.0)

        result = await bucket.acquire()

        assert result is True
        assert bucket.tokens < 5.0

    @pytest.mark.asyncio
    async def test_acquire_multiple_tokens(self):
        """Test acquiring multiple tokens in sequence"""
        bucket = TokenBucket(max_tokens=5, refill_rate=5.0)

        for _ in range(5):
            result = await bucket.acquire()
            assert result is True

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self):
        """Test that acquire waits when bucket is empty"""
        bucket = TokenBucket(max_tokens=2, refill_rate=10.0)  # Fast refill for testing

        # Exhaust tokens
        await bucket.acquire()
        await bucket.acquire()

        # Next acquire should wait
        start = time.monotonic()
        await bucket.acquire()
        elapsed = time.monotonic() - start

        # Should have waited some time for token refill
        assert elapsed > 0.05  # At least 50ms wait

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        """Test acquire timeout"""
        bucket = TokenBucket(max_tokens=1, refill_rate=0.1)  # Very slow refill

        # Exhaust tokens
        await bucket.acquire()

        # Should timeout
        result = await bucket.acquire(timeout=0.05)

        assert result is False

    @pytest.mark.asyncio
    async def test_token_refill(self):
        """Test tokens refill over time"""
        bucket = TokenBucket(max_tokens=5, refill_rate=50.0)  # Fast refill

        # Exhaust all tokens
        for _ in range(5):
            await bucket.acquire()

        # Wait for refill
        await asyncio.sleep(0.1)

        # Should be able to acquire again
        result = await bucket.acquire(timeout=0.01)
        assert result is True

    def test_available_tokens_property(self):
        """Test available_tokens property"""
        bucket = TokenBucket(max_tokens=5, refill_rate=5.0)

        tokens = bucket.available_tokens

        assert tokens <= 5.0
        assert tokens >= 4.9  # Allow for small timing differences


class TestKiwoomRateLimiter:
    """KiwoomRateLimiter unit tests"""

    def test_initialization(self):
        """Test rate limiter initialization"""
        limiter = KiwoomRateLimiter()

        assert limiter._query_bucket is not None
        assert limiter._order_bucket is not None

    def test_custom_limits(self):
        """Test rate limiter with custom limits"""
        limiter = KiwoomRateLimiter(query_limit=10, order_limit=3)

        assert limiter._query_bucket.max_tokens == 10
        assert limiter._order_bucket.max_tokens == 3

    @pytest.mark.asyncio
    async def test_acquire_query(self):
        """Test acquiring query token"""
        limiter = KiwoomRateLimiter()

        result = await limiter.acquire(RequestType.QUERY)

        assert result is True
        assert limiter._query_count == 1

    @pytest.mark.asyncio
    async def test_acquire_order(self):
        """Test acquiring order token"""
        limiter = KiwoomRateLimiter()

        result = await limiter.acquire(RequestType.ORDER)

        assert result is True
        assert limiter._order_count == 1

    @pytest.mark.asyncio
    async def test_acquire_query_convenience(self):
        """Test acquire_query convenience method"""
        limiter = KiwoomRateLimiter()

        result = await limiter.acquire_query()

        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_order_convenience(self):
        """Test acquire_order convenience method"""
        limiter = KiwoomRateLimiter()

        result = await limiter.acquire_order()

        assert result is True

    @pytest.mark.asyncio
    async def test_query_and_order_independent(self):
        """Test query and order buckets are independent"""
        limiter = KiwoomRateLimiter(query_limit=2, order_limit=2)

        # Exhaust query tokens
        await limiter.acquire_query()
        await limiter.acquire_query()

        # Order tokens should still be available
        result = await limiter.acquire_order(timeout=0.01)

        assert result is True

    @pytest.mark.asyncio
    async def test_stats(self):
        """Test stats property"""
        limiter = KiwoomRateLimiter()

        await limiter.acquire_query()
        await limiter.acquire_query()
        await limiter.acquire_order()

        stats = limiter.stats

        assert stats["query_count"] == 2
        assert stats["order_count"] == 1
        assert "total_wait_time" in stats
        assert "query_tokens_available" in stats
        assert "order_tokens_available" in stats

    @pytest.mark.asyncio
    async def test_rate_limiting_enforced(self):
        """Test that rate limiting is enforced"""
        limiter = KiwoomRateLimiter(query_limit=5, order_limit=5)

        start = time.monotonic()

        # Make 10 requests (should take ~1 second with 5/sec limit)
        for _ in range(10):
            await limiter.acquire_query()

        elapsed = time.monotonic() - start

        # Should have taken at least 0.8 seconds (allowing some margin)
        assert elapsed >= 0.8


class TestGetRequestType:
    """get_request_type function tests"""

    def test_query_api_ids(self):
        """Test query API IDs return QUERY type"""
        query_ids = ["ka10001", "ka10004", "ka10081", "ka10075", "ka10076", "kt00001", "kt00004"]

        for api_id in query_ids:
            result = get_request_type(api_id)
            assert result == RequestType.QUERY, f"Expected QUERY for {api_id}"

    def test_order_api_ids(self):
        """Test order API IDs return ORDER type"""
        order_ids = ["kt10000", "kt10001", "kt10002", "kt10003"]

        for api_id in order_ids:
            result = get_request_type(api_id)
            assert result == RequestType.ORDER, f"Expected ORDER for {api_id}"

    def test_unknown_kt10xxx_is_order(self):
        """Test unknown kt10xxx IDs default to ORDER"""
        result = get_request_type("kt10999")
        assert result == RequestType.ORDER

    def test_unknown_ka_is_query(self):
        """Test unknown ka IDs default to QUERY"""
        result = get_request_type("ka99999")
        assert result == RequestType.QUERY

    def test_unknown_default_to_query(self):
        """Test unknown IDs default to QUERY"""
        result = get_request_type("unknown_api")
        assert result == RequestType.QUERY


class TestRequestType:
    """RequestType enum tests"""

    def test_query_value(self):
        """Test QUERY enum value"""
        assert RequestType.QUERY.value == "query"

    def test_order_value(self):
        """Test ORDER enum value"""
        assert RequestType.ORDER.value == "order"


class TestRateLimiterIntegration:
    """Integration tests for rate limiter"""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test concurrent request handling"""
        limiter = KiwoomRateLimiter(query_limit=5, order_limit=5)

        async def make_request(request_type: RequestType):
            return await limiter.acquire(request_type)

        # Make 5 concurrent query requests
        tasks = [make_request(RequestType.QUERY) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        assert limiter._query_count == 5

    @pytest.mark.asyncio
    async def test_mixed_concurrent_requests(self):
        """Test mixed concurrent query and order requests"""
        limiter = KiwoomRateLimiter(query_limit=3, order_limit=3)

        async def make_query():
            return await limiter.acquire(RequestType.QUERY)

        async def make_order():
            return await limiter.acquire(RequestType.ORDER)

        # Make concurrent mixed requests
        tasks = [
            make_query(),
            make_order(),
            make_query(),
            make_order(),
        ]
        results = await asyncio.gather(*tasks)

        assert all(results)
        assert limiter._query_count == 2
        assert limiter._order_count == 2