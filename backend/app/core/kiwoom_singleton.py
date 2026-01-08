"""
Kiwoom Client Singleton

Provides a shared KiwoomClient instance across the application.
Ensures rate limiter and cache are shared between all requests.
"""

import asyncio
from typing import Optional, Tuple

import structlog

from services.kiwoom import KiwoomClient

logger = structlog.get_logger()

# Singleton instance and keys
_kiwoom_client: Optional[KiwoomClient] = None
_kiwoom_keys: Tuple[str, str, bool] = ("", "", True)
_lock = asyncio.Lock()


def _get_runtime_keys() -> Tuple[str, str, bool]:
    """
    Get Kiwoom API keys from runtime storage (updated via settings API).
    Falls back to environment config if runtime keys not set.
    """
    # Import here to avoid circular import
    from app.api.routes.settings import (
        get_kiwoom_app_key,
        get_kiwoom_secret_key,
        get_kiwoom_is_mock,
    )

    return (
        get_kiwoom_app_key() or "",
        get_kiwoom_secret_key() or "",
        get_kiwoom_is_mock(),
    )


def get_shared_kiwoom_client() -> KiwoomClient:
    """
    Get shared KiwoomClient singleton.

    This client shares rate limiter and cache across all requests.
    Automatically recreates if API keys change.

    Returns:
        Shared KiwoomClient instance
    """
    global _kiwoom_client, _kiwoom_keys

    current_keys = _get_runtime_keys()

    # Create new client if keys changed or not initialized
    if _kiwoom_client is None or _kiwoom_keys != current_keys:
        # Close old client if exists
        if _kiwoom_client is not None:
            try:
                # Use synchronous close if possible
                asyncio.get_event_loop().run_until_complete(_kiwoom_client.close())
            except Exception:
                pass  # Ignore cleanup errors

        _kiwoom_client = KiwoomClient(
            app_key=current_keys[0],
            secret_key=current_keys[1],
            is_mock=current_keys[2],
        )
        _kiwoom_keys = current_keys
        logger.info(
            "kiwoom_singleton_created",
            is_mock=current_keys[2],
            has_keys=bool(current_keys[0] and current_keys[1]),
        )

    return _kiwoom_client


async def get_shared_kiwoom_client_async() -> KiwoomClient:
    """
    Async version of get_shared_kiwoom_client.
    Thread-safe with async lock.
    """
    global _kiwoom_client, _kiwoom_keys

    async with _lock:
        current_keys = _get_runtime_keys()

        if _kiwoom_client is None or _kiwoom_keys != current_keys:
            if _kiwoom_client is not None:
                try:
                    await _kiwoom_client.close()
                except Exception:
                    pass

            _kiwoom_client = KiwoomClient(
                app_key=current_keys[0],
                secret_key=current_keys[1],
                is_mock=current_keys[2],
            )
            _kiwoom_keys = current_keys
            logger.info(
                "kiwoom_singleton_created_async",
                is_mock=current_keys[2],
                has_keys=bool(current_keys[0] and current_keys[1]),
            )

    return _kiwoom_client


def invalidate_kiwoom_client():
    """
    Invalidate the singleton client.
    Call this when API keys are updated to force recreation.
    """
    global _kiwoom_client, _kiwoom_keys

    if _kiwoom_client is not None:
        try:
            asyncio.get_event_loop().run_until_complete(_kiwoom_client.close())
        except Exception:
            pass

    _kiwoom_client = None
    _kiwoom_keys = ("", "", True)
    logger.info("kiwoom_singleton_invalidated")


async def close_kiwoom_client():
    """
    Close the singleton client gracefully.
    Call this on application shutdown.
    """
    global _kiwoom_client

    if _kiwoom_client is not None:
        try:
            await _kiwoom_client.close()
        except Exception:
            pass
        _kiwoom_client = None
        logger.info("kiwoom_singleton_closed")
