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
    use_llm: bool = False  # Use LLM for analysis (slower but more accurate)
    auto_gpu_scaling: bool = True  # Automatically adjust concurrency based on GPU memory


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
    market_type: str = ""
    scanned_at: str


class ScanResultsResponse(BaseModel):
    """Scan results response"""
    results: List[ScanResultItem]
    count: int
    total: int = 0
    filter: Optional[str] = None
    session_id: Optional[str] = None


class ScanSessionItem(BaseModel):
    """Scan session information"""
    id: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_stocks: int = 0
    completed: int = 0
    failed: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    watch_count: int = 0
    avoid_count: int = 0
    status: str = ""


class ScanSessionsResponse(BaseModel):
    """Scan sessions list response"""
    sessions: List[ScanSessionItem]
    count: int


# -------------------------------------------
# Scanner Endpoints
# -------------------------------------------

@router.post("/start")
async def start_scan(request: Optional[StartScanRequest] = None):
    """
    Start background stock scan.

    Scans all KOSPI/KOSDAQ stocks with controlled concurrency.
    Supports two modes:
    - Quick mode (default): Technical indicators only, fast parallel analysis
    - LLM mode: Deep analysis with GPU-based batch processing

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

        # Extract parameters with defaults
        use_llm = request.use_llm if request else False
        auto_gpu_scaling = request.auto_gpu_scaling if request else True

        # Start scan
        await scanner.start_scan(
            stock_list=request.custom_stocks if request else None,
            notify_progress=request.notify_progress if request else True,
            use_llm=use_llm,
            auto_gpu_scaling=auto_gpu_scaling,
        )

        mode = "LLM 배치 분석" if use_llm else "기술적 지표 분석"
        return {
            "status": "started",
            "message": f"Background scan started ({mode})",
            "total_stocks": scanner.get_progress().total_stocks,
            "mode": "llm" if use_llm else "quick",
            "auto_gpu_scaling": auto_gpu_scaling,
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


# -------------------------------------------
# Database Query Endpoints
# -------------------------------------------

@router.get("/db/results")
async def get_db_results(
    action: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Get scan results from database.

    Args:
        action: Filter by action (BUY, SELL, HOLD, WATCH, AVOID)
        session_id: Filter by scan session (None = latest session)
        limit: Maximum results to return
        offset: Offset for pagination
    """
    try:
        scanner = await get_background_scanner()
        results = await scanner.get_results_from_db(
            action_filter=action,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        counts = await scanner.get_result_counts_from_db(session_id=session_id)

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
                    market_type=r.market_type,
                    scanned_at=r.scanned_at.isoformat(),
                )
                for r in results
            ],
            count=len(results),
            total=counts.get("total", 0),
            filter=action,
            session_id=session_id,
        )

    except Exception as e:
        logger.exception("[Scanner API] DB results query failed")
        raise HTTPException(500, f"Failed to query results: {e}")


@router.get("/db/counts")
async def get_db_counts(session_id: Optional[str] = None):
    """
    Get action counts from database.

    Args:
        session_id: Filter by scan session (None = latest session)
    """
    try:
        scanner = await get_background_scanner()
        counts = await scanner.get_result_counts_from_db(session_id=session_id)

        return counts

    except Exception as e:
        logger.exception("[Scanner API] DB counts query failed")
        raise HTTPException(500, f"Failed to query counts: {e}")


@router.get("/db/sessions", response_model=ScanSessionsResponse)
async def get_sessions(limit: int = 10):
    """
    Get recent scan sessions.

    Args:
        limit: Maximum sessions to return
    """
    try:
        scanner = await get_background_scanner()
        sessions = await scanner.get_scan_sessions(limit=limit)

        return ScanSessionsResponse(
            sessions=[
                ScanSessionItem(
                    id=s.get("id", ""),
                    started_at=str(s.get("started_at")) if s.get("started_at") else None,
                    completed_at=str(s.get("completed_at")) if s.get("completed_at") else None,
                    total_stocks=s.get("total_stocks") or 0,
                    completed=s.get("completed") or 0,
                    failed=s.get("failed") or 0,
                    buy_count=s.get("buy_count") or 0,
                    sell_count=s.get("sell_count") or 0,
                    hold_count=s.get("hold_count") or 0,
                    watch_count=s.get("watch_count") or 0,
                    avoid_count=s.get("avoid_count") or 0,
                    status=s.get("status") or "",
                )
                for s in sessions
            ],
            count=len(sessions),
        )

    except Exception as e:
        logger.exception("[Scanner API] Sessions query failed")
        raise HTTPException(500, f"Failed to query sessions: {e}")
