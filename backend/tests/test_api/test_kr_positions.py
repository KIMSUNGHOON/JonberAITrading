"""P2 task 1: GET /positions (KR) — broker balance is the single source.

Before this fix, the handler called `storage.get_kr_stock_positions()`, a
method that has never existed on StorageService (there is no KR position
writer anywhere in the backend) — every call raised AttributeError, caught
and silently turned into `positions_data = []`. KR positions were therefore
ALWAYS empty regardless of actual broker holdings, while Operations '보유'
(app/api/routes/trading.py, backed by the same kt00004 get_account_balance())
showed the real numbers. This rewires GET /positions onto
`get_account_balance().holdings` — the exact same source and field mapping
Operations uses (kr_stocks/orders.py:63-76, trading.py:1388-1398) — so the
two surfaces can never diverge on quantity/avg/current price/P&L for the
same holding.

Direct-call style (no TestClient), matching test_kr_order_execution.py /
test_kr_trades.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.kr_stocks import positions as positions_mod
from services.kiwoom.models import Holding, OrderResponse


def _kiwoom(holdings=None):
    client = MagicMock()
    balance = MagicMock()
    balance.holdings = holdings or []
    client.get_account_balance = AsyncMock(return_value=balance)
    return client


def _holding(**overrides):
    fields = dict(
        stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
        avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
        evlu_pfls_amt=60000, evlu_pfls_rt=2.31,
    )
    fields.update(overrides)
    return Holding(**fields)


async def test_get_positions_returns_real_holdings_from_broker_balance():
    holding = _holding()
    client = _kiwoom([holding])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_positions()

    assert len(res.positions) == 1
    p = res.positions[0]
    # Same field mapping Operations '보유' uses off the same Holding model —
    # same ticker => same quantity/avg/current price, no divergence.
    assert p.stk_cd == "005930"
    assert p.stk_nm == "삼성전자"
    assert p.quantity == holding.hldg_qty == 10
    assert p.avg_entry_price == holding.avg_buy_prc == 260000
    assert p.current_price == holding.cur_prc == 266000
    client.get_account_balance.assert_awaited_once()


async def test_get_positions_unrealized_pnl_computed_from_holdings():
    """P&L is holdings-derived (broker-computed evlu_pfls_amt/rt on the
    Holding model), not an independently recomputed number that could drift
    from what Operations shows for the same holding."""
    holding = _holding(hldg_qty=10, avg_buy_prc=260000, cur_prc=266000,
                       evlu_amt=2660000, evlu_pfls_amt=60000, evlu_pfls_rt=2.31)
    client = _kiwoom([holding])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_positions()

    p = res.positions[0]
    assert p.unrealized_pnl == 60000
    assert p.unrealized_pnl_pct == 2.31
    assert res.total_pnl == 60000
    assert res.total_value_krw == 2660000  # sum of holdings' evlu_amt


async def test_get_positions_aggregates_totals_across_multiple_holdings():
    h1 = _holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                  avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                  evlu_pfls_amt=60000, evlu_pfls_rt=2.31)
    h2 = _holding(stk_cd="000660", stk_nm="SK하이닉스", hldg_qty=5,
                  avg_buy_prc=190000, cur_prc=185000, evlu_amt=925000,
                  evlu_pfls_amt=-25000, evlu_pfls_rt=-2.6)
    client = _kiwoom([h1, h2])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_positions()

    assert {p.stk_cd for p in res.positions} == {"005930", "000660"}
    assert res.total_value_krw == 2660000 + 925000
    assert res.total_pnl == 60000 - 25000
    total_cost = 10 * 260000 + 5 * 190000
    assert res.total_pnl_pct == (35000 / total_cost * 100)


async def test_get_positions_no_holdings_returns_empty_not_fabricated():
    client = _kiwoom([])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_positions()

    assert res.positions == []
    assert res.total_value_krw == 0
    assert res.total_pnl == 0
    assert res.total_pnl_pct == 0


async def test_get_positions_broker_failure_degrades_honestly():
    """Broker fetch failure -> honest empty portfolio, never a fabricated
    non-empty/non-zero response (the CRITICAL random-mock-data issue this
    repo already fixed elsewhere must not be reintroduced here)."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(side_effect=RuntimeError("kiwoom down"))

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_positions()

    assert res.positions == []
    assert res.total_value_krw == 0
    assert res.total_pnl == 0
    assert res.total_pnl_pct == 0


async def test_get_positions_client_construction_failure_degrades_honestly():
    """Even a failure at the singleton-client level (e.g. keys not
    configured) must degrade to the same honest-empty shape, not raise."""
    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(side_effect=RuntimeError("no keys configured"))):
        res = await positions_mod.get_positions()

    assert res.positions == []
    assert res.total_value_krw == 0


