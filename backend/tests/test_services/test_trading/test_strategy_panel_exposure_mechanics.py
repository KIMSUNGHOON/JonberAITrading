"""전략 패널이 자기가 조정하는 노출도 노브의 역학을 볼 수 있는가.

2026-08-11 라이브: 실현변동성 101.7% · `target_vol_pct` 22.0 →
`22/101.7 = 0.216`이 하한 0.5로 클램프돼 `m_vol`이 **하한에 박혀 있다**.
그 구간에서는 `target_vol_pct`를 허용 상한(40)까지 올려도 결과가 1bp도
안 바뀌고(하한을 벗어나려면 50.9가 필요), 레짐 앵커(bull/neutral/bear)도
램프에 먼저 묶여 결과에 도달하지 못한다. 패널에게는 이 사실을 볼 방법이
없었다 -- 값은 정상 적용됐고 산수에서 소거됐을 뿐이라
`strategy_knob_discarded`조차 나지 않는다.

여기서 지키는 것은 **정보 전달**이지 조종이 아니다: 블록은 사실만 담고,
그 사실로 무엇을 할지는 패널이 정한다.

⚠️ 라이브 DB 격리: 이 파일은 tmp-path StorageService만 쓰지만
`isolated_storage_service`를 함께 걸어 전역 싱글턴 경로도 막는다.
"""

import json
import math
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.exposure_target import (
    DAILY_TARGET_DELTA_MAX,
    REGIME_ANCHORS,
    TargetExposure,
)
from services.trading.strategy_panel import (
    build_strategy_context,
    convergence_target_pct,
    run_strategy_panel,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.usefixtures("isolated_storage_service"),
]

_TRADE_DATE = "2026-08-11"

# 오늘 라이브 그대로.
_LIVE_VOL_PCT = 101.7
_LIVE_TARGET_VOL = 22.0
_LIVE_VOL_MIN = 0.5

_KNOBS = {
    "risk_tolerance": "moderate",
    "max_position_pct": 0.0375,
    "target_vol_pct": _LIVE_TARGET_VOL,
    "vol_multiplier_min": _LIVE_VOL_MIN,
}


async def _seed_eod_review(storage, trade_date=_TRADE_DATE):
    report = {
        "trade_date": trade_date,
        "portfolio": {"equity": 500_000_000, "net_pnl": -120_000,
                      "win_trades": 1, "loss_trades": 2,
                      "realized_pnl": -100_000, "cumulative_return_pct": -0.02,
                      "exposure": 0.14, "concentration": 0.5},
        "per_stock": [],
        "agents": [],
        "regime": {"regime_snapshot_id": "r1", "label": "risk_off"},
    }
    await storage.save_eod_review(
        {"trade_date": trade_date, "report_json": json.dumps(report)}
    )


def _closes_for_vol(vol_pct: float, n: int = 21) -> list[float]:
    """연율 `vol_pct`가 나오는 종가 시계열(오름차순).

    ±a 교대 수익률의 표본표준편차는 a·√(m/(m-1)) (m=수익률 개수, 평균 0).
    """
    m = n - 1
    sd = vol_pct / math.sqrt(250)
    a = sd / math.sqrt(m / (m - 1))
    closes = [100.0]
    for i in range(m):
        r = a if i % 2 == 0 else -a
        closes.append(closes[-1] * (1.0 + r / 100.0))
    return closes


async def _seed_index(storage, vol_pct: float = _LIVE_VOL_PCT, n: int = 21,
                      latest: date | None = None):
    latest = latest or date.today()
    closes = _closes_for_vol(vol_pct, n)
    rows = [
        ((latest - timedelta(days=n - 1 - i)).isoformat(), c)
        for i, c in enumerate(closes)
    ]
    assert await storage.upsert_index_daily(rows, source="test")


async def _seed_judgment(storage, regime: str = "bear",
                         effective: float = 0.15102547685952483,
                         trade_date: str = _TRADE_DATE):
    assert await storage.insert_regime_judgment(
        trade_date=trade_date,
        regime=regime,
        confidence=0.72,
        rationale="테스트",
        key_drivers=[],
        anchor_target_pct=REGIME_ANCHORS[regime],
        effective_target_pct=effective,
        prev_effective_pct=0.15375639263471202,
        degraded=[],
    )


