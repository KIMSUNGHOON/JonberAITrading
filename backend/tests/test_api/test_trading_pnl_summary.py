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
    assert res.equity_return["day"].trade_date == "2026-07-31"
    assert round(res.equity_return["week"].pct, 4) == 0.4692
    assert res.equity_return["week"].basis == "prior_close"
    assert round(res.equity_return["month"].pct, 4) == -0.4479
    assert res.equity_return["month"].basis == "base_asset"
    # data_start(07-24)가 이번 달 1일(07-01)보다 늦으므로 total은 month와
    # 같은 창(07-01~07-31)이다 — total이 month보다 좁아지는 모순 방지
    # (리뷰 항목 6, period_bounds의 총계 폭 보장).
    assert round(res.equity_return["total"].pct, 4) == -0.4479
    assert res.equity_return["total"].basis == "base_asset"


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
    # 오늘 날짜로 물러선다 — 평가금 데이터가 아예 없어 "실제로 반영된
    # 데이터 일자"를 알 수 없기 때문(리뷰 항목 1의 as_of 규칙).
    assert res.as_of == "2026-07-31"


async def test_empty_snapshots_error_message_does_not_claim_an_unverified_cause():
    """리뷰 항목 5: storage.get_daily_perf_snapshots는 내부에서 모든 예외를
    삼키고 빈 리스트를 반환한다(storage_service.py) — 그래서 이 라우트의
    try/except는 절대 발동하지 않고, "행이 아직 없음"과 "조회가 사실은
    실패함"을 구분할 수 없다. 확인하지 않은 원인("스냅샷 없음")을 단정하는
    메시지 대신, 두 가능성을 모두 인정하는 메시지여야 한다."""
    client = _kiwoom(daily=[_row("20260731", 984_533)])
    res = await _call(client, _storage([]))

    msg = res.errors["equity_return"]
    assert "평가금 스냅샷 없음" in msg
    assert "조회 실패" in msg  # 원인을 안다고 주장하지 않는다


async def test_realized_total_marks_month_scope_when_data_start_unknown():
    """리뷰 항목 5b: data_start를 모르면(스냅샷이 없거나 최이른 행이
    손상됨) bounds()의 total은 이번 달 1일로 물러선다 — 그런데
    realized["total"]은 여전히 값이 채워지므로(실현손익은 브로커 조회라
    로컬 스냅샷 유무와 무관), "누적" 라벨 아래 월간 합계가 표시자
    없이 노출되면 안 된다."""
    client = _kiwoom(daily=[_row("20260727", 418_950), _row("20260731", 984_533)])
    res = await _call(client, _storage([]))  # 스냅샷 없음 -> data_start=None

    assert res.realized is not None
    assert "realized_total_scope" in res.errors


async def test_realized_total_scope_not_marked_when_data_start_known():
    client = _kiwoom(daily=[_row("20260727", 418_950), _row("20260731", 984_533)])
    res = await _call(client, _storage(SNAPS))  # data_start=20260724

    assert "realized_total_scope" not in res.errors


async def test_malformed_earliest_trade_date_falls_back_to_month_start():
    """리뷰 항목 4 재현: 가장 이른 스냅샷의 trade_date가 예상 밖 포맷
    (ISO datetime 등)이면 data_start로 채택하면 안 된다. 이 가드가 없으면
    문자열이 비교에 그대로 섞여 들어가 total의 basis/수익률이 조용히
    달라진다(리뷰: -0.4479%가 -0.4679%로, basis가 prior_close로 바뀜).
    equity_return_for_period가 스냅샷 행에 이미 쓰는 것과 같은
    len==8+isdigit 가드를 data_start 추출에도 적용해야 한다."""
    snaps = [
        {"trade_date": "2026-07-16T00:00:00", "equity": 495_000_000},  # 손상된 최이른 행
        {"trade_date": "2026-07-30", "equity": 497_691_136},
        {"trade_date": "2026-07-31", "equity": 497_760_401},
    ]
    client = _kiwoom(daily=[_row("20260731", 984_533)])
    res = await _call(client, _storage(snaps))

    # month_start(07-01)로 안전하게 물러섰다는 신호: 오염된 07-16을
    # data_start로 오인했을 때와 달리 basis가 base_asset을 유지하고,
    # test_buckets_use_broker_realized_and_local_equity의 정상 month
    # 폴백과 값이 같다.
    assert res.equity_return["total"].basis == "base_asset"
    assert round(res.equity_return["total"].pct, 4) == -0.4479
    assert "realized_total_scope" in res.errors  # data_start를 못 뽑았으니 표시됨


async def test_intraday_no_snapshot_row_today_degrades_day_week_month_not_zero():
    """리뷰 CRITICAL 재현: 월요일 장중, 최신 스냅샷이 지난 금요일(07-31)
    뿐이면 일/주/월 버킷 모두 오늘자 행이 없어 None(프론트 '—')이어야
    한다 — 0.0000%로 위장하면 안 된다. total은 데이터 시작(07-24)부터
    시작해 여전히 계산 가능하다(어제까지의 실적, base_asset 폴백)."""
    client = _kiwoom(daily=[_row("20260803", -3_500_000)])
    with patch.object(
        trading_mod, "get_shared_kiwoom_client_async", AsyncMock(return_value=client)
    ), patch.object(
        trading_mod, "get_storage_service", AsyncMock(return_value=_storage(SNAPS))
    ), patch.object(trading_mod, "_pnl_summary_today", lambda: date(2026, 8, 3)):
        res = await trading_mod.get_pnl_summary(base=500_000_000)

    assert res.equity_return is not None  # total은 살아있다(섹션 자체는 안 죽음)
    assert "day" not in res.equity_return
    assert "week" not in res.equity_return
    assert "month" not in res.equity_return
    assert "total" in res.equity_return
    # as_of는 오늘(08-03)이 아니라 실제로 반영된 데이터 일자(07-31)다 —
    # 장중 수익률이 전부 직전 종가 기준임을 화면에서 알 수 있어야 한다.
    assert res.as_of == "2026-07-31"
    # 실현손익 섹션은 독립적으로 살아있다 — equity만 강등됐다고 realized까지
    # 죽지 않는다.
    assert res.realized is not None
    assert res.realized["day"] == -3_500_000


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
