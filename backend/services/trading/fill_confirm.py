"""
Fill Confirmation

Shared helper for confirming the actual fill of an accepted Kiwoom order via
ka10076 (체결내역). Extracted from OrderAgent._confirm_kiwoom_fill so other
callers (e.g. the LangGraph execution node) can reuse the exact same logic.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def confirm_kiwoom_fill(
    kiwoom_client,
    *,
    ticker: str,
    order_no: str,
    requested_qty: int,
    fallback_price: float,
    attempts: int = 3,
    interval: float = 0.5,
) -> tuple[int, float]:
    """Confirm the actual fill of an accepted Kiwoom order via ka10076.

    Polls the fill list (체결내역) up to `attempts` times, matching by order
    number and summing 체결수량. Returns (filled_qty, avg_price).
    Fills are asynchronous, so a just-placed limit order may show 0 — that is
    reported faithfully (assume nothing). A query failure is treated as an
    unconfirmed fill (0), never as a full fill.
    """
    filled_qty = 0
    avg_price = fallback_price
    for attempt in range(attempts):
        try:
            # Bypass the 5s cache — every poll must see the latest fills,
            # else all retries within the TTL replay the same stale snapshot.
            fills = await kiwoom_client.get_filled_orders(
                stk_cd=ticker, use_cache=False
            )
        except Exception as e:
            logger.warning(
                f"[fill_confirm] Fill confirmation query failed for {order_no}: {e}"
            )
            fills = []

        matching = [
            f for f in fills if f.ord_no == order_no and f.ccld_qty > 0
        ]
        filled_qty = sum(f.ccld_qty for f in matching)
        if filled_qty > 0:
            value = sum(f.ccld_qty * f.ccld_uv for f in matching)
            avg_price = value / filled_qty

        if filled_qty >= requested_qty:
            break
        if attempt < attempts - 1:
            await asyncio.sleep(interval)

    return filled_qty, avg_price