# -------------------------------------------
# P2 T1b: GET /positions/{stk_cd} (single) + POST /positions/{stk_cd}/close
#
# Before this fix both handlers called `storage.get_kr_stock_position()` /
# `storage.delete_kr_stock_position()`, methods that have never existed on
# StorageService (same root cause as the list handler above) — every
# lookup 404'd even for a ticker the list endpoint showed as held, and
# close_position's "delete a storage row" semantics were architecturally
# wrong for a KR position (broker balance, not a stored row). Both now
# source from the same `get_account_balance().holdings` the list handler
# uses, and close_position places a real full-quantity market SELL via
# KiwoomExecutionAdapter instead of fabricating a response.
# -------------------------------------------


async def test_get_position_returns_held_ticker_from_broker_balance():
    holding = _holding()
    client = _kiwoom([holding])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.get_position("005930")

    assert res.stk_cd == "005930"
    assert res.stk_nm == "삼성전자"
    assert res.quantity == holding.hldg_qty == 10
    assert res.avg_entry_price == holding.avg_buy_prc == 260000
    assert res.current_price == holding.cur_prc == 266000
    assert res.unrealized_pnl == holding.evlu_pfls_amt == 60000
    assert res.unrealized_pnl_pct == holding.evlu_pfls_rt == 2.31


async def test_get_position_unheld_ticker_returns_honest_404():
    client = _kiwoom([_holding(stk_cd="005930")])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        with pytest.raises(HTTPException) as exc_info:
            await positions_mod.get_position("000660")

    assert exc_info.value.status_code == 404


async def test_get_position_broker_failure_degrades_honestly():
    """Broker fetch failure -> honest 503, never a fabricated position."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(side_effect=RuntimeError("kiwoom down"))

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        with pytest.raises(HTTPException) as exc_info:
            await positions_mod.get_position("005930")

    assert exc_info.value.status_code == 503


@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
async def test_close_position_places_full_qty_market_sell(_chk):
    holding = _holding(stk_cd="005930", hldg_qty=10)
    client = _kiwoom([holding])
    client.place_sell_order = AsyncMock(
        return_value=OrderResponse(ord_no="C1", return_code=0, return_msg="정상")
    )
    client.place_buy_order = AsyncMock()

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.close_position("005930")

    client.place_sell_order.assert_awaited_once()
    kwargs = client.place_sell_order.await_args.kwargs
    assert kwargs["stk_cd"] == "005930"
    assert kwargs["qty"] == 10
    client.place_buy_order.assert_not_awaited()
    assert res.order_id == "C1"
    assert res.side == "sell"
    assert res.quantity == 10
    assert res.status == "pending"


@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
async def test_close_position_uses_fresh_balance_not_cache(_chk):
    """close_position must fetch account balance with use_cache=False —
    the default 30s cache (client.py:700-716) can understate a position
    that grew via a concurrent ADD in the last 30s, so a "close full
    position" order would only sell the stale (smaller) quantity and
    silently leave a partial position open."""
    holding = _holding(stk_cd="005930", hldg_qty=25)
    client = _kiwoom([holding])
    client.place_sell_order = AsyncMock(
        return_value=OrderResponse(ord_no="C2", return_code=0, return_msg="정상")
    )
    client.place_buy_order = AsyncMock()

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.close_position("005930")

    client.get_account_balance.assert_awaited_once_with(use_cache=False)
    kwargs = client.place_sell_order.await_args.kwargs
    assert kwargs["qty"] == 25  # sells against the FRESH holding qty
    assert res.quantity == 25


@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
async def test_close_position_unheld_ticker_returns_honest_404(_chk):
    client = _kiwoom([_holding(stk_cd="005930")])

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        with pytest.raises(HTTPException) as exc_info:
            await positions_mod.close_position("000660")

    assert exc_info.value.status_code == 404


@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
async def test_close_position_broker_rejection_is_not_reported_as_success(_chk):
    """A rejected sell order (return_code != 0) must never surface as a
    fabricated completed/pending success."""
    holding = _holding(stk_cd="005930", hldg_qty=10)
    client = _kiwoom([holding])
    client.place_sell_order = AsyncMock(
        return_value=OrderResponse(ord_no="", return_code=1, return_msg="주문거부")
    )

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        res = await positions_mod.close_position("005930")

    assert res.status not in ("pending", "completed")


@patch("app.api.routes.kr_stocks.positions.check_kiwoom_api_keys")
async def test_close_position_broker_balance_failure_degrades_honestly(_chk):
    """Failure to even look up the holding -> honest 503, no fake order."""
    client = MagicMock()
    client.get_account_balance = AsyncMock(side_effect=RuntimeError("kiwoom down"))

    with patch.object(positions_mod, "get_shared_kiwoom_client_async",
                       AsyncMock(return_value=client)):
        with pytest.raises(HTTPException) as exc_info:
            await positions_mod.close_position("005930")

    assert exc_info.value.status_code == 503
