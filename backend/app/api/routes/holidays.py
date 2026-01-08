"""
Holiday API Routes

Provides endpoints for managing KRX market holidays.
"""

from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.krx_holiday import get_holiday_service_sync, HolidayInfo

router = APIRouter(prefix="/holidays", tags=["holidays"])


# -------------------------------------------
# Response Schemas
# -------------------------------------------

class HolidayResponse(BaseModel):
    """Holiday information response."""
    date: str
    day_of_week: str
    name: str
    year: int


class HolidayListResponse(BaseModel):
    """List of holidays response."""
    holidays: List[HolidayResponse]
    count: int
    year: Optional[int] = None


class HolidayCheckResponse(BaseModel):
    """Holiday check response."""
    date: str
    is_holiday: bool
    is_trading_day: bool
    holiday_name: Optional[str] = None


class ServiceStatusResponse(BaseModel):
    """Service status response."""
    initialized: bool
    scheduler_running: bool
    last_update: Optional[str] = None
    year_stats: dict
    total_holidays: int


class UpdateResponse(BaseModel):
    """Update response."""
    success: bool
    message: str
    holidays_updated: int


# -------------------------------------------
# Helper Functions
# -------------------------------------------

def _get_service():
    """Get holiday service instance."""
    return get_holiday_service_sync()


def _holiday_to_response(holiday: HolidayInfo) -> HolidayResponse:
    """Convert HolidayInfo to response model."""
    return HolidayResponse(
        date=holiday.date.isoformat(),
        day_of_week=holiday.day_of_week,
        name=holiday.name,
        year=holiday.year,
    )


# -------------------------------------------
# Endpoints
# -------------------------------------------

@router.get("/", response_model=HolidayListResponse)
async def get_holidays(
    year: Optional[int] = Query(None, description="Filter by year"),
):
    """
    Get list of KRX holidays.

    Optionally filter by year.
    """
    service = _get_service()
    holidays = service.get_holidays(year)

    return HolidayListResponse(
        holidays=[_holiday_to_response(h) for h in holidays],
        count=len(holidays),
        year=year,
    )


@router.get("/check/{check_date}", response_model=HolidayCheckResponse)
async def check_date(
    check_date: str,
):
    """
    Check if a specific date is a holiday.

    Date format: YYYY-MM-DD
    """
    try:
        parsed_date = date.fromisoformat(check_date)
    except ValueError:
        raise HTTPException(400, f"Invalid date format: {check_date}. Use YYYY-MM-DD")

    service = _get_service()

    is_holiday = service.is_holiday(parsed_date)
    is_trading_day = service.is_trading_day(parsed_date)
    holiday_info = service.get_holiday_info(parsed_date)

    return HolidayCheckResponse(
        date=check_date,
        is_holiday=is_holiday,
        is_trading_day=is_trading_day,
        holiday_name=holiday_info.name if holiday_info else None,
    )


@router.get("/next-trading-day", response_model=HolidayCheckResponse)
async def get_next_trading_day(
    from_date: Optional[str] = Query(None, description="Starting date (YYYY-MM-DD)"),
):
    """
    Get the next trading day from a given date.

    If no date provided, uses today.
    """
    service = _get_service()

    if from_date:
        try:
            start_date = date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(400, f"Invalid date format: {from_date}. Use YYYY-MM-DD")
    else:
        start_date = date.today()

    next_day = service.get_next_trading_day(start_date)

    return HolidayCheckResponse(
        date=next_day.isoformat(),
        is_holiday=False,
        is_trading_day=True,
        holiday_name=None,
    )


@router.get("/previous-trading-day", response_model=HolidayCheckResponse)
async def get_previous_trading_day(
    from_date: Optional[str] = Query(None, description="Starting date (YYYY-MM-DD)"),
):
    """
    Get the previous trading day from a given date.

    If no date provided, uses today.
    """
    service = _get_service()

    if from_date:
        try:
            start_date = date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(400, f"Invalid date format: {from_date}. Use YYYY-MM-DD")
    else:
        start_date = date.today()

    prev_day = service.get_previous_trading_day(start_date)

    return HolidayCheckResponse(
        date=prev_day.isoformat(),
        is_holiday=False,
        is_trading_day=True,
        holiday_name=None,
    )


@router.get("/status", response_model=ServiceStatusResponse)
async def get_service_status():
    """
    Get holiday service status.

    Returns initialization state, update info, and statistics.
    """
    service = _get_service()
    status = service.get_status()

    return ServiceStatusResponse(**status)


@router.post("/update", response_model=UpdateResponse)
async def update_holidays(
    year: Optional[int] = Query(None, description="Specific year to update"),
):
    """
    Manually trigger holiday data update.

    If year is not provided, updates current and next year.
    """
    service = _get_service()

    try:
        count = await service.update_holidays(year)
        return UpdateResponse(
            success=True,
            message=f"Updated holidays for year(s): {year if year else 'current and next'}",
            holidays_updated=count,
        )
    except Exception as e:
        return UpdateResponse(
            success=False,
            message=f"Update failed: {str(e)}",
            holidays_updated=0,
        )


@router.get("/trading-days", response_model=List[str])
async def get_trading_days(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
):
    """
    Get all trading days in a date range.

    Returns list of trading day dates.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date format: {e}. Use YYYY-MM-DD")

    if start > end:
        raise HTTPException(400, "Start date must be before end date")

    if (end - start).days > 365:
        raise HTTPException(400, "Date range cannot exceed 365 days")

    service = _get_service()
    trading_days = service.get_trading_days_in_range(start, end)

    return [d.isoformat() for d in trading_days]
