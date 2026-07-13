"""ExecutionCoordinator._get_current_price live-bug regression.

Live logs spammed "Failed to get price ... no attribute 'get_quote'" every
RiskMonitor cycle: KiwoomClient has never had a `get_quote` method — the real
quote API is `get_stock_info(stk_cd) -> StockBasicInfo` (see
agents/tools/kr_market_data.py, the confirmed consumer, and
services/kiwoom/client.py:407). The bug made the fetch always fail, return 0,
and RiskMonitor's `current_price <= 0` guard would then skip stop-loss/
take-profit checks forever — stop monitoring silently ran on stale
registration prices only.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.kiwoom.models import StockBasicInfo
from services.trading.coordinator import ExecutionCoordinator

pytestmark = pytest.mark.asyncio


def _stock_info(cur_prc: int) -> StockBasicInfo:
    return StockBasicInfo(stk_cd="005930", stk_nm="삼성전자", cur_prc=cur_prc)


async def test_get_current_price_uses_real_client_api():
    """Real KiwoomClient method is get_stock_info(stk_cd) -> StockBasicInfo.cur_prc."""
    client = MagicMock()
    client.get_stock_info = AsyncMock(return_value=_stock_info(75000))
    coord = ExecutionCoordinator(kiwoom_client=client)

    price = await coord._get_current_price("005930")

    assert price == 75000.0
    client.get_stock_info.assert_awaited_once_with("005930")


async def test_get_current_price_exception_fails_safe_to_zero():
    """Broker failure must not raise — fail-safe returns 0 (unchanged contract)."""
    client = MagicMock()
    client.get_stock_info = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    coord = ExecutionCoordinator(kiwoom_client=client)

    price = await coord._get_current_price("005930")

    assert price == 0


async def test_get_current_price_simulation_mode_unchanged():
    """No kiwoom client (simulation mode) still returns the mock price."""
    coord = ExecutionCoordinator(kiwoom_client=None)

    price = await coord._get_current_price("005930")

    assert price == 50000
