"""
Background Scanner API Routes

Endpoints for controlling the background stock scanner.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.background_scanner import (
    get_background_scanner,
    ScanStatus,
    ScanProgress,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])


# -------------------------------------------
# Request/Response Models
# -------------------------------------------

class StartScanRequest(BaseModel):
    """Request to start background scan"""
    notify_progress: bool = True
    custom_stocks: Optional[List[tuple]] = None  # [(stk_cd, stk_nm), ...]


class ScanProgressResponse(BaseModel):
    """Scan progress response"""
    status: str
    total_stocks: int
    completed: int
    in_progress: int
    failed: int
    progress_pct: float
    current_stocks: List[str]
    buy_count: int
    sell_count: int
    hold_count: int
    watch_count: int
    avoid_count: int
    started_at: Optional[str] = None
    estimated_completion: Optional[str] = None
    completed_at: Optional[str] = None
    last_scan_date: Optional[str] = None
    last_error: Optional[str] = None


class ScanResultItem(BaseModel):
    """Individual scan result"""
    stk_cd: str
    stk_nm: str
    action: str
    signal: str
    confidence: float
    summary: str
    key_factors: List[str]
    current_price: int
    scanned_at: str


class ScanResultsResponse(BaseModel):
    """Scan results response"""
    results: List[ScanResultItem]
    count: int
    filter: Optional[str] = None


# -------------------------------------------
# Scanner Endpoints
# -------------------------------------------

@router.post("/start")
async def start_scan(request: Optional[StartScanRequest] = None):
    """
    Start background stock scan.

    Scans all KOSPI/KOSDAQ stocks with 3 concurrent analysis slots.
    Sends Telegram notifications for progress and completion.
    """
    try:
        scanner = await get_background_scanner()

        # Check if already running
        progress = scanner.get_progress()
        if progress.status == ScanStatus.RUNNING:
            raise HTTPException(
                status_code=400,
                detail="Scanner is already running"
            )

        # Start scan
        await scanner.start_scan(
            stock_list=request.custom_stocks if request else None,
            notify_progress=request.notify_progress if request else True,
        )

        return {
            "status": "started",
            "message": "Background scan started",
            "total_stocks": scanner.get_progress().total_stocks,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Scanner API] Start failed")
        raise HTTPException(500, f"Failed to start scan: {e}")


@router.post("/pause")
async def pause_scan():
    """Pause the background scan."""
    try:
        scanner = await get_background_scanner()
        await scanner.pause_scan()

        return {
            "status": "paused",
            "message": "Background scan paused",
        }

    except Exception as e:
        logger.exception("[Scanner API] Pause failed")
        raise HTTPException(500, f"Failed to pause scan: {e}")


@router.post("/resume")
async def resume_scan():
    """Resume the background scan."""
    try:
        scanner = await get_background_scanner()
        await scanner.resume_scan()

        return {
            "status": "resumed",
            "message": "Background scan resumed",
        }

    except Exception as e:
        logger.exception("[Scanner API] Resume failed")
        raise HTTPException(500, f"Failed to resume scan: {e}")


@router.post("/stop")
async def stop_scan():
    """Stop the background scan."""
    try:
        scanner = await get_background_scanner()
        await scanner.stop_scan()

        return {
            "status": "stopped",
            "message": "Background scan stopped",
        }

    except Exception as e:
        logger.exception("[Scanner API] Stop failed")
        raise HTTPException(500, f"Failed to stop scan: {e}")


@router.get("/progress", response_model=ScanProgressResponse)
async def get_progress():
    """Get current scan progress."""
    scanner = await get_background_scanner()
    progress = scanner.get_progress()

    return ScanProgressResponse(
        status=progress.status.value,
        total_stocks=progress.total_stocks,
        completed=progress.completed,
        in_progress=progress.in_progress,
        failed=progress.failed,
        progress_pct=progress.progress_pct,
        current_stocks=progress.current_stocks,
        buy_count=progress.buy_count,
        sell_count=progress.sell_count,
        hold_count=progress.hold_count,
        watch_count=progress.watch_count,
        avoid_count=progress.avoid_count,
        started_at=progress.started_at.isoformat() if progress.started_at else None,
        estimated_completion=progress.estimated_completion.isoformat() if progress.estimated_completion else None,
        completed_at=progress.completed_at.isoformat() if progress.completed_at else None,
        last_scan_date=progress.last_scan_date.isoformat() if progress.last_scan_date else None,
        last_error=progress.last_error,
    )


@router.get("/results")
async def get_results(action: Optional[str] = None):
    """
    Get scan results.

    Args:
        action: Filter by action (BUY, SELL, HOLD, WATCH, AVOID)
    """
    scanner = await get_background_scanner()
    results = scanner.get_results(action_filter=action)

    return ScanResultsResponse(
        results=[
            ScanResultItem(
                stk_cd=r.stk_cd,
                stk_nm=r.stk_nm,
                action=r.action,
                signal=r.signal,
                confidence=r.confidence,
                summary=r.summary,
                key_factors=r.key_factors,
                current_price=r.current_price,
                scanned_at=r.scanned_at.isoformat(),
            )
            for r in results
        ],
        count=len(results),
        filter=action,
    )


@router.get("/results/buy")
async def get_buy_recommendations():
    """Get stocks with BUY recommendation."""
    scanner = await get_background_scanner()
    results = scanner.get_results(action_filter="BUY")

    return {
        "action": "BUY",
        "count": len(results),
        "stocks": [
            {
                "stk_cd": r.stk_cd,
                "stk_nm": r.stk_nm,
                "confidence": r.confidence,
                "current_price": r.current_price,
                "summary": r.summary,
            }
            for r in results
        ],
    }


@router.get("/results/watch")
async def get_watch_recommendations():
    """Get stocks with WATCH recommendation."""
    scanner = await get_background_scanner()
    results = scanner.get_results(action_filter="WATCH")

    return {
        "action": "WATCH",
        "count": len(results),
        "stocks": [
            {
                "stk_cd": r.stk_cd,
                "stk_nm": r.stk_nm,
                "confidence": r.confidence,
                "current_price": r.current_price,
                "summary": r.summary,
            }
            for r in results
        ],
    }


@router.post("/check-reminder")
async def check_reminder():
    """
    Check if monthly reminder is needed.

    Returns whether a reminder was sent.
    """
    scanner = await get_background_scanner()
    reminded = await scanner.check_monthly_reminder()

    return {
        "reminded": reminded,
        "last_scan_date": scanner.get_progress().last_scan_date.isoformat()
            if scanner.get_progress().last_scan_date else None,
    }