async def _seed_shadow(storage, actual_pct: float = 0.14182,
                       trade_date: str = _TRADE_DATE):
    target = TargetExposure(
        target_pct=0.1505, m_vol=0.5, m_drawdown=0.991,
        binding="daily_limit", anchor_pct=0.55, prev_effective_pct=0.1537,
        degraded=[], index_vol_annualized=_LIVE_VOL_PCT, index_vol_n=20,
    )
    assert await storage.insert_exposure_shadow(
        trade_date=trade_date, target=target, equity=500_000_000,
        stock_value=500_000_000 * actual_pct, actual_pct=actual_pct,
        n_round_trips=None, equity_peak=505_000_000,
    )


async def _context(tmp_path, *, vol_pct=_LIVE_VOL_PCT, regime="bear",
                   knobs=None, with_index=True, with_judgment=True,
                   n=21, latest=None):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    if with_index:
        await _seed_index(storage, vol_pct, n=n, latest=latest)
    if with_judgment:
        await _seed_judgment(storage, regime=regime)
        await _seed_shadow(storage)
    return await build_strategy_context(
        storage, _TRADE_DATE, dict(knobs if knobs is not None else _KNOBS)
    )


# ---------------------------------------------------------------- 1. 라이브 재현

async def test_live_state_is_visible_to_the_panel(tmp_path):
    """실현변동성 101.7 · target_vol 22 · vol_min 0.5 · bear →
    m_vol이 하한에 클램프됐고, 그것을 푸는 데 필요한 target_vol_pct가
    허용 상한 밖이라는 사실이 블록에 드러난다."""
    context = await _context(tmp_path)
    block = context["exposure_mechanics"]

    assert block["status"] == "ok"
    assert block["unknown"] == []

    assert block["realized_vol_annualized_pct"] == pytest.approx(_LIVE_VOL_PCT, rel=1e-6)
    assert block["realized_vol_samples"] == 20
    assert block["index_series_stale"] is False

    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["vol_multiplier_min"] == pytest.approx(0.5)

    # 22 / 101.7 = 0.2163 -> 하한 0.5로 클램프
    assert block["m_vol_unclamped"] == pytest.approx(22.0 / _LIVE_VOL_PCT, rel=1e-6)
    assert block["m_vol"] == pytest.approx(0.5)
    assert block["m_vol_binding"] == "floor"

    # 하한을 벗어나려면 0.5 × 101.7 = 50.85 -- 허용 상한 40 밖이다.
    assert block["target_vol_pct_to_lift_m_vol"] == pytest.approx(
        0.5 * _LIVE_VOL_PCT, rel=1e-6
    )
    assert block["target_vol_pct_allowed_range"] == [10.0, 40.0]
    assert block["target_vol_pct_can_lift_m_vol"] is False

    # 앵커는 램프에 묶여 한 번도 구속하지 않는다.
    assert block["regime_label"] == "bear"
    assert block["regime_anchor_pct"] == pytest.approx(0.55)
    assert block["daily_ramp_max"] == pytest.approx(0.15)
    assert block["anchor_is_binding"] is False

    # 수렴점 = min(ramp·m/(1−m), anchor·m) = min(0.15, 0.275) = 0.15
    assert block["convergence"]["target_pct"] == pytest.approx(0.15)
    assert block["convergence"]["binds_on"] == "ramp"

    # 실제/목표가 나란히 보인다.
    assert block["current_target_pct"] == pytest.approx(0.15102547685952483)
    assert block["actual_exposure_pct"] == pytest.approx(0.14182)


