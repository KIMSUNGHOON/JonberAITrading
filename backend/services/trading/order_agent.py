"""
Order Agent

Handles order execution via Kiwoom API with rate limiting and split orders.

Uses KRX tick size (호가 단위) for proper price rounding.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, List

from .models import (
    OrderRequest,
    OrderResult,
    OrderType,
    OrderSide,
)
from .market_hours import (
    round_to_tick_size,
    is_valid_tick_price,
    get_krx_tick_size,
)

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""
    pass


class OrderExecutionError(Exception):
    """Raised when order execution fails"""
    pass


class KiwoomRateLimiter:
    """
    Rate limiter for Kiwoom API.

    Kiwoom limits:
    - 5 requests per second
    - 100 requests per minute
    """

    RATE_PER_SECOND = 5
    RATE_PER_MINUTE = 100

    def __init__(self, redis_client=None):
        """
        Initialize rate limiter.

        Args:
            redis_client: Optional Redis client for distributed limiting
        """
        self.redis = redis_client
        # In-memory fallback
        self._second_counts: dict = {}
        self._minute_counts: dict = {}

    async def acquire(self) -> bool:
        """
        Try to acquire a rate limit slot.

        Returns:
            True if acquired, False if limit exceeded
        """
        if self.redis:
            return await self._acquire_redis()
        return await self._acquire_memory()

    async def _acquire_redis(self) -> bool:
        """Acquire using Redis for distributed limiting."""
        now = datetime.now()
        second_key = f"kiwoom:rate:{now.strftime('%Y%m%d%H%M%S')}"
        minute_key = f"kiwoom:rate:{now.strftime('%Y%m%d%H%M')}"

        try:
            # Check second limit
            second_count = await self.redis.incr(second_key)
            await self.redis.expire(second_key, 2)

            if second_count > self.RATE_PER_SECOND:
                await self.redis.decr(second_key)
                return False

            # Check minute limit
            minute_count = await self.redis.incr(minute_key)
            await self.redis.expire(minute_key, 120)

            if minute_count > self.RATE_PER_MINUTE:
                await self.redis.decr(minute_key)
                await self.redis.decr(second_key)
                return False

            return True

        except Exception as e:
            logger.warning(f"[RateLimiter] Redis error: {e}, using memory fallback")
            return await self._acquire_memory()

    async def _acquire_memory(self) -> bool:
        """Acquire using in-memory counting."""
        now = datetime.now()
        second_key = now.strftime('%Y%m%d%H%M%S')
        minute_key = now.strftime('%Y%m%d%H%M')

        # Clean old entries
        self._cleanup_old_entries(now)

        # Check second limit
        second_count = self._second_counts.get(second_key, 0)
        if second_count >= self.RATE_PER_SECOND:
            return False

        # Check minute limit
        minute_count = self._minute_counts.get(minute_key, 0)
        if minute_count >= self.RATE_PER_MINUTE:
            return False

        # Increment
        self._second_counts[second_key] = second_count + 1
        self._minute_counts[minute_key] = minute_count + 1

        return True

    def _cleanup_old_entries(self, now: datetime):
        """Remove old rate limit entries."""
        current_second = now.strftime('%Y%m%d%H%M%S')
        current_minute = now.strftime('%Y%m%d%H%M')

        # Keep only current second
        self._second_counts = {
            k: v for k, v in self._second_counts.items()
            if k >= current_second[:12]  # Same minute
        }

        # Keep only current and previous minute
        self._minute_counts = {
            k: v for k, v in self._minute_counts.items()
            if k >= current_minute[:10]  # Same hour
        }

    async def wait_for_slot(self, timeout: float = 30.0) -> bool:
        """
        Wait until a rate limit slot is available.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if slot acquired

        Raises:
            RateLimitExceeded: If timeout reached
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            if await self.acquire():
                return True
            await asyncio.sleep(0.2)

        raise RateLimitExceeded(
            f"Kiwoom rate limit timeout after {timeout}s"
        )


