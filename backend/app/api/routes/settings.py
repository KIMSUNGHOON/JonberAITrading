"""
Settings API Routes

Endpoints for managing application settings including API keys.
"""

import os
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.settings import (
    SettingsResponse,
    UpbitApiKeyRequest,
    UpbitApiKeyResponse,
    UpbitApiKeyStatus,
    UpbitValidateResponse,
)
from app.api.schemas.kr_stocks import (
    KiwoomApiKeyRequest,
    KiwoomApiKeyResponse,
    KiwoomApiKeyStatus,
    KiwoomValidationResponse,
)
from app.config import settings
from services.upbit import UpbitClient

logger = structlog.get_logger()
router = APIRouter()

# In-memory storage for runtime API keys (not persisted across restarts)
# For production, use secure storage (environment variables, secrets manager, etc.)
_runtime_upbit_keys: dict[str, Optional[str]] = {
    "access_key": None,
    "secret_key": None,
    "last_validated": None,
    "is_valid": None,
}

_runtime_kiwoom_keys: dict[str, Optional[str]] = {
    "app_key": None,
    "secret_key": None,
    "account": None,
    "is_mock": True,
    "last_validated": None,
    "is_valid": None,
}


def get_upbit_access_key() -> Optional[str]:
    """Get Upbit access key from runtime storage or environment."""
    return _runtime_upbit_keys.get("access_key") or settings.UPBIT_ACCESS_KEY


def get_upbit_secret_key() -> Optional[str]:
    """Get Upbit secret key from runtime storage or environment."""
    return _runtime_upbit_keys.get("secret_key") or settings.UPBIT_SECRET_KEY


def mask_key(key: Optional[str]) -> Optional[str]:
    """Mask API key for display (show first 4 chars + ****)."""
    if not key or len(key) < 8:
        return None
    return f"{key[:4]}****{key[-4:]}"


def get_upbit_status() -> UpbitApiKeyStatus:
    """Get current Upbit API key status."""
    access_key = get_upbit_access_key()
    is_configured = bool(access_key and get_upbit_secret_key())

    return UpbitApiKeyStatus(
        is_configured=is_configured,
        access_key_masked=mask_key(access_key) if access_key else None,
        trading_mode=settings.UPBIT_TRADING_MODE,
        is_valid=_runtime_upbit_keys.get("is_valid"),
        last_validated=_runtime_upbit_keys.get("last_validated"),
    )


# -------------------------------------------
# Settings Endpoints
# -------------------------------------------


@router.get("", response_model=SettingsResponse)
async def get_settings_status():
    """
    Get current application settings status.

    Returns:
        Settings status including API key configurations
    """
    return SettingsResponse(
        upbit=get_upbit_status(),
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
        market_data_mode=settings.MARKET_DATA_MODE,
    )


# -------------------------------------------
# Upbit API Key Endpoints
# -------------------------------------------


@router.get("/upbit", response_model=UpbitApiKeyStatus)
async def get_upbit_api_status():
    """
    Get Upbit API key configuration status.

    Returns:
        API key status with masked key for security
    """
    return get_upbit_status()


@router.post("/upbit", response_model=UpbitApiKeyResponse)
async def update_upbit_api_keys(request: UpbitApiKeyRequest):
    """
    Update Upbit API keys.

    Keys are stored in runtime memory. For persistence across restarts,
    set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY in environment variables.

    Args:
        request: New API keys

    Returns:
        Success status and updated configuration
    """
    logger.info("upbit_api_keys_updated")

    # Store in runtime
    _runtime_upbit_keys["access_key"] = request.access_key
    _runtime_upbit_keys["secret_key"] = request.secret_key
    _runtime_upbit_keys["is_valid"] = None  # Reset validation
    _runtime_upbit_keys["last_validated"] = None

    return UpbitApiKeyResponse(
        success=True,
        message="API keys updated. Use /settings/upbit/validate to verify.",
        status=get_upbit_status(),
    )


@router.post("/upbit/validate", response_model=UpbitValidateResponse)
async def validate_upbit_api_keys():
    """
    Validate Upbit API keys by attempting to fetch account info.

    Returns:
        Validation result with account count if successful
    """
    access_key = get_upbit_access_key()
    secret_key = get_upbit_secret_key()

    if not access_key or not secret_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API keys not configured. Set keys first.",
        )

    try:
        async with UpbitClient(access_key=access_key, secret_key=secret_key) as client:
            accounts = await client.get_accounts()

            # Update validation status
            _runtime_upbit_keys["is_valid"] = True
            _runtime_upbit_keys["last_validated"] = datetime.utcnow()

            logger.info("upbit_api_keys_validated", account_count=len(accounts))

            return UpbitValidateResponse(
                is_valid=True,
                message=f"API keys validated. Found {len(accounts)} account(s).",
                account_count=len(accounts),
            )

    except Exception as e:
        _runtime_upbit_keys["is_valid"] = False
        _runtime_upbit_keys["last_validated"] = datetime.utcnow()

        logger.error("upbit_api_keys_invalid", error=str(e))

        return UpbitValidateResponse(
            is_valid=False,
            message=f"API key validation failed: {str(e)}",
            account_count=None,
        )


@router.delete("/upbit")
async def clear_upbit_api_keys():
    """
    Clear Upbit API keys from runtime storage.

    Note: This only clears runtime keys. Environment variables remain unchanged.

    Returns:
        Success confirmation
    """
    _runtime_upbit_keys["access_key"] = None
    _runtime_upbit_keys["secret_key"] = None
    _runtime_upbit_keys["is_valid"] = None
    _runtime_upbit_keys["last_validated"] = None

    logger.info("upbit_api_keys_cleared")

    return {"message": "API keys cleared from runtime storage."}