async def test_vol_multiplier_min_table_shows_the_alternatives(tmp_path):
    """`vol_multiplier_min` 후보별 수렴점 표 -- 패널이 선택의 결과를 본다."""
    context = await _context(tmp_path)
    table = context["exposure_mechanics"]["convergence"]["by_vol_multiplier_min"]

    assert "0.5" in table and "0.8" in table
    # 하한을 올리면 m_vol이 그대로 따라 올라간다(현재 raw 0.216 < 모든 후보).
    assert table["0.5"]["m_vol"] == pytest.approx(0.5)
    assert table["0.8"]["m_vol"] == pytest.approx(0.8)
    # 0.5 -> 0.15, 0.8 -> min(0.15·0.8/0.2, 0.55·0.8) = min(0.60, 0.44) = 0.44
    assert table["0.5"]["target_pct"] == pytest.approx(0.15)
    assert table["0.8"]["target_pct"] == pytest.approx(0.44)
    # 표는 단조롭다 -- 하한을 낮추면 수렴점이 내려간다.
    keys = sorted(table, key=float)
    values = [table[k]["target_pct"] for k in keys]
    assert values == sorted(values)


# ---------------------------------------------- 2. 앵커가 결과를 안 바꾼다

@pytest.mark.parametrize("regime", ["bull", "neutral", "bear"])
async def test_anchor_does_not_reach_the_result_at_the_floor(tmp_path, regime):
    """오늘 조건에서는 세 앵커의 수렴점이 전부 0.15다."""
    context = await _context(tmp_path, regime=regime)
    conv = context["exposure_mechanics"]["convergence"]

    assert conv["target_pct"] == pytest.approx(0.15)
    assert conv["by_regime_anchor"] == {
        "bull": pytest.approx(0.15),
        "neutral": pytest.approx(0.15),
        "bear": pytest.approx(0.15),
    }
    assert context["exposure_mechanics"]["anchor_is_binding"] is False


# ------------------------------------- 3. 낮은 변동성에서는 앵커가 구속한다

async def test_convergence_pure_math_matches_the_verification_table():
    ramp = DAILY_TARGET_DELTA_MAX
    assert ramp == pytest.approx(0.15)

    assert convergence_target_pct(0.55, 0.5, ramp)[0] == pytest.approx(0.15)
    assert convergence_target_pct(0.80, 0.5, ramp)[0] == pytest.approx(0.15)

    # m이 커지면 anchor·m이 작아져 앵커가 구속하기 시작한다.
    v, binds = convergence_target_pct(0.80, 0.8, ramp)
    assert v == pytest.approx(0.60) and binds == "ramp"
    v, binds = convergence_target_pct(0.55, 0.8, ramp)
    assert v == pytest.approx(0.44) and binds == "anchor"


async def test_low_vol_lets_the_anchor_bind(tmp_path):
    """target_vol 22 / 실현변동성 27.5 = 0.8 -> 앵커가 결과를 가른다."""
    vol = _LIVE_TARGET_VOL / 0.8  # 27.5
    bull = await _context(tmp_path / "a", vol_pct=vol, regime="bull")
    bear = await _context(tmp_path / "b", vol_pct=vol, regime="bear")

    assert bull["exposure_mechanics"]["m_vol"] == pytest.approx(0.8)
    assert bull["exposure_mechanics"]["m_vol_binding"] == "free"
    assert bull["exposure_mechanics"]["convergence"]["target_pct"] == pytest.approx(0.60)
    assert bear["exposure_mechanics"]["convergence"]["target_pct"] == pytest.approx(0.44)
    assert bear["exposure_mechanics"]["convergence"]["binds_on"] == "anchor"

    # 이 구간에서는 target_vol_pct가 실제로 m_vol을 움직인다.
    assert bull["exposure_mechanics"]["target_vol_pct_can_lift_m_vol"] is True


# ----------------------------------------------- 4. m = 1.0 에서 0으로 안 나눈다

async def test_m_one_does_not_divide_by_zero():
    v, binds = convergence_target_pct(0.80, 1.0, DAILY_TARGET_DELTA_MAX)
    assert v == pytest.approx(0.80) and binds == "anchor"
    # 이론상 도달 불가(VOL_MULTIPLIER_MAX=1.0)지만 방어적으로.
    v, _ = convergence_target_pct(0.55, 1.5, DAILY_TARGET_DELTA_MAX)
    assert v == pytest.approx(0.55 * 1.5)
    assert convergence_target_pct(0.55, 0.0, DAILY_TARGET_DELTA_MAX)[0] == 0.0


