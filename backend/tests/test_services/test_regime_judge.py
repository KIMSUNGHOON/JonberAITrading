from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import get_storage_service
from services.trading.regime_judge import get_effective_target, judge_regime

pytestmark = pytest.mark.usefixtures("isolated_storage_service")

_SNAPSHOT = {
    "quotes": {"EWY": {"chg_pct": -2.97, "prev_close": 169.1},
               "SPY": {"chg_pct": -0.16, "prev_close": 769.8}},
    "missing": [],
}


def _healthy_account():
    """계좌 조회가 **정상**인 상태를 만든다.

    이 패치가 없으면 `_portfolio_state()`가 실제 키움 호출을 시도해 인증
    오류로 죽고 `portfolio_state_unavailable`이 붙는다 -- 2026-08-07의 I-2
    수정 전에는 그 실패가 조용해서(숫자를 안 바꿔서) "happy path" 테스트가
    사실은 저하 경로를 지나면서도 통과했다. 이제는 실패가 결과를 바꾸므로
    의도한 경로를 명시적으로 만들어 줘야 한다.
    """
    balance = MagicMock(evlu_amt=1_000_000.0, d2_ord_psbl_amt=500_000.0)
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=balance)
    return patch(
        "app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    )


def _llm(regime="bear", confidence=0.72):
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
async def test_happy_path_persists_regime_and_target():
    with _healthy_account(), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=_llm()):
        out = await judge_regime()

    assert out is not None
    assert out["regime"] == "bear"
    assert out["anchor_target_pct"] == pytest.approx(0.55)

    storage = await get_storage_service()
    row = await storage.get_latest_regime_judgment()
    assert row["regime"] == "bear"
    assert row["rationale"].startswith("EWY")


@pytest.mark.asyncio
async def test_llm_failure_carries_previous_judgment_forward():
    """직전 판정을 유지한다. 중간값(neutral)을 새로 만들어내지 않는다."""
    storage = await get_storage_service()
    await storage.insert_regime_judgment(
        trade_date=(date.today() - timedelta(days=1)).isoformat(),
        regime="bull", confidence=0.9, rationale="어제", key_drivers=[],
        anchor_target_pct=0.80, effective_target_pct=0.40,
        prev_effective_pct=0.25, degraded=[], macro_snapshot_id=None,
    )
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=RuntimeError("llm down"))

    with _healthy_account(), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=provider):
        out = await judge_regime()

    assert out is not None
    assert out["regime"] == "bull", "직전 판정이 이어져야 한다"
    assert "llm_unavailable" in out["degraded"]


@pytest.mark.asyncio
async def test_unparseable_label_carries_forward_and_is_degraded():
    """이름대로: 이어받을 직전 판정이 있어야 '이어받기'가 성립한다."""
    storage = await get_storage_service()
    await storage.insert_regime_judgment(
        trade_date=(date.today() - timedelta(days=1)).isoformat(),
        regime="bull", confidence=0.9, rationale="어제", key_drivers=[],
        anchor_target_pct=0.80, effective_target_pct=0.40,
        prev_effective_pct=0.25, degraded=[], macro_snapshot_id=None,
    )
    with _healthy_account(), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider",
               return_value=_llm(regime="슈퍼강세")):
        out = await judge_regime()
    assert out is not None
    assert out["regime"] == "bull", "직전 판정이 이어져야 한다"
    assert "regime_unparseable" in out["degraded"]


@pytest.mark.asyncio
async def test_unparseable_label_without_prior_writes_nothing():
    """라벨이 이상하고 직전 판정도 없으면 -- bear조차 폴백으로 쓰지 않는다.
    임의의 숫자를 만들면 판정 실패가 오히려 노출도 상한을 열 수 있다
    (예: 실제 비중 13%에서 bear 램프면 28% > 기존 슬롯 천장 21%). 행을 안
    적어야 게이트가 검사를 건너뛰고 기존 천장이 그대로 남는다."""
    with patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider",
               return_value=_llm(regime="슈퍼강세")):
        out = await judge_regime()
    assert out is None
    storage = await get_storage_service()
    assert await storage.get_latest_regime_judgment() is None


