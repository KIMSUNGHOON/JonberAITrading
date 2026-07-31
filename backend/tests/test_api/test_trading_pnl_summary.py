"""GET /api/trading/pnl-summary 테스트.

두 섹션이 독립 소스다: `realized`는 브로커 ka10074, `equity_return`은 로컬
daily_perf_snapshot. 하나가 실패해도 다른 하나는 정상 값을 반환하고 실패한
섹션만 null + errors가 채워진다(0/가짜 값 위장 금지).

미실현손익은 이 엔드포인트에 없다 — PositionsPanel이 이미 폴링 중인
/operations 데이터에서 프론트가 합산한다(브로커 중복 호출 회피, 계획 문서의
"스펙과의 의도적 차이" 절 참조).
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes import trading as trading_mod
from services.kiwoom.models import DailyRealizedPnlRow, RealizedPnl


def _row(dt, sell_pnl):
    return DailyRealizedPnlRow(
        dt=dt, sell_pnl=sell_pnl, sell_amount=0, buy_amount=0, commission=0, tax=0
    )


def _kiwoom(daily=None, pnl_error=None):
    client = MagicMock()
    if pnl_error is not None:
        client.get_realized_pnl = AsyncMock(side_effect=pnl_error)
    else:
        client.get_realized_pnl = AsyncMock(
            return_value=RealizedPnl(
                strt_dt="20260701", end_dt="20260731", daily=daily or []
            )
        )
    return client


def _storage(snapshots=None):
    storage = MagicMock()
    # 실제 구현과 같이 최신순(내림차순)으로 돌려준다
    storage.get_daily_perf_snapshots = AsyncMock(
        return_value=list(reversed(snapshots or []))
    )
    return storage


SNAPS = [
    {"trade_date": "2026-07-24", "equity": 495_435_889},
    {"trade_date": "2026-07-30", "equity": 497_691_136},
    {"trade_date": "2026-07-31", "equity": 497_760_401},
]
TODAY = date(2026, 7, 31)


async def _call(client, storage, base=500_000_000):
    with patch.object(
        trading_mod, "get_shared_kiwoom_client_async", AsyncMock(return_value=client)
    ), patch.object(
        trading_mod, "get_storage_service", AsyncMock(return_value=storage)
    ), patch.object(trading_mod, "_pnl_summary_today", lambda: TODAY):
        return await trading_mod.get_pnl_summary(base=base)


async def test_buckets_use_broker_realized_and_local_equity():
    client = _kiwoom(daily=[_row("20260727", 418_950), _row("20260731", 984_533)])
    res = await _call(client, _storage(SNAPS))

    assert res.errors == {}
    assert res.as_of == "2026-07-31"
    assert res.realized == {
        "day": 984_533, "week": 1_403_483, "month": 1_403_483, "total": 1_403_483
    }
    assert round(res.equity_return["day"].pct, 4) == 0.0139
    assert res.equity_return["day"].basis == "prior_close"
    assert round(res.equity_return["week"].pct, 4) == 0.4692
    assert res.equity_return["week"].basis == "prior_close"
    assert round(res.equity_return["month"].pct, 4) == -0.4479
    assert res.equity_return["month"].basis == "base_asset"


async def test_broker_called_exactly_once_for_all_four_buckets():
    client = _kiwoom(daily=[_row("20260731", 1)])
    await _call(client, _storage(SNAPS))
    assert client.get_realized_pnl.await_count == 1


async def test_broker_window_is_the_widest_bucket_start():
    # 한 번의 호출로 네 버킷을 모두 덮어야 하므로 창의 시작은 가장 이른 버킷
    # 시작이다. 여기서는 월 시작(20260701)이 데이터 시작(20260724)보다 이르다.
    client = _kiwoom(daily=[_row("20260731", 1)])
    await _call(client, _storage(SNAPS))
    kwargs = client.get_realized_pnl.await_args.kwargs
    assert kwargs["strt_dt"] == "20260701"
    assert kwargs["end_dt"] == "20260731"


async def test_broker_failure_degrades_only_the_realized_section():
    client = _kiwoom(pnl_error=RuntimeError("ka10074 boom"))
    res = await _call(client, _storage(SNAPS))

    assert res.realized is None
    assert "ka10074 boom" in res.errors["realized"]
    assert res.equity_return is not None  # 살아 있다
    assert round(res.equity_return["day"].pct, 4) == 0.0139


async def test_empty_snapshots_degrade_only_the_equity_section():
    client = _kiwoom(daily=[_row("20260731", 984_533)])
    res = await _call(client, _storage([]))

    assert res.equity_return is None
    assert "equity_return" in res.errors
    assert res.realized is not None
    assert res.realized["day"] == 984_533


async def test_client_failure_degrades_both_sections_without_raising():
    with patch.object(
        trading_mod,
        "get_shared_kiwoom_client_async",
        AsyncMock(side_effect=RuntimeError("no client")),
    ), patch.object(
        trading_mod, "get_storage_service", AsyncMock(return_value=_storage([]))
    ), patch.object(trading_mod, "_pnl_summary_today", lambda: TODAY):
        res = await trading_mod.get_pnl_summary(base=500_000_000)

    assert res.realized is None
    assert res.equity_return is None
    assert "realized" in res.errors and "equity_return" in res.errors
