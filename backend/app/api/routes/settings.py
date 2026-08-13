"""
Settings API Routes

Endpoints for managing application settings including API keys.
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.schemas.settings import SettingsResponse
from app.api.schemas.kr_stocks import (
    KiwoomApiKeyRequest,
    KiwoomApiKeyResponse,
    KiwoomApiKeyStatus,
    KiwoomValidationResponse,
)
from app.config import settings

logger = structlog.get_logger()
router = APIRouter()

# In-memory storage for runtime API keys (not persisted across restarts)
# For production, use secure storage (environment variables, secrets manager, etc.)
_runtime_kiwoom_keys: dict[str, Optional[str]] = {
    "app_key": None,
    "secret_key": None,
    "account": None,
    "is_mock": True,
    "last_validated": None,
    "is_valid": None,
}


def mask_key(key: Optional[str]) -> Optional[str]:
    """Mask API key for display (show first 4 chars + ****)."""
    if not key or len(key) < 8:
        return None
    return f"{key[:4]}****{key[-4:]}"


# -------------------------------------------
# Settings Endpoints
# -------------------------------------------


@router.get("", response_model=SettingsResponse)
async def get_settings_status():
    """
    Get current application settings status.

    Returns:
        Settings status (LLM provider/model, market data mode)
    """
    return SettingsResponse(
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
        market_data_mode=settings.MARKET_DATA_MODE,
    )


# -------------------------------------------
# Trading Mode (Autonomous | HITL) — R3
# -------------------------------------------

from typing import Literal
from pydantic import BaseModel


class TradingModeResponse(BaseModel):
    """Per-market trading mode + the autonomy master gate state."""
    kiwoom: Literal["hitl", "autonomous"]
    master_enabled: bool


class TradingModeUpdate(BaseModel):
    """Set one market's trading mode."""
    market: Literal["kiwoom"]
    mode: Literal["hitl", "autonomous"]


async def _trading_mode_response() -> TradingModeResponse:
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    return TradingModeResponse(
        kiwoom=await storage.get_app_setting("trading_mode:kiwoom", "hitl"),
        master_enabled=settings.AUTONOMY_ENABLED,
    )


@router.get("/trading-mode", response_model=TradingModeResponse)
async def get_trading_mode():
    """Get per-market Autonomous|HITL mode (persisted; default hitl)."""
    return await _trading_mode_response()


@router.put("/trading-mode", response_model=TradingModeResponse)
async def set_trading_mode(update: TradingModeUpdate):
    """Set one market's trading mode. The autonomy gate additionally requires
    AUTONOMY_ENABLED and paper mode — this toggle alone never enables live
    autonomous trading."""
    from services.storage_service import get_storage_service

    storage = await get_storage_service()
    await storage.set_app_setting(f"trading_mode:{update.market}", update.mode)
    logger.info("trading_mode_updated", market=update.market, mode=update.mode)
    return await _trading_mode_response()


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
            _runtime_kiwoom_keys["last_validated"] = datetime.now(timezone.utc)

            logger.info("kiwoom_api_keys_validated")

            return KiwoomValidationResponse(
                is_valid=True,
                message="API keys validated successfully.",
                account_info=None,
            )

    except Exception as e:
        _runtime_kiwoom_keys["is_valid"] = False
        _runtime_kiwoom_keys["last_validated"] = datetime.now(timezone.utc)

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


