"""GET /api/trading/performance aggregate endpoint tests (TUX4).

성과 스냅샷은 두 개의 독립 브로커 호출로 구성된다: ka10074(기간 실현손익) →
`pnl` 섹션, kt00004(계좌 평가액) → `asset` 섹션. 하나가 실패해도 다른 하나는
정상 반환하고, 실패한 섹션만 null + errors 사유가 채워진다(/operations와
동일한 정직 강등 — 0/가짜 값 위장 금지).
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes import trading as trading_mod
from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl


def _pnl(daily=None, **totals):
    return RealizedPnl(strt_dt="20260613", end_dt="20260713", daily=daily or [], **totals)


def _row(dt, sell_pnl, sell_amount=1_000_000, commission=100, tax=200):
    return DailyRealizedPnlRow(
        dt=dt, sell_pnl=sell_pnl, sell_amount=sell_amount,
        buy_amount=0, commission=commission, tax=tax,
    )


def _kiwoom(pnl=None, balance_total_value=None, pnl_error=None, balance_error=None):
    client = MagicMock()
    if pnl_error is not None:
        client.get_realized_pnl = AsyncMock(side_effect=pnl_error)
    else:
        client.get_realized_pnl = AsyncMock(return_value=pnl or _pnl())

    if balance_error is not None:
        client.get_account_balance = AsyncMock(side_effect=balance_error)
    else:
        balance = MagicMock()
        balance.total_value = balance_total_value if balance_total_value is not None else 500_000_000
        client.get_account_balance = AsyncMock(return_value=balance)
    return client


async def test_performance_aggregates_pnl_and_asset_sections():
    pnl = _pnl(
        daily=[
            _row("20260706", sell_pnl=50_000),
            _row("20260707", sell_pnl=-30_000),
        ],
        realized_pnl=20_000, commission=200, tax=400,
    )
    client = _kiwoom(pnl=pnl, balance_total_value=510_000_000)

    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_performance(base=500_000_000, start="20260706", end="20260707")

    assert res.errors == {}
    assert res.pnl.realized_pnl_total == 20_000
    assert res.pnl.net_pnl == 20_000 - 200 - 400
    assert res.pnl.trade_days == 2
    assert res.pnl.win_days == 1 and res.pnl.loss_days == 1
    assert res.pnl.win_rate_pct == 50.0
    assert [d.dt for d in res.pnl.daily] == ["20260706", "20260707"]
    assert res.pnl.daily[0].pnl == 50_000 and res.pnl.daily[0].cumulative_pnl == 50_000
    assert res.pnl.daily[1].pnl == -30_000 and res.pnl.daily[1].cumulative_pnl == 20_000

    assert res.asset.current_asset == 510_000_000
    assert res.asset.base_asset == 500_000_000
    assert res.asset.cumulative_return_pct == 2.0


async def test_performance_pnl_failure_degrades_honestly_asset_still_returned():
    client = _kiwoom(pnl_error=RuntimeError("kiwoom down"), balance_total_value=500_000_000)

    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_performance(base=500_000_000)

    assert res.pnl is None
    assert "kiwoom down" in res.errors["pnl"]
    assert res.asset is not None
    assert res.asset.current_asset == 500_000_000
    assert "asset" not in res.errors


async def test_performance_asset_failure_degrades_honestly_pnl_still_returned():
    pnl = _pnl(daily=[_row("20260706", sell_pnl=10_000)], realized_pnl=10_000)
    client = _kiwoom(pnl=pnl, balance_error=RuntimeError("account down"))

    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_performance(base=500_000_000)

    assert res.asset is None
    assert "account down" in res.errors["asset"]
    assert res.pnl is not None
    assert res.pnl.realized_pnl_total == 10_000
    assert "pnl" not in res.errors


async def test_performance_client_unavailable_degrades_both_sections():
    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(side_effect=RuntimeError("no credentials"))):
        res = await trading_mod.get_performance(base=500_000_000)

    assert res.pnl is None and res.asset is None
    assert "no credentials" in res.errors["pnl"]
    assert "no credentials" in res.errors["asset"]


async def test_performance_no_base_asset_returns_none_cumulative_return():
    client = _kiwoom(balance_total_value=500_000_000)

    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_performance(base=None)

    assert res.asset.cumulative_return_pct is None
    assert res.asset.base_asset is None


async def test_performance_empty_period_reports_no_trades_not_fabricated_zero():
    client = _kiwoom(pnl=_pnl(daily=[], realized_pnl=0), balance_total_value=500_000_000)

    with patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_performance(base=500_000_000)

    assert res.pnl.trade_days == 0
    assert res.pnl.win_rate_pct is None  # 승부 없음 — 0%가 아니라 미정
    assert res.pnl.daily == []