@pytest.mark.asyncio
async def test_no_snapshot_writes_nothing():
    """매크로가 없으면 판정하지 않는다 — 입력 없이 내린 판정은 근거가 없다."""
    with patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=None)):
        assert await judge_regime() is None
    storage = await get_storage_service()
    assert await storage.get_latest_regime_judgment() is None


@pytest.mark.asyncio
async def test_effective_target_is_none_when_no_judgment():
    """부재는 None이다 — 게이트가 이걸 보고 검사를 건너뛴다."""
    assert await get_effective_target() is None


@pytest.mark.asyncio
async def test_effective_target_expires_after_max_age():
    storage = await get_storage_service()
    stale = (date.today() - timedelta(days=6)).isoformat()
    await storage.insert_regime_judgment(
        trade_date=stale, regime="bull", confidence=0.9, rationale="", key_drivers=[],
        anchor_target_pct=0.80, effective_target_pct=0.80,
        prev_effective_pct=0.65, degraded=[], macro_snapshot_id=None,
    )
    assert await get_effective_target() is None, "만료된 판정이 노출도를 열면 안 된다"


@pytest.mark.asyncio
async def test_effective_target_returns_fresh_value():
    storage = await get_storage_service()
    await storage.insert_regime_judgment(
        trade_date=date.today().isoformat(), regime="bear", confidence=0.7,
        rationale="", key_drivers=[], anchor_target_pct=0.55,
        effective_target_pct=0.2355, prev_effective_pct=0.0855,
        degraded=[], macro_snapshot_id=None,
    )
    assert await get_effective_target() == pytest.approx(0.2355)


@pytest.mark.asyncio
async def test_persist_failure_returns_none_and_does_not_claim_success():
    """insert_regime_judgment는 실패-무해(False만 반환, raise 안 함)다.
    judge_regime이 반환값을 확인하지 않으면 DB 쓰기가 실패해도
    "regime_judged"를 로그하고 성공 dict를 돌려주는 거짓 보고를 한다
    (Task 2에서 동일한 결함이 리뷰에 걸렸다). 반환값을 검사해 False면
    경고를 남기고 None을 돌려줘야 한다."""
    storage = await get_storage_service()
    with _healthy_account(), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=_llm()), \
         patch.object(storage, "insert_regime_judgment", AsyncMock(return_value=False)):
        out = await judge_regime()

    assert out is None, "저장이 실패했는데 성공 dict를 돌려주면 거짓 보고다"
    assert await storage.get_latest_regime_judgment() is None


async def _seed_prior(effective: float = 0.20):
    storage = await get_storage_service()
    await storage.insert_regime_judgment(
        trade_date=(date.today() - timedelta(days=1)).isoformat(),
        regime="neutral", confidence=0.6, rationale="어제", key_drivers=[],
        anchor_target_pct=0.65, effective_target_pct=effective,
        prev_effective_pct=0.05, degraded=[], macro_snapshot_id=None,
    )
    return storage


@pytest.mark.asyncio
async def test_portfolio_query_failure_is_recorded_in_degraded():
    """계좌 조회 자체가 실패하면(equity/stock_value를 모름) 판정 행의
    degraded에 그 사실이 남아야 한다 -- 조용히 (0,0,0)으로 넘어가면
    낙폭 방어가 꺼진 채로 아무 사후 감사 흔적도 안 남는다."""
    await _seed_prior()
    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(side_effect=RuntimeError("kiwoom down"))), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=_llm()):
        out = await judge_regime()

    assert out is not None
    assert "portfolio_state_unavailable" in out["degraded"]


# -------------------------------------------
# I-2 (2026-08-07 최종 리뷰) — 조회 실패가 노출도를 위로 열지 않는다
# -------------------------------------------


