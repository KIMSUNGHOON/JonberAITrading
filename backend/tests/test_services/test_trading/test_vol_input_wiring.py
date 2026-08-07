from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import get_storage_service

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _llm(regime="bear", confidence=0.72):
    """`test_regime_judge.py`의 동일 헬퍼와 같은 모양(9곳 전부가 이 관행을
    쓴다) -- `get_llm_provider`를 패치하지 않으면 이 샌드박스에 설치된
    `claude` CLI로 라우터가 실제 LLM 호출에 폴백해 성공해버려(비용·
    비결정성·오프라인 실패), `judge_regime`이 `compute_regime_target`에
    도달하는지가 우연에 좌우된다(리뷰 발견, 2026-08-08)."""
    provider = MagicMock()
    provider.generate_structured = AsyncMock(
        return_value={
            "regime": regime,
            "confidence": confidence,
            "rationale": "EWY -2.97%로 외국인 이탈",
            "key_drivers": ["EWY -2.97%"],
        }
    )
    return provider


@pytest.mark.asyncio
async def test_cycle_refreshes_index_before_judging():
    """수집이 판정보다 먼저여야 그날 종가가 변동성에 반영된다."""
    order = []
    refresh = AsyncMock(side_effect=lambda *a, **k: order.append("refresh"))
    judge = AsyncMock(side_effect=lambda *a, **k: order.append("judge"))
    svc = MagicMock()
    svc.is_trading_day = MagicMock(return_value=True)
    coord = MagicMock()
    coord.apply_regime_slots = AsyncMock(return_value=None)
    coord.risk_params = MagicMock(target_vol_pct=18.0, vol_multiplier_min=0.5)

    from services.trading import regime_judge as rj

    with patch("services.krx_holiday.get_holiday_service", AsyncMock(return_value=svc)), \
         patch.object(rj, "refresh_index_daily", refresh), \
         patch.object(rj, "judge_regime", judge), \
         patch.object(rj, "_get_trading_coordinator", AsyncMock(return_value=coord)):
        await rj.run_daily_regime_cycle()

    assert order == ["refresh", "judge"], f"순서가 틀렸다: {order}"


@pytest.mark.asyncio
async def test_judge_uses_index_daily_not_spy():
    """SPY(macro_snapshot)가 아니라 KOSPI(index_daily)를 봐야 한다."""
    storage = await get_storage_service()
    await storage.upsert_index_daily(
        [(f"2026-07-{d:02d}", 100.0 * (1.064 if d % 2 else 0.936))
         for d in range(1, 22)],
        source="test",
    )
    seen = {}

    def _capture(**kw):
        seen.update(kw)
        raise RuntimeError("stop here")

    from services.trading import regime_judge as rj

    # ⚠️ `judge_regime`은 첫 줄에서 `refresh_macro_snapshot()`을 부르고
    # 실패하면 조기 반환한다 — 패치하지 않으면 compute_regime_target에
    # 도달조차 못 하고 이 테스트는 공허해진다. `get_llm_provider`도 같은
    # 이유로 패치한다 -- 진짜 LLM을 부르면 도달 여부가 우연에 좌우된다.
    _snap = {"quotes": {"SPY": {"chg_pct": -0.16, "prev_close": 769.8}}, "missing": []}
    with patch.object(rj, "refresh_macro_snapshot", AsyncMock(return_value=_snap)), \
         patch.object(rj, "get_llm_provider", return_value=_llm()), \
         patch.object(rj, "compute_regime_target", _capture):
        await rj.judge_regime()

    assert "index_returns" in seen
    assert len(seen["index_returns"]) == 20, "종가 21개 → 수익률 20개"
    assert "series_stale" in seen


@pytest.mark.asyncio
async def test_judge_passes_the_knobs_through():
    from services.trading import regime_judge as rj

    seen = {}

    def _capture(**kw):
        seen.update(kw)
        raise RuntimeError("stop here")

    # 위와 같은 이유로 refresh_macro_snapshot과 get_llm_provider를 패치해야
    # 도달한다.
    _snap = {"quotes": {"SPY": {"chg_pct": -0.16, "prev_close": 769.8}}, "missing": []}
    with patch.object(rj, "refresh_macro_snapshot", AsyncMock(return_value=_snap)), \
         patch.object(rj, "get_llm_provider", return_value=_llm()), \
         patch.object(rj, "compute_regime_target", _capture):
        await rj.judge_regime(target_vol_pct=33.0, vol_multiplier_min=0.25)

    assert seen.get("target_vol_pct") == pytest.approx(33.0)
    assert seen.get("vol_multiplier_min") == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_cycle_reads_knobs_from_the_coordinator():
    """judge_regime은 코디네이터를 모른다 — 사이클이 읽어서 넘긴다."""
    svc = MagicMock()
    svc.is_trading_day = MagicMock(return_value=True)
    coord = MagicMock()
    coord.apply_regime_slots = AsyncMock(return_value=None)
    coord.risk_params = MagicMock(target_vol_pct=25.0, vol_multiplier_min=0.35)
    judge = AsyncMock(return_value=None)

    from services.trading import regime_judge as rj

    with patch("services.krx_holiday.get_holiday_service", AsyncMock(return_value=svc)), \
         patch.object(rj, "refresh_index_daily", AsyncMock(return_value=40)), \
         patch.object(rj, "judge_regime", judge), \
         patch.object(rj, "_get_trading_coordinator", AsyncMock(return_value=coord)):
        await rj.run_daily_regime_cycle()

    judge.assert_awaited_once()
    kw = judge.await_args.kwargs
    assert kw.get("target_vol_pct") == pytest.approx(25.0)
    assert kw.get("vol_multiplier_min") == pytest.approx(0.35)
