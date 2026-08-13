"""PUT /trading/positions/{ticker}/stop-loss|take-profit — honesty fix (T7 review C1).

Before this fix, both routes unconditionally returned {"status": "updated"}
even when RiskMonitor wasn't tracking `ticker` in `_watching`. These tests
pin the contract:

- ticker IS watched by RiskMonitor -> update applied there, "source":
  "risk_monitor".
- ticker is NOT watched -> honest 404, never a fake "updated".

(2026-08-01 Upbit 제거: 이 라우트는 RiskMonitor가 모르는 티커에 대해
`storage.coin_positions`로 폴백해 저장하는 두 번째 경로가 있었다 — 코인
포지션은 `_watching`에 절대 들어가지 않았기 때문이다. 코인 매매가
백엔드에서 완전히 제거되면서 그 폴백은 대상이 될 코인 포지션이 다시는
생기지 않는 영구 사문화 코드가 됐고, 함께 제거했다. KR 티커에 대해서는
이 폴백이 원래도 실질적으로 절대 성공하지 않았으므로("KRW-BTC" 류가
아닌 티커는 get_coin_position이 늘 None) 아래 3-way 계약이 2-way로
줄어드는 것 외에 동작 변화는 없다.)
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes import trading as trading_mod
from services.trading.risk_monitor import RiskMonitor
from services.trading.models import ManagedPosition


def _coordinator_with_real_risk_monitor() -> MagicMock:
    coord = MagicMock()
    coord.risk_monitor = RiskMonitor()
    return coord


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


async def test_stop_loss_raises_honest_404_when_ticker_unwatched():
    """No fake 'updated' — a ticker RiskMonitor isn't tracking must surface
    as an explicit error, never a silent no-op."""
    coordinator = _coordinator_with_real_risk_monitor()

    with pytest.raises(HTTPException) as exc_info:
        await trading_mod.update_position_stop_loss(
            ticker="999999", stop_loss=100, coordinator=coordinator
        )

    assert exc_info.value.status_code == 404


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


async def test_take_profit_raises_honest_404_when_ticker_unwatched():
    coordinator = _coordinator_with_real_risk_monitor()

    with pytest.raises(HTTPException) as exc_info:
        await trading_mod.update_position_take_profit(
            ticker="999999", take_profit=100, coordinator=coordinator
        )

    assert exc_info.value.status_code == 404
