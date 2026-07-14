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

from app.api.routes.kr_stocks import positions as positions_mod
from services.kiwoom.models import Holding


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