# -------------------------------------------
# Kiwoom API Key Endpoints
# -------------------------------------------


def get_kiwoom_app_key() -> Optional[str]:
    """Get Kiwoom app key from runtime storage or environment."""
    return _runtime_kiwoom_keys.get("app_key") or getattr(settings, "KIWOOM_APP_KEY", None)


def get_kiwoom_secret_key() -> Optional[str]:
    """Get Kiwoom secret key from runtime storage or environment."""
    return _runtime_kiwoom_keys.get("secret_key") or getattr(settings, "KIWOOM_SECRET_KEY", None)


def get_kiwoom_account() -> Optional[str]:
    """Get Kiwoom account from runtime storage or environment."""
    return _runtime_kiwoom_keys.get("account") or getattr(settings, "KIWOOM_ACCOUNT_NO", None)


def get_kiwoom_is_mock() -> bool:
    """Get Kiwoom mock mode from runtime storage or environment."""
    if _runtime_kiwoom_keys.get("is_mock") is not None:
        return _runtime_kiwoom_keys.get("is_mock")
    return getattr(settings, "KIWOOM_IS_MOCK", True)


def get_kiwoom_status() -> KiwoomApiKeyStatus:
    """Get current Kiwoom API key status."""
    app_key = get_kiwoom_app_key()
    is_configured = bool(app_key and get_kiwoom_secret_key())
    account = get_kiwoom_account()

    return KiwoomApiKeyStatus(
        is_configured=is_configured,
        account_masked=mask_key(account) if account else None,
        trading_mode="paper" if get_kiwoom_is_mock() else "live",
        is_valid=_runtime_kiwoom_keys.get("is_valid"),
        last_validated=_runtime_kiwoom_keys.get("last_validated"),
    )


@router.get("/kiwoom", response_model=KiwoomApiKeyStatus)
async def get_kiwoom_api_status():
    """
    Get Kiwoom API key configuration status.

    Returns:
        API key status with masked key for security
    """
    return get_kiwoom_status()


@router.post("/kiwoom", response_model=KiwoomApiKeyResponse)
async def update_kiwoom_api_keys(request: KiwoomApiKeyRequest):
    """
    Update Kiwoom API keys.

    Keys are stored in runtime memory. For persistence across restarts,
    set KIWOOM_APP_KEY and KIWOOM_APP_SECRET in environment variables.

    Args:
        request: New API keys

    Returns:
        Success status and updated configuration
    """
    logger.info("kiwoom_api_keys_updated")

    # Store in runtime
    _runtime_kiwoom_keys["app_key"] = request.app_key
    _runtime_kiwoom_keys["secret_key"] = request.app_secret
    _runtime_kiwoom_keys["account"] = request.account_number
    _runtime_kiwoom_keys["is_mock"] = request.is_mock
    _runtime_kiwoom_keys["is_valid"] = None  # Reset validation
    _runtime_kiwoom_keys["last_validated"] = None

    return KiwoomApiKeyResponse(
        success=True,
        message="API keys updated. Use /settings/kiwoom/validate to verify.",
        status=get_kiwoom_status(),
    )


@router.post("/kiwoom/validate", response_model=KiwoomValidationResponse)
async def validate_kiwoom_api_keys():
    """
    Validate Kiwoom API keys by attempting to get an access token.

    Returns:
        Validation result
    """
    app_key = get_kiwoom_app_key()
    secret_key = get_kiwoom_secret_key()

    if not app_key or not secret_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API keys not configured. Set keys first.",
        )

    try:
        from services.kiwoom import KiwoomClient

        async with KiwoomClient(
            app_key=app_key,
            secret_key=secret_key,
            is_mock=get_kiwoom_is_mock(),
        ) as client:
            # Try to get account balance to validate
            await client.get_cash_balance()

            # Update validation status
            _runtime_kiwoom_keys["is_valid"] = True
            _runtime_kiwoom_keys["last_validated"] = datetime.utcnow()

            logger.info("kiwoom_api_keys_validated")

            return KiwoomValidationResponse(
                is_valid=True,
                message="API keys validated successfully.",
                account_info=None,
            )

    except Exception as e:
        _runtime_kiwoom_keys["is_valid"] = False
        _runtime_kiwoom_keys["last_validated"] = datetime.utcnow()

        logger.error("kiwoom_api_keys_invalid", error=str(e))

        return KiwoomValidationResponse(
            is_valid=False,
            message=f"API key validation failed: {str(e)}",
            account_info=None,
        )


@router.delete("/kiwoom")
async def clear_kiwoom_api_keys():
    """
    Clear Kiwoom API keys from runtime storage.

    Note: This only clears runtime keys. Environment variables remain unchanged.

    Returns:
        Success confirmation
    """
    _runtime_kiwoom_keys["app_key"] = None
    _runtime_kiwoom_keys["secret_key"] = None
    _runtime_kiwoom_keys["account"] = None
    _runtime_kiwoom_keys["is_mock"] = True
    _runtime_kiwoom_keys["is_valid"] = None
    _runtime_kiwoom_keys["last_validated"] = None

    logger.info("kiwoom_api_keys_cleared")

    return {"message": "Kiwoom API keys cleared from runtime storage."}