class OrderAgent:
    """
    Order execution agent.

    Responsibilities:
    - Execute orders via Kiwoom API
    - Handle rate limiting
    - Split large orders
    - Track order status
    """

    # Split orders larger than this
    SPLIT_THRESHOLD = 100

    def __init__(
        self,
        kiwoom_client=None,
        rate_limiter: Optional[KiwoomRateLimiter] = None,
    ):
        """
        Initialize Order Agent.

        Args:
            kiwoom_client: Kiwoom API client
            rate_limiter: Rate limiter instance
        """
        self.kiwoom = kiwoom_client
        self.limiter = rate_limiter or KiwoomRateLimiter()

        # Order tracking
        self._pending_orders: dict = {}
        self._completed_orders: dict = {}

    async def execute_order(
        self,
        order: OrderRequest,
        split: bool = True,
    ) -> OrderResult:
        """
        Execute an order.

        Args:
            order: Order to execute
            split: Whether to split large orders

        Returns:
            OrderResult with execution details
        """
        logger.info(
            f"[OrderAgent] Executing order: {order.side.value} "
            f"{order.quantity} {order.ticker} @ {order.price or 'market'}"
        )

        # Determine if we should split
        if split and order.quantity > self.SPLIT_THRESHOLD:
            return await self._execute_split_order(order)

        return await self._execute_single_order(order)

    async def _execute_single_order(
        self,
        order: OrderRequest,
    ) -> OrderResult:
        """Execute a single order."""
        order_id = str(uuid.uuid4())[:8]

        try:
            # Wait for rate limit slot
            await self.limiter.wait_for_slot()

            # Track as pending
            self._pending_orders[order_id] = order

            if self.kiwoom is None:
                # Simulation mode
                result = await self._simulate_order(order_id, order)
            else:
                # Real execution
                result = await self._execute_kiwoom_order(order_id, order)

            # Move to completed
            del self._pending_orders[order_id]
            self._completed_orders[order_id] = result

            logger.info(
                f"[OrderAgent] Order {order_id} completed: "
                f"{result.filled_quantity}/{result.requested_quantity} filled "
                f"@ {result.avg_price}"
            )

            return result

        except RateLimitExceeded as e:
            logger.error(f"[OrderAgent] Rate limit exceeded: {e}")
            return OrderResult(
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                requested_quantity=order.quantity,
                filled_quantity=0,
                status="rejected",
                message=str(e),
            )

        except Exception as e:
            logger.exception(f"[OrderAgent] Order execution failed: {e}")
            return OrderResult(
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                requested_quantity=order.quantity,
                filled_quantity=0,
                status="rejected",
                message=str(e),
            )

    async def _execute_split_order(
        self,
        order: OrderRequest,
        num_splits: int = 3,
    ) -> OrderResult:
        """
        Execute order in multiple splits.

        Helps reduce market impact and get better fills.
        """
        logger.info(
            f"[OrderAgent] Splitting order into {num_splits} parts"
        )

        base_qty = order.quantity // num_splits
        remainder = order.quantity % num_splits

        results: List[OrderResult] = []

        for i in range(num_splits):
            # Last split gets remainder
            qty = base_qty + (remainder if i == num_splits - 1 else 0)

            if qty <= 0:
                continue

            split_order = OrderRequest(
                ticker=order.ticker,
                stock_name=order.stock_name,
                side=order.side,
                quantity=qty,
                price=order.price,
                order_type=order.order_type,
                session_id=order.session_id,
                reason=f"{order.reason} (split {i+1}/{num_splits})",
            )

            result = await self._execute_single_order(split_order)
            results.append(result)

            # Wait between splits (1-2 seconds)
            if i < num_splits - 1:
                await asyncio.sleep(1.5)

        # Aggregate results
        return self._aggregate_results(order, results)

    async def _execute_kiwoom_order(
        self,
        order_id: str,
        order: OrderRequest,
    ) -> OrderResult:
        """Execute order via Kiwoom API."""
        # Map to Kiwoom order type
        order_type_code = "00" if order.order_type == OrderType.LIMIT else "03"
        side_code = "01" if order.side == OrderSide.BUY else "02"

        # Apply tick size rounding for limit orders
        price_to_use = 0
        if order.price and order.order_type == OrderType.LIMIT:
            # Round price to valid tick size
            direction = "up" if order.side == OrderSide.BUY else "down"
            price_to_use = round_to_tick_size(order.price, direction)

            if price_to_use != int(order.price):
                logger.info(
                    f"[OrderAgent] Price adjusted to tick size: "
                    f"{order.price:,.0f} → {price_to_use:,.0f} "
                    f"(tick size: {get_krx_tick_size(order.price)})"
                )

        try:
            response = await self.kiwoom.place_order(
                order_type=side_code,
                stock_code=order.ticker,
                quantity=order.quantity,
                price=price_to_use,
                price_type=order_type_code,
            )

            # Parse response
            if response.get("rt_cd") == "0":
                return OrderResult(
                    order_id=response.get("order_no", order_id),
                    ticker=order.ticker,
                    side=order.side,
                    requested_quantity=order.quantity,
                    filled_quantity=order.quantity,  # Assume filled
                    avg_price=order.price or 0,
                    status="filled",
                    filled_at=datetime.now(),
                )
            else:
                return OrderResult(
                    order_id=order_id,
                    ticker=order.ticker,
                    side=order.side,
                    requested_quantity=order.quantity,
                    filled_quantity=0,
                    status="rejected",
                    message=response.get("msg1", "Unknown error"),
                )

        except Exception as e:
            raise OrderExecutionError(f"Kiwoom API error: {e}")

    async def _simulate_order(
        self,
        order_id: str,
        order: OrderRequest,
    ) -> OrderResult:
        """Simulate order execution for testing."""
        # Simulate network delay
        await asyncio.sleep(0.1)

        # Simulate 95% fill rate
        import random
        if random.random() < 0.95:
            return OrderResult(
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                requested_quantity=order.quantity,
                filled_quantity=order.quantity,
                avg_price=order.price or 50000,  # Default price
                status="filled",
                filled_at=datetime.now(),
            )
        else:
            return OrderResult(
                order_id=order_id,
                ticker=order.ticker,
                side=order.side,
                requested_quantity=order.quantity,
                filled_quantity=0,
                status="rejected",
                message="Simulated rejection",
            )

    def _aggregate_results(
        self,
        original_order: OrderRequest,
        results: List[OrderResult],
    ) -> OrderResult:
        """Aggregate multiple split order results."""
        total_filled = sum(r.filled_quantity for r in results)
        total_value = sum(r.filled_quantity * r.avg_price for r in results)
        avg_price = total_value / total_filled if total_filled > 0 else 0

        # Determine overall status
        if total_filled >= original_order.quantity:
            status = "filled"
        elif total_filled > 0:
            status = "partial"
        else:
            status = "rejected"

        return OrderResult(
            order_id=results[0].order_id if results else str(uuid.uuid4())[:8],
            ticker=original_order.ticker,
            side=original_order.side,
            requested_quantity=original_order.quantity,
            filled_quantity=total_filled,
            avg_price=avg_price,
            status=status,
            filled_at=datetime.now() if total_filled > 0 else None,
            message=f"Split order: {len(results)} parts",
        )

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.

        Returns:
            True if cancelled successfully
        """
        if order_id not in self._pending_orders:
            logger.warning(f"[OrderAgent] Order {order_id} not found in pending")
            return False

        if self.kiwoom:
            try:
                await self.limiter.wait_for_slot()
                await self.kiwoom.cancel_order(order_id)
            except Exception as e:
                logger.error(f"[OrderAgent] Cancel failed: {e}")
                return False

        del self._pending_orders[order_id]
        return True

    def get_pending_orders(self) -> List[OrderRequest]:
        """Get all pending orders."""
        return list(self._pending_orders.values())

    def get_order_history(self, limit: int = 50) -> List[OrderResult]:
        """Get recent completed orders."""
        orders = list(self._completed_orders.values())
        return sorted(orders, key=lambda o: o.created_at, reverse=True)[:limit]