async def test_m_vol_ceiling_when_vol_is_tiny(tmp_path):
    """실현변동성이 target_vol보다 낮으면 배수가 1.0에 포화한다(축소 전용)."""
    context = await _context(tmp_path, vol_pct=5.0)
    block = context["exposure_mechanics"]
    assert block["m_vol"] == pytest.approx(1.0)
    assert block["m_vol_binding"] == "ceiling"
    assert block["convergence"]["target_pct"] == pytest.approx(0.55)


# ------------------------------------- 5. 데이터 없음: 멈추지 않고, 가짜도 없다

async def test_missing_index_data_does_not_stop_the_panel(tmp_path):
    context = await _context(tmp_path, with_index=False)

    assert context is not None
    assert context["eod_review"]["portfolio"]["net_pnl"] == -120_000  # 나머지 불변

    block = context["exposure_mechanics"]
    assert block["status"] == "partial"
    assert "realized_vol" in block["unknown"]
    # 그럴듯한 가짜 숫자를 넣지 않는다.
    assert block["realized_vol_annualized_pct"] is None
    assert block["m_vol"] is None
    assert block["m_vol_binding"] == "unknown"
    assert block["target_vol_pct_to_lift_m_vol"] is None
    assert block["target_vol_pct_can_lift_m_vol"] is None
    assert block["convergence"]["target_pct"] is None
    assert block["convergence"]["by_regime_anchor"] is None
    assert block["convergence"]["by_vol_multiplier_min"] is None
    # 아는 사실(노브·앵커)은 그대로 남는다.
    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["regime_anchor_pct"] == pytest.approx(0.55)


async def test_too_few_index_samples_is_unknown_not_a_guess(tmp_path):
    context = await _context(tmp_path, n=4)  # 수익률 3개 < VOL_MIN_SAMPLES
    block = context["exposure_mechanics"]
    assert block["status"] == "partial"
    assert block["realized_vol_annualized_pct"] is None
    assert block["realized_vol_samples"] == 3
    assert block["m_vol"] is None


async def test_missing_regime_judgment_is_unknown_not_a_guess(tmp_path):
    context = await _context(tmp_path, with_judgment=False)
    block = context["exposure_mechanics"]

    assert block["status"] == "partial"
    assert "regime_anchor" in block["unknown"]
    assert block["regime_label"] is None
    assert block["regime_anchor_pct"] is None
    assert block["current_target_pct"] is None
    assert block["actual_exposure_pct"] is None
    assert block["anchor_is_binding"] is None
    assert block["convergence"]["target_pct"] is None
    # 앵커에 의존하지 않는 사실은 살아남는다.
    assert block["m_vol"] == pytest.approx(0.5)
    assert block["convergence"]["by_regime_anchor"]["bear"] == pytest.approx(0.15)


