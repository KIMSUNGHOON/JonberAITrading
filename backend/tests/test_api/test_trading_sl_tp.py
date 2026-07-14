"""
PUT /trading/positions/{ticker}/stop-loss|take-profit — honesty fix (T7 review C1).

Before this fix, both routes unconditionally returned {"status": "updated"}
even when RiskMonitor wasn't tracking `ticker` in `_watching` — which is
ALWAYS true for coin positions (they live in the separate `coin_positions`
storage table and never enter `_watching`). These tests pin the new
contract:

- ticker IS watched by RiskMonitor -> update applied there, "source":
  "risk_monitor".
- ticker is NOT watched but IS a persisted coin position -> the edit is
  persisted directly into the coin position store instead (the surface
  PositionsPanel actually reads), "source": "coin_position_store".
- ticker is neither watched nor a known coin position -> honest 404, never
  a fake "updated".
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes import trading as trading_mod
from services.trading.risk_monitor import RiskMonitor
from services.trading.models import ManagedPosition


def _coordinator_with_real_risk_monitor() -> MagicMock:
    coord = MagicMock()
    coord.risk_monitor = RiskMonitor()
    return coord


def _storage(get_position_result=None, update_result=True):
    storage = MagicMock()
    storage.get_coin_position = AsyncMock(return_value=get_position_result)
    storage.update_coin_position = AsyncMock(return_value=update_result)
    return storage


# -------------------------------------------
# stop-loss
# -------------------------------------------

async def test_stop_loss_uses_risk_monitor_when_ticker_is_watched():
    coordinator = _coordinator_with_real_risk_monitor()
    coordinator.risk_monitor.add_position(
        ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10, avg_price=70000)
    )

    res = await trading_mod.update_position_stop_loss(
        ticker="005930", stop_loss=65000, coordinator=coordinator
    )

    assert res == {"status": "updated", "ticker": "005930", "stop_loss": 65000, "source": "risk_monitor"}
    assert coordinator.risk_monitor._watching["005930"].stop_loss == 65000


async def test_stop_loss_falls_back_to_coin_store_when_unwatched():
    """The always-true-today case: a coin ticker never enters `_watching`."""
    coordinator = _coordinator_with_real_risk_monitor()
    storage = _storage(get_position_result={"market": "KRW-BTC", "quantity": 0.5}, update_result=True)

    with patch("services.storage_service.get_storage_service", AsyncMock(return_value=storage)):
        res = await trading_mod.update_position_stop_loss(
            ticker="KRW-BTC", stop_loss=48_000_000, coordinator=coordinator
        )

    assert res == {
        "status": "updated", "ticker": "KRW-BTC", "stop_loss": 48_000_000,
        "source": "coin_position_store",
    }
    storage.update_coin_position.assert_awaited_once_with("KRW-BTC", {"stop_loss": 48_000_000})


async def test_stop_loss_raises_honest_404_when_ticker_unknown_everywhere():
    """No fake 'updated' — a ticker that's neither watched nor a stored
    position must surface as an explicit error, never a silent no-op."""
    coordinator = _coordinator_with_real_risk_monitor()
    storage = _storage(get_position_result=None)

    with patch("services.storage_service.get_storage_service", AsyncMock(return_value=storage)):
        with pytest.raises(HTTPException) as exc_info:
            await trading_mod.update_position_stop_loss(
                ticker="KRW-DOGE", stop_loss=100, coordinator=coordinator
            )

    assert exc_info.value.status_code == 404
    storage.update_coin_position.assert_not_awaited()


# -------------------------------------------
# take-profit (same contract, lighter coverage)
# -------------------------------------------

async def test_take_profit_uses_risk_monitor_when_ticker_is_watched():
    coordinator = _coordinator_with_real_risk_monitor()
    coordinator.risk_monitor.add_position(
        ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10, avg_price=70000)
    )

    res = await trading_mod.update_position_take_profit(
        ticker="005930", take_profit=80000, coordinator=coordinator
    )

    assert res == {"status": "updated", "ticker": "005930", "take_profit": 80000, "source": "risk_monitor"}


async def test_take_profit_falls_back_to_coin_store_when_unwatched():
    coordinator = _coordinator_with_real_risk_monitor()
    storage = _storage(get_position_result={"market": "KRW-BTC", "quantity": 0.5}, update_result=True)

    with patch("services.storage_service.get_storage_service", AsyncMock(return_value=storage)):
        res = await trading_mod.update_position_take_profit(
            ticker="krw-btc", take_profit=55_000_000, coordinator=coordinator
        )

    assert res == {
        "status": "updated", "ticker": "KRW-BTC", "take_profit": 55_000_000,
        "source": "coin_position_store",
    }
    storage.update_coin_position.assert_awaited_once_with("KRW-BTC", {"take_profit": 55_000_000})


async def test_take_profit_raises_honest_404_when_ticker_unknown_everywhere():
    coordinator = _coordinator_with_real_risk_monitor()
    storage = _storage(get_position_result=None)

    with patch("services.storage_service.get_storage_service", AsyncMock(return_value=storage)):
        with pytest.raises(HTTPException) as exc_info:
            await trading_mod.update_position_take_profit(
                ticker="KRW-DOGE", take_profit=100, coordinator=coordinator
            )

    assert exc_info.value.status_code == 404