@pytest.mark.asyncio
async def test_portfolio_unavailable_clamps_target_to_the_previous_one():
    """`M_vol`을 축소 전용으로 바꾼 뒤(C-1) `m_drawdown`이 사실상 유일하게
    남는 안전 배수다. 계좌를 못 읽으면 `_drawdown_multiplier(0,0)`이 1.0을
    돌려주므로 그날은 방어가 통째로 없다 -- 그런 날 목표가 **오르면** 안 된다.
    """
    await _seed_prior(effective=0.20)
    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(side_effect=RuntimeError("kiwoom down"))), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider",
               return_value=_llm(regime="bull")):
        out = await judge_regime()

    assert out is not None
    # 클램프가 없으면 ramped = clamp(0.80, 0.05, 0.35) = 0.35이 그대로 나간다.
    assert out["effective_target_pct"] == pytest.approx(0.20)
    assert "target_clamped_defense_unreliable" in out["degraded"]

    storage = await get_storage_service()
    row = await storage.get_latest_regime_judgment()
    assert row["effective_target_pct"] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_portfolio_unavailable_without_prior_writes_nothing():
    """계좌도 못 읽고 이어받을 직전 목표도 없으면 임의의 숫자를 만들지
    않는다. 행이 없으면 검사 8이 스킵되고, C-2의 되돌리기가 실효 천장을
    브랜치 이전 값으로 되돌린다 -- 그것이 진짜 보수적인 상태다."""
    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(side_effect=RuntimeError("kiwoom down"))), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=_llm()):
        out = await judge_regime()

    assert out is None
    storage = await get_storage_service()
    assert await storage.get_latest_regime_judgment() is None


@pytest.mark.asyncio
async def test_equity_peak_unavailable_also_clamps():
    """고점을 못 읽어도 결과는 같다 -- `m_drawdown`이 무감쇠 1.0이 된다."""
    storage = await _seed_prior(effective=0.20)
    balance = MagicMock(evlu_amt=1_000_000.0, d2_ord_psbl_amt=500_000.0)
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=balance)

    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(return_value=client)), \
         patch.object(storage, "get_equity_peak", AsyncMock(return_value=None)), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider",
               return_value=_llm(regime="bull")):
        out = await judge_regime()

    assert out is not None
    assert out["effective_target_pct"] == pytest.approx(0.20)
    assert "target_clamped_defense_unreliable" in out["degraded"]


@pytest.mark.asyncio
async def test_healthy_portfolio_state_is_not_clamped():
    """정상 조회에서는 클램프가 절대 걸리지 않는다 -- 안 그러면 목표가
    영원히 못 오른다(램프 자체가 죽는다)."""
    storage = await _seed_prior(effective=0.20)
    balance = MagicMock(evlu_amt=1_000_000.0, d2_ord_psbl_amt=500_000.0)
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=balance)

    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(return_value=client)), \
         patch.object(storage, "get_equity_peak", AsyncMock(return_value=1_500_000.0)), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider",
               return_value=_llm(regime="bull")):
        out = await judge_regime()

    assert out is not None
    assert out["effective_target_pct"] == pytest.approx(0.35)
    assert "target_clamped_defense_unreliable" not in out["degraded"]


@pytest.mark.asyncio
async def test_equity_peak_unavailable_is_recorded_in_degraded():
    """get_equity_peak()이 None(조회 실패)을 돌려주면(고점을 모름 -> 낙폭
    배수를 신뢰할 수 없음), 그 사실이 판정 행의 degraded에 남아야 한다.
    '스냅샷 없음'(0.0, 정상)과 달리 이건 진짜 조회 실패다."""
    storage = await get_storage_service()
    balance = MagicMock(evlu_amt=1_000_000.0, d2_ord_psbl_amt=500_000.0)
    client = MagicMock()
    client.get_account_balance = AsyncMock(return_value=balance)

    with patch("app.core.kiwoom_singleton.get_shared_kiwoom_client_async",
               AsyncMock(return_value=client)), \
         patch.object(storage, "get_equity_peak", AsyncMock(return_value=None)), \
         patch("services.trading.regime_judge.refresh_macro_snapshot",
               AsyncMock(return_value=_SNAPSHOT)), \
         patch("services.trading.regime_judge.get_llm_provider", return_value=_llm()):
        out = await judge_regime()

    assert out is not None
    assert "equity_peak_unavailable" in out["degraded"]
