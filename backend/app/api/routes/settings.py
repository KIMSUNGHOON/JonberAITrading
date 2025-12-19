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
