"""Task 8: 08:05 일일 사이클 + 초과분 토론 주입 + 브리핑 노출.

브리프: .superpowers/sdd/2026-08-07-regime-aware-exposure/task-8-brief.md

강제 매도 없음 — 초과 사실만 토론 프롬프트에 주고 종목별 판단은 패널에게
맡긴다(사용자 결정, 2026-08-07). 이 파일은 그 배선 자체를 확인한다;
`services/agent_chat/coordinator.py`의 실제 프롬프트 도달 배선은
`tests/test_services/test_agent_chat/test_exposure_context_injection.py`가
따로 잠근다(C2/US신호 배선 테스트와 동일 분리 패턴).
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.telegram.briefing import format_regime
from services.trading.regime_judge import run_daily_regime_cycle

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


@pytest.mark.asyncio
async def test_cycle_skips_on_non_trading_day():
    """휴장일에는 판정하지 않는다."""
    svc = MagicMock()
    svc.is_trading_day = MagicMock(return_value=False)
    judge = AsyncMock()
    with patch("services.krx_holiday.get_holiday_service", AsyncMock(return_value=svc)), \
         patch("services.trading.regime_judge.judge_regime", judge):
        await run_daily_regime_cycle()
    judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_holiday_service_contract_canary():
    """실제 이름은 is_trading_day이고 get_holiday_service는 async다.

    2026-08-06에 is_business_day(존재하지 않는 이름)를 부르고 await를
    빠뜨려, 넓은 except가 둘 다 삼키는 바람에 휴장일 스킵이 한 번도
    작동하지 않았다. 이 테스트는 목이 아니라 실물 계약을 본다."""
    import inspect

    from services.krx_holiday import get_holiday_service

    assert inspect.iscoroutinefunction(get_holiday_service)
    svc = await get_holiday_service()
    assert hasattr(svc, "is_trading_day")
    assert not hasattr(svc, "is_business_day")


@pytest.mark.asyncio
async def test_cycle_applies_slots_after_judging():
    svc = MagicMock()
    svc.is_trading_day = MagicMock(return_value=True)
    coord = MagicMock()
    coord.apply_regime_slots = AsyncMock(return_value={"max_open_positions": 11})
    with patch("services.krx_holiday.get_holiday_service", AsyncMock(return_value=svc)), \
         patch("services.trading.regime_judge.judge_regime",
               AsyncMock(return_value={"regime": "bear"})), \
         patch("services.trading.regime_judge._get_trading_coordinator",
               AsyncMock(return_value=coord)):
        await run_daily_regime_cycle()
    coord.apply_regime_slots.assert_awaited_once()


@pytest.mark.asyncio
async def test_cycle_never_raises():
    with patch("services.krx_holiday.get_holiday_service",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("services.trading.regime_judge.judge_regime",
               AsyncMock(side_effect=RuntimeError("boom"))):
        await run_daily_regime_cycle()  # 예외가 나가면 이 테스트가 실패한다


def test_format_regime_absent_is_explicit():
    """행이 없으면 '판정 없음'이라고 쓴다. 조용히 중립을 보여주지 않는다."""
    out = format_regime(None)
    assert "판정 없음" in out
    assert "neutral" not in out


def test_format_regime_shows_label_target_and_driver():
    out = format_regime({
        "regime": "bear", "confidence": 0.72,
        "rationale": "EWY -2.97%로 외국인 이탈",
        "key_drivers": ["EWY -2.97%"],
        "anchor_target_pct": 0.55, "effective_target_pct": 0.2355,
        "degraded": ["index_vol_insufficient"],
        "trade_date": date.today().isoformat(),
    })
    assert "bear" in out
    assert "23.6" in out or "23.5" in out   # effective
    assert "55" in out                       # anchor
    assert "EWY" in out
    assert "index_vol_insufficient" in out


# ---------------------------------------------------------------------------
# `_get_trading_coordinator` 계약 카나리
# ---------------------------------------------------------------------------
# 브리프 원문 Step 3은 `from app.core.dependencies import
# get_trading_coordinator`를 가리켰다 -- 이 리포에 `app/core/dependencies.py`
# 는 없다(있는 것은 `app/dependencies.py`, ExecutionCoordinator 싱글턴은
# `get_trading_coordinator`). Task 5/7이 각각 `create_messages` 시그니처와
# `_persist_fields` 시그니처에서 같은 종류의 "계획 원문이 틀렸다"를 만났던
# 것과 동일한 패턴이라 실물 계약으로 고정한다 -- 목으로 감싸면(위
# test_cycle_applies_slots_after_judging처럼) import 경로가 틀려도 항상
# 통과한다.


@pytest.mark.asyncio
async def test_get_trading_coordinator_uses_the_real_import_path():
    from services.trading.regime_judge import _get_trading_coordinator

    coord = await _get_trading_coordinator()
    assert hasattr(coord, "apply_regime_slots")


# ---------------------------------------------------------------------------
# start_regime_scheduler — 킬스위치
# ---------------------------------------------------------------------------


def test_scheduler_off_when_kill_switch_disabled():
    from services.trading.regime_judge import start_regime_scheduler

    # `start_regime_scheduler`는 `from app.config import get_settings`를
    # 함수 본문에서 지역 임포트한다(브리프 원문 그대로) -- 그래서 패치
    # 대상은 `services.trading.regime_judge.get_settings`(모듈 속성으로
    # 존재하지 않음)가 아니라 원본인 `app.config.get_settings`다.
    with patch("app.config.get_settings") as gs:
        gs.return_value.REGIME_EXPOSURE_ENABLED = False
        assert start_regime_scheduler() is None


@pytest.mark.asyncio
async def test_scheduler_starts_when_kill_switch_enabled():
    """`AsyncIOScheduler.start()`는 실행 중인 이벤트 루프를 요구한다 --
    실제 부팅 경로(`app/main.py`의 lifespan)는 항상 루프 안이므로 async
    테스트로 맞춘다."""
    from services.trading.regime_judge import start_regime_scheduler

    scheduler = None
    try:
        with patch("app.config.get_settings") as gs:
            gs.return_value.REGIME_EXPOSURE_ENABLED = True
            scheduler = start_regime_scheduler()
        assert scheduler is not None
        assert scheduler.get_job("regime_daily_cycle") is not None
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# format_exposure_context — 순수 함수 (services.agent_chat.coordinator)
# ---------------------------------------------------------------------------
# 실제 프롬프트 도달 배선은 test_exposure_context_injection.py가 따로 본다.
# 여기서는 렌더링 규칙만 고정한다: 목표 없음=빈 문자열, 초과 여부에 따라
# "초과 …%p — 신규 진입은 게이트가 막고 있다" 문구의 유무가 갈린다.


class TestFormatExposureContext:
    def test_no_target_is_empty_string(self):
        from services.agent_chat.coordinator import format_exposure_context

        assert format_exposure_context(None, 0.30, "bear") == ""

    def test_under_target_has_no_excess_marker(self):
        from services.agent_chat.coordinator import format_exposure_context

        out = format_exposure_context(0.30, 0.20, "neutral")
        assert "초과" not in out
        assert "30.0%" in out
        assert "20.0%" in out
        assert "neutral" in out

    def test_over_target_flags_excess_and_gate(self):
        from services.agent_chat.coordinator import format_exposure_context

        out = format_exposure_context(0.20, 0.35, "bear")
        assert "초과 15.0%p" in out
        assert "게이트가 막고 있다" in out

    def test_regime_none_omits_label(self):
        from services.agent_chat.coordinator import format_exposure_context

        out = format_exposure_context(0.30, 0.20, None)
        assert "레짐" not in out

    def test_does_not_prescribe_which_ticker_to_sell(self):
        """사용자 결정(2026-08-07): 초과 사실만 준다. 종목명·매도 지시가
        섞여 들어가면 안 된다 — 이 함수는 target/actual/regime만 받는다."""
        import inspect

        from services.agent_chat.coordinator import format_exposure_context

        params = list(inspect.signature(format_exposure_context).parameters)
        assert params == ["target_pct", "actual_pct", "regime"]
