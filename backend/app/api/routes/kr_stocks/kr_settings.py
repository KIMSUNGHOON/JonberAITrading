"""
Korean Stock Settings Endpoints

Endpoints for Kiwoom API configuration:
- GET /settings/status - API status
- POST /settings/update - Update API keys
- POST /settings/validate - Validate API keys
- DELETE /settings/clear - Clear API keys
"""

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.kr_stocks import (
    KiwoomApiKeyRequest,
    KiwoomApiKeyResponse,
    KiwoomApiKeyStatus,
    KiwoomValidationResponse,
)
from app.config import settings
from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
from .helpers import check_kiwoom_api_keys

logger = structlog.get_logger()
router = APIRouter()


@router.get("/settings/status", response_model=KiwoomApiKeyStatus)
async def get_kiwoom_api_status():
    """
    Get current Kiwoom API configuration status.

    Returns:
        Configuration status including whether keys are set
    """
    app_key = getattr(settings, "KIWOOM_APP_KEY", None)
    account = getattr(settings, "KIWOOM_ACCOUNT_NUMBER", None)
    is_mock = getattr(settings, "KIWOOM_IS_MOCK", True)

    is_configured = bool(app_key and account)

    # Mask account number for display
    account_masked = None
    if account:
        if len(account) > 4:
            account_masked = account[:4] + "*" * (len(account) - 4)
        else:
            account_masked = "****"

    return KiwoomApiKeyStatus(
        is_configured=is_configured,
        account_masked=account_masked,
        trading_mode="paper" if is_mock else "live",
        is_valid=None,  # Would need to validate with API
        last_validated=None,
    )


@router.post("/settings/update", response_model=KiwoomApiKeyResponse)
async def update_kiwoom_api_keys(request: KiwoomApiKeyRequest):
    """
    Update Kiwoom API keys.

    Note: In production, this would persist to secure storage.
    Currently updates in-memory settings only.

    Args:
        request: API key update request

    Returns:
        Update result with new status
    """
    try:
        settings.KIWOOM_APP_KEY = request.app_key
        settings.KIWOOM_APP_SECRET = request.app_secret
        settings.KIWOOM_ACCOUNT_NUMBER = request.account_number
        settings.KIWOOM_IS_MOCK = request.is_mock

        logger.info(
            "kiwoom_api_keys_updated",
            account=request.account_number[:4] + "****",
            is_mock=request.is_mock,
        )

        return KiwoomApiKeyResponse(
            success=True,
            message="Kiwoom API 설정이 업데이트되었습니다",
            status=KiwoomApiKeyStatus(
                is_configured=True,
                account_masked=request.account_number[:4] + "****",
                trading_mode="paper" if request.is_mock else "live",
                is_valid=None,
                last_validated=None,
            ),
        )

    except Exception as e:
        logger.error("update_kiwoom_keys_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 업데이트 실패: {str(e)}",
        )


@router.post("/settings/validate", response_model=KiwoomValidationResponse)
async def validate_kiwoom_api_keys():
    """
    Validate Kiwoom API keys by making a test request.

    Returns:
        Validation result
    """
    check_kiwoom_api_keys()

    client = await get_shared_kiwoom_client_async()

    try:
        # Try to get cash balance as a test
        balance = await client.get_cash_balance()

        return KiwoomValidationResponse(
            is_valid=True,
            message="API 키가 유효합니다",
            account_info={
                "deposit": balance.dnca_tot_amt,
                "orderable_amount": balance.ord_psbl_amt,
            },
        )

    except Exception as e:
        logger.error("validate_kiwoom_keys_failed", error=str(e))
        return KiwoomValidationResponse(
            is_valid=False,
            message=f"API 키 검증 실패: {str(e)}",
            account_info=None,
        )


@router.delete("/settings/clear")
async def clear_kiwoom_api_keys():
    """
    Clear Kiwoom API keys from settings.

    Returns:
        Confirmation message
    """
    try:
        settings.KIWOOM_APP_KEY = None
        settings.KIWOOM_APP_SECRET = None
        settings.KIWOOM_ACCOUNT_NUMBER = None

        logger.info("kiwoom_api_keys_cleared")

        return {"message": "Kiwoom API 설정이 삭제되었습니다"}

    except Exception as e:
        logger.error("clear_kiwoom_keys_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"설정 삭제 실패: {str(e)}",
        )