async def test_storage_failure_degrades_to_explicit_unknown(tmp_path):
    """조회가 예외를 던져도 패널은 계속 간다 -- 명시적 '모름'으로."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)

    async def _boom(*_a, **_kw):
        raise RuntimeError("db down")

    with patch.object(StorageService, "get_recent_index_closes", _boom), \
         patch.object(StorageService, "get_latest_regime_judgment", _boom):
        context = await build_strategy_context(storage, _TRADE_DATE, dict(_KNOBS))

    assert context is not None
    block = context["exposure_mechanics"]
    assert block["status"] in ("partial", "error")
    assert block["m_vol"] is None
    assert block["convergence"]["target_pct"] is None


async def test_missing_knobs_are_not_backfilled_with_module_defaults(tmp_path):
    """노브가 컨텍스트에 없으면 18.0/0.5(모듈 기본값)를 조용히 넣지 않는다."""
    context = await _context(tmp_path, knobs={"risk_tolerance": "moderate"})
    block = context["exposure_mechanics"]
    assert block["target_vol_pct"] is None
    assert block["vol_multiplier_min"] is None
    assert block["m_vol"] is None
    assert "target_vol_pct" in block["unknown"]


# --------------------------------------------- 6. 블록이 실제로 프롬프트에 닿는다

async def test_block_reaches_the_panelist_prompt(tmp_path):
    """컨텍스트에만 있고 직렬화에서 빠지면 아무 소용이 없다 -- 종단 확인."""
    context = await _context(tmp_path)

    provider = MagicMock()
    provider.generate_structured = AsyncMock(
        return_value={"stance": "neutral", "confidence": 0.5, "reasoning": "x"}
    )
    with patch("services.trading.strategy_panel.get_llm_provider",
               return_value=provider):
        await run_strategy_panel(context)

    assert provider.generate_structured.await_count == 3
    messages = provider.generate_structured.await_args_list[0].args[0]
    sent = "\n".join(str(m.content) for m in messages)

    assert "exposure_mechanics" in sent
    payload = json.loads(sent[sent.index("{"):])["exposure_mechanics"]
    assert payload["m_vol_binding"] == "floor"
    assert payload["target_vol_pct_can_lift_m_vol"] is False
    assert payload["convergence"]["target_pct"] == pytest.approx(0.15)


async def test_orchestrator_hands_the_vol_knobs_to_the_context():
    """현행 노브가 컨텍스트에 실려야 블록이 계산된다 -- 이 배선이 빠지면
    블록은 조용히 '모름'으로 저하된다."""
    from services.trading.strategy import TradingStrategy
    from services.trading.strategy_orchestrator import _current_knobs

    strategy = TradingStrategy()
    strategy.position_sizing.target_vol_pct = 22.0
    strategy.position_sizing.vol_multiplier_min = 0.5

    knobs = _current_knobs(strategy)
    assert knobs["target_vol_pct"] == pytest.approx(22.0)
    assert knobs["vol_multiplier_min"] == pytest.approx(0.5)


async def test_end_to_end_live_knobs_reach_the_panel_prompt(tmp_path):
    """orchestrator → context → 패널 프롬프트까지 한 번에.

    전략에 박힌 22.0이 실제 프롬프트의 exposure_mechanics에 나타나고,
    그 블록이 'm_vol은 하한에 있고 target_vol_pct로는 못 푼다'를 말한다.
    """
    from services.trading import strategy_orchestrator
    from services.trading.strategy import TradingStrategy
    from services.trading.strategy_orchestrator import run_strategy_consensus

    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    await _seed_index(storage)
    await _seed_judgment(storage)
    await _seed_shadow(storage)

    strategy = TradingStrategy()
    strategy.position_sizing.target_vol_pct = 22.0
    strategy.position_sizing.vol_multiplier_min = 0.5

    class _Coordinator:
        def get_strategy(self):
            return strategy

        def set_strategy(self, s):
            pass

    provider = MagicMock()
    provider.generate_structured = AsyncMock(
        return_value={"stance": "neutral", "confidence": 0.5, "reasoning": "x"}
    )
    with patch("services.trading.strategy_panel.get_llm_provider",
               return_value=provider):
        result = await run_strategy_consensus(
            _Coordinator(), storage, _TRADE_DATE, force=True
        )

    assert result["ok"] is True, result
    assert provider.generate_structured.await_count == 3
    messages = provider.generate_structured.await_args_list[0].args[0]
    sent = "\n".join(str(m.content) for m in messages)

    block = json.loads(sent[sent.index("{"):])["exposure_mechanics"]
    assert block["status"] == "ok"
    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["m_vol_binding"] == "floor"
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["target_vol_pct_to_lift_m_vol"] == pytest.approx(
        0.5 * _LIVE_VOL_PCT, rel=1e-6
    )
    assert block["convergence"]["target_pct"] == pytest.approx(0.15)


async def test_knob_description_states_the_floor_and_the_dead_zone():
    """노브 설명이 '축소에 하한이 있다'와 '그 구간에서 target_vol_pct가
    소거된다'를 말한다. 라이브 수치는 프롬프트 상수에 박지 않는다."""
    from services.trading.strategy_panel import _SCHEMA_INSTRUCTION

    assert "m_vol" in _SCHEMA_INSTRUCTION
    assert "vol_multiplier_min" in _SCHEMA_INSTRUCTION
    assert "exposure_mechanics" in _SCHEMA_INSTRUCTION
    # 낡을 라이브 수치가 상수에 박혀 있지 않다.
    assert "101" not in _SCHEMA_INSTRUCTION
    assert "50.9" not in _SCHEMA_INSTRUCTION
