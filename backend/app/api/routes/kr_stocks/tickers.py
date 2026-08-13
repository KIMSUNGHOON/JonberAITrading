"""
Korean Stock Batch Ticker Endpoint (P1-7)

- POST /tickers - Ticker snapshots for many stock codes in ONE request

Panels that render a watchlist/basket of KR symbols previously fanned out
one GET /ticker/{stk_cd} request per symbol (P0-T4 stopgap). That strains
the shared ~1.4 req/s Kiwoom rate limiter and leaves prices stale under
load. This endpoint reuses the exact same single-quote data path
(KiwoomClient.get_stock_info — same 3s TTL cache, same shared rate
limiter) but lets the frontend issue one request per poll instead of N.

Codes are fetched concurrently via asyncio.gather; the shared rate
limiter's token bucket (on the singleton KiwoomClient) serializes the
actual dispatch, so this does not bypass the throttle — it just collapses
N HTTP round-trips between the frontend and this backend into one.

A per-code failure (unknown code, transient API error) degrades that
code to `null` in the response. This endpoint never fabricates data.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.kr_stocks import (
    KRStockTickerBatchRequest,
    KRStockTickerBatchResponse,
    KRStockTickerResponse,
)
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

logger = structlog.get_logger()
router = APIRouter()

# Sane upper bound — KR watchlists/baskets are small (store caps baskets at
# ~10-20 items today); this just guards against an unbounded fan-in request.
MAX_BATCH_SIZE = 50


async def _fetch_one(client, stk_cd: str) -> tuple[str, Optional[KRStockTickerResponse]]:
    """Fetch a single code's ticker snapshot; None on any failure (honest degrade)."""
    if len(stk_cd) != 6 or not stk_cd.isdigit():
        logger.warning("batch_ticker_invalid_code", stk_cd=stk_cd)
        return stk_cd, None

    try:
        info = await client.get_stock_info(stk_cd)
        if not info:
            return stk_cd, None

        return stk_cd, KRStockTickerResponse(
            stk_cd=stk_cd,
            stk_nm=info.stk_nm,
            cur_prc=info.cur_prc,
            prdy_vrss=info.prdy_vrss,
            prdy_ctrt=info.prdy_ctrt,
            opng_prc=info.strt_prc,
            high_prc=info.high_prc,
            low_prc=info.low_prc,
            trde_qty=info.acml_vol,
            trde_prica=info.acml_tr_pbmn,
            per=info.per,
            pbr=info.pbr,
            eps=info.eps,
            bps=info.bps,
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.warning("batch_ticker_fetch_failed", stk_cd=stk_cd, error=str(e))
        return stk_cd, None


@router.post("/tickers", response_model=KRStockTickerBatchResponse)
async def get_tickers(request: KRStockTickerBatchRequest):
    """
    Get current ticker snapshots for multiple Korean stock codes in one request.

    Args:
        request: Stock codes to fetch (max 50, de-duplicated)

    Returns:
        Map of stock code -> ticker snapshot (null for codes that failed to fetch)
    """
    # De-dup while preserving order; drop blanks.
    seen: set[str] = set()
    codes: list[str] = []
    for raw in request.codes:
        code = (raw or "").strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)

    if not codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one stock code is required",
        )

    if len(codes) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_BATCH_SIZE} codes per request",
        )

    client = await get_shared_kiwoom_client_async()

    results = await asyncio.gather(*(_fetch_one(client, code) for code in codes))

    tickers: dict[str, Optional[KRStockTickerResponse]] = dict(results)
    total = sum(1 for v in tickers.values() if v is not None)

    return KRStockTickerBatchResponse(tickers=tickers, total=total)
