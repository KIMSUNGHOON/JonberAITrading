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
import re
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.storage_service import StorageService
from services.trading.index_series import closes_to_returns
from services.trading.strategy_consensus import MAX_RELATIVE_DELTA
from services.trading.exposure_target import (
    DAILY_TARGET_DELTA_MAX,
    REGIME_ANCHORS,
    TargetExposure,
    compute_regime_target,
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
_LIVE_EFFECTIVE = 0.15102547685952483
_LIVE_ACTUAL = 0.14182
_LIVE_EQUITY = 500_000_000.0
_LIVE_PEAK = 505_000_000.0

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
                         effective: float = _LIVE_EFFECTIVE,
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


async def _seed_shadow(storage, actual_pct: float = _LIVE_ACTUAL,
                       equity: float = _LIVE_EQUITY,
                       equity_peak: float = _LIVE_PEAK,
                       trade_date: str = _TRADE_DATE):
    target = TargetExposure(
        target_pct=0.1505, m_vol=0.5, m_drawdown=0.991,
        binding="daily_limit", anchor_pct=0.55, prev_effective_pct=0.1537,
        degraded=[], index_vol_annualized=_LIVE_VOL_PCT, index_vol_n=20,
    )
    assert await storage.insert_exposure_shadow(
        trade_date=trade_date, target=target, equity=equity,
        stock_value=equity * actual_pct, actual_pct=actual_pct,
        n_round_trips=None, equity_peak=equity_peak,
    )


def _engine(*, regime="bear", vol_pct=_LIVE_VOL_PCT, n=21,
            tv=_LIVE_TARGET_VOL, vmin=_LIVE_VOL_MIN,
            prev=_LIVE_EFFECTIVE, seed=_LIVE_ACTUAL,
            equity=_LIVE_EQUITY, peak=_LIVE_PEAK,
            stale=False, returns=None):
    """블록이 무엇을 말해야 하는지의 **기준은 엔진 자신**이다.

    기대값을 손으로 적으면 그것이 곧 엔진 규칙의 두 번째 사본이 되고,
    엔진이 바뀌는 날(`fix/index-series-fail-closed`의 fail-closed 폴백)
    테스트가 낡은 동작을 고정해버린다. 그래서 여기서도 계산하지 않고
    `compute_regime_target`을 부른다.
    """
    if returns is None:
        returns = closes_to_returns(_closes_for_vol(vol_pct, n))
    return compute_regime_target(
        regime_label=regime, prev_effective_pct=prev, seed_actual_pct=seed,
        index_returns=returns, equity=equity, equity_peak=peak,
        series_stale=stale, target_vol_pct=tv, vol_multiplier_min=vmin,
    )


async def _context(tmp_path, *, vol_pct=_LIVE_VOL_PCT, regime="bear",
                   knobs=None, with_index=True, with_judgment=True,
                   n=21, latest=None, equity=_LIVE_EQUITY, peak=_LIVE_PEAK):
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    if with_index:
        await _seed_index(storage, vol_pct, n=n, latest=latest)
    if with_judgment:
        await _seed_judgment(storage, regime=regime)
        await _seed_shadow(storage, equity=equity, equity_peak=peak)
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
    assert block["projection_degraded"] == []

    assert block["realized_vol_annualized_pct"] == pytest.approx(_LIVE_VOL_PCT, rel=1e-6)
    assert block["realized_vol_samples"] == 20
    assert block["index_series_stale"] is False

    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["vol_multiplier_min"] == pytest.approx(0.5)

    # 22 / 101.7 = 0.2163 -> 하한 0.5로 클램프 (엔진 값과 일치)
    assert block["m_vol_unclamped"] == pytest.approx(22.0 / _LIVE_VOL_PCT, rel=1e-6)
    assert block["m_vol"] == pytest.approx(_engine().m_vol)
    assert block["m_vol"] == pytest.approx(0.5)
    assert block["m_vol_binding"] == "floor"

    # 허용 범위 어느 쪽으로 밀어도 배수가 안 움직인다.
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["target_vol_pct_can_lower_m_vol"] is False
    # 하한을 벗어나려면 0.5 × 101.7 = 50.85 -- 허용 상한 40 밖이다.
    assert block["target_vol_pct_to_lift_m_vol"] == pytest.approx(
        0.5 * _LIVE_VOL_PCT, rel=1e-6
    )
    assert block["target_vol_pct_allowed_range"] == [10.0, 40.0]

    # 앵커는 램프에 묶여 한 번도 구속하지 않는다.
    assert block["regime_label"] == "bear"
    assert block["regime_anchor_pct"] == pytest.approx(0.55)
    assert block["daily_ramp_max"] == pytest.approx(0.15)
    assert block["anchor_is_binding"] is False

    # 수렴점 = min(ramp·m/(1−m), anchor·m) = min(0.15, 0.275) = 0.15
    assert block["convergence"]["target_pct"] == pytest.approx(0.15)
    assert block["convergence"]["binds_on"] == "ramp"

    # 실제/목표가 나란히 보인다.
    assert block["current_target_pct"] == pytest.approx(_LIVE_EFFECTIVE)
    assert block["actual_exposure_pct"] == pytest.approx(_LIVE_ACTUAL)


async def test_vol_multiplier_min_table_shows_the_alternatives(tmp_path):
    """`vol_multiplier_min` 후보별 수렴점 표 -- 패널이 선택의 결과를 본다."""
    context = await _context(tmp_path)
    table = context["exposure_mechanics"]["convergence"]["by_vol_multiplier_min"]

    assert "0.5" in table and "0.8" in table
    # 후보별 m_vol도 엔진이 낸 값이어야 한다.
    for key, row in table.items():
        assert row["m_vol"] == pytest.approx(_engine(vmin=float(key)).m_vol)
    # 0.5 -> 0.15, 0.8 -> min(0.15·0.8/0.2, 0.55·0.8) = min(0.60, 0.44) = 0.44
    assert table["0.5"]["target_pct"] == pytest.approx(0.15)
    assert table["0.8"]["target_pct"] == pytest.approx(0.44)
    # 표는 단조롭다 -- 하한을 낮추면 수렴점이 내려간다.
    keys = sorted(table, key=float)
    values = [table[k]["target_pct"] for k in keys]
    assert values == sorted(values)


async def test_table_shows_how_many_eod_runs_a_choice_takes(tmp_path):
    """1회 EOD당 25% 상대 이동 상한(MAX_RELATIVE_DELTA) -- 표에 없으면
    0.5 → 0.8이 즉시 도달 가능한 선택지로 보인다(리뷰 M8)."""
    context = await _context(tmp_path)
    block = context["exposure_mechanics"]
    table = block["convergence"]["by_vol_multiplier_min"]

    assert block["knob_max_relative_move_per_eod"] == pytest.approx(MAX_RELATIVE_DELTA)
    assert table["0.5"]["min_eod_runs"] == 0          # 현행 값
    assert table["0.8"]["min_eod_runs"] == 3          # 0.5→0.625→0.781→0.8
    assert table["0.2"]["min_eod_runs"] == 4          # 하향도 같은 상한

    # 실제로 3회가 맞는지 clamp 자체로 확인한다(상수 재구현 아님).
    v = 0.5
    for _ in range(3):
        v = min(0.8, v * (1 + MAX_RELATIVE_DELTA))
    assert v == pytest.approx(0.8)


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

    # 이 구간에서는 target_vol_pct가 실제로 m_vol을 양방향으로 움직인다.
    assert bull["exposure_mechanics"]["target_vol_pct_can_lift_m_vol"] is True
    assert bull["exposure_mechanics"]["target_vol_pct_can_lower_m_vol"] is True


# ----------------------------------------------- 4. m = 1.0 에서 0으로 안 나눈다

async def test_m_one_does_not_divide_by_zero():
    v, binds = convergence_target_pct(0.80, 1.0, DAILY_TARGET_DELTA_MAX)
    assert v == pytest.approx(0.80) and binds == "anchor"
    # 이론상 도달 불가(VOL_MULTIPLIER_MAX=1.0)지만 방어적으로.
    v, _ = convergence_target_pct(0.55, 1.5, DAILY_TARGET_DELTA_MAX)
    assert v == pytest.approx(0.55 * 1.5)
    assert convergence_target_pct(0.55, 0.0, DAILY_TARGET_DELTA_MAX)[0] == 0.0


async def test_m_vol_ceiling_when_vol_is_tiny(tmp_path):
    """실현변동성이 target_vol보다 낮으면 배수가 1.0에 포화한다(축소 전용).

    변동성 5%에서는 허용 하한(10)으로 내려도 10/5 = 2.0이라 여전히 천장이다
    -- 이 국면에서는 target_vol_pct가 **양방향 모두** 죽어 있다."""
    context = await _context(tmp_path, vol_pct=5.0)
    block = context["exposure_mechanics"]
    assert block["m_vol"] == pytest.approx(_engine(vol_pct=5.0).m_vol)
    assert block["m_vol"] == pytest.approx(1.0)
    assert block["m_vol_binding"] == "ceiling"
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["target_vol_pct_to_lift_m_vol"] is None
    assert block["target_vol_pct_can_lower_m_vol"] is False
    assert block["convergence"]["target_pct"] == pytest.approx(0.55)


async def test_ceiling_but_the_knob_still_cuts_downward(tmp_path):
    """변동성 15%: 지금은 천장이지만 허용 하한(10)으로 내리면 10/15 = 0.667로
    실제로 줄어든다 -- '천장 = 노브가 죽었다'가 아니다."""
    context = await _context(tmp_path, vol_pct=15.0)
    block = context["exposure_mechanics"]
    assert block["m_vol"] == pytest.approx(1.0)
    assert block["m_vol_binding"] == "free"   # 한쪽으로는 움직인다
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["target_vol_pct_can_lower_m_vol"] is True


# ------------------------- 5. 저하 경로: 엔진과 같은 값 · 가짜 숫자 없음

async def test_stale_series_matches_the_engine_and_stays_self_consistent(tmp_path):
    """⚠️ 리뷰 Important 3. 시계열 노후 시 엔진이 무엇을 하든(현재 1.0,
    fail-closed 수정 뒤 min(1.0, vol_min)) 블록이 **같은 값**을 말해야
    하고, 표도 그 상태에서 계산돼야 한다.

    기대값을 상수로 적지 않는다 -- 그러면 이 테스트가 곧 엔진 규칙의
    세 번째 사본이 된다.
    """
    stale_day = date.today() - timedelta(days=30)
    context = await _context(tmp_path, latest=stale_day)
    block = context["exposure_mechanics"]

    assert block["index_series_stale"] is True
    expected = _engine(stale=True)
    assert block["m_vol"] == pytest.approx(expected.m_vol)
    assert "index_series_stale" in block["projection_degraded"]
    assert block["next_target_pct_projected"] == pytest.approx(expected.target_pct)

    # 블록 안에서 서로 모순이 없다: 격자의 각 후보도 같은 stale 상태의
    # 엔진 값이어야 하고, m_vol이 같으면 수렴점도 같아야 한다.
    table = block["convergence"]["by_vol_multiplier_min"]
    for key, row in table.items():
        assert row["m_vol"] == pytest.approx(_engine(stale=True, vmin=float(key)).m_vol)
    by_m: dict = {}
    for row in table.values():
        by_m.setdefault(round(row["m_vol"], 12), set()).add(round(row["target_pct"], 12))
    for m_value, targets in by_m.items():
        assert len(targets) == 1, f"m_vol {m_value}인데 수렴점이 갈린다: {targets}"

    # 대표 수렴점도 같은 m_vol에서 나온 값이어야 한다.
    assert block["convergence"]["target_pct"] == pytest.approx(
        convergence_target_pct(REGIME_ANCHORS["bear"], expected.m_vol)[0]
    )


async def test_degraded_ratio_is_flagged_not_left_contradictory(tmp_path):
    """리뷰 2. 열화 시 `m_vol_unclamped`(0.216)와 `m_vol`이 나란히 있으면
    모순처럼 보인다 -- 비율이 **엔진 입력이 아니었다**는 것을 패널이 볼 수
    있어야 한다(코드 주석은 프롬프트에 안 실린다)."""
    fresh = (await _context(tmp_path / "fresh"))["exposure_mechanics"]
    assert fresh["m_vol_from_ratio"] is True
    assert fresh["m_vol_unclamped"] is not None

    stale = (await _context(tmp_path / "stale",
                            latest=date.today() - timedelta(days=30))
             )["exposure_mechanics"]
    assert stale["m_vol_from_ratio"] is False
    # 비율 자체는 참인 사실이라 남긴다 -- 시계열이 회복되면 어디로 갈지가 보인다.
    assert stale["m_vol_unclamped"] == pytest.approx(_LIVE_TARGET_VOL / _LIVE_VOL_PCT,
                                                     rel=1e-6)

    none_vol = (await _context(tmp_path / "novol", with_index=False)
                )["exposure_mechanics"]
    assert none_vol["m_vol_from_ratio"] is False
    assert none_vol["m_vol_unclamped"] is None


async def test_flat_index_series_does_not_stop_the_panel(tmp_path):
    """리뷰 3. 21일 종가가 완전히 평탄하면 실현변동성이 0.0이 되고
    엔진의 `target_vol_pct / vol_ann`이 ZeroDivisionError를 던진다.
    패널이 멈추지 않아야 하고, **이미 알아낸 사실까지 잃지 않아야** 한다."""
    storage = StorageService(db_path=str(tmp_path / "storage.db"))
    await _seed_eod_review(storage)
    rows = [((date.today() - timedelta(days=20 - i)).isoformat(), 100.0)
            for i in range(21)]
    assert await storage.upsert_index_daily(rows, source="test")
    await _seed_judgment(storage)
    await _seed_shadow(storage)

    context = await build_strategy_context(storage, _TRADE_DATE, dict(_KNOBS))

    assert context is not None
    block = context["exposure_mechanics"]
    # 바깥 겹(status="error")까지 안 가고 여기서 저하한다.
    assert block["status"] == "partial"
    assert "engine_projection" in block["unknown"]
    assert block["m_vol"] is None
    assert block["convergence"]["target_pct"] is None
    # ⭐ 알던 사실은 살아남는다 -- 이것이 이 가드의 존재 이유다.
    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["vol_multiplier_min"] == pytest.approx(0.5)
    assert block["regime_label"] == "bear"
    assert block["regime_anchor_pct"] == pytest.approx(0.55)
    assert block["current_target_pct"] == pytest.approx(_LIVE_EFFECTIVE)
    assert block["actual_exposure_pct"] == pytest.approx(_LIVE_ACTUAL)


async def test_missing_index_data_does_not_stop_the_panel(tmp_path):
    context = await _context(tmp_path, with_index=False)

    assert context is not None
    assert context["eod_review"]["portfolio"]["net_pnl"] == -120_000  # 나머지 불변

    block = context["exposure_mechanics"]
    assert block["status"] == "partial"
    assert "realized_vol" in block["unknown"]
    # 측정값을 지어내지 않는다.
    assert block["realized_vol_annualized_pct"] is None
    assert block["m_vol_unclamped"] is None
    # 배수는 엔진의 열화 폴백 그대로다(사본 아님) + 이유를 함께 적는다.
    expected = _engine(returns=[])
    assert block["m_vol"] == pytest.approx(expected.m_vol)
    assert "index_vol_insufficient" in block["projection_degraded"]
    # 아는 사실(노브·앵커)은 그대로 남는다.
    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["regime_anchor_pct"] == pytest.approx(0.55)


async def test_too_few_index_samples_is_unknown_not_a_guess(tmp_path):
    context = await _context(tmp_path, n=4)  # 수익률 3개 < VOL_MIN_SAMPLES
    block = context["exposure_mechanics"]
    assert block["status"] == "partial"
    assert block["realized_vol_annualized_pct"] is None
    assert block["realized_vol_samples"] == 3
    assert block["m_vol"] == pytest.approx(_engine(n=4).m_vol)
    assert "index_vol_insufficient" in block["projection_degraded"]


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
    assert block["next_target_pct_projected"] is None
    assert block["convergence"]["target_pct"] is None
    assert block["convergence"]["by_vol_multiplier_min"] is None
    # 앵커에 의존하지 않는 사실은 살아남는다.
    assert block["m_vol"] == pytest.approx(0.5)
    assert block["convergence"]["by_regime_anchor"]["bear"] == pytest.approx(0.15)


async def test_missing_shadow_row_is_listed_as_unknown(tmp_path):
    """행이 **없는** 것도 모르는 것이다 -- 예외만 unknown에 넣으면
    regime_anchor 쪽과 비대칭이 된다(리뷰 M6)."""
    context = await _context(tmp_path, with_judgment=False)
    block = context["exposure_mechanics"]
    assert "exposure_shadow" in block["unknown"]
    assert "m_drawdown" in block["unknown"]


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
    assert "index_series" in block["unknown"]
    assert "regime_judgment" in block["unknown"]
    assert block["realized_vol_annualized_pct"] is None
    assert block["convergence"]["target_pct"] is None


async def test_error_path_keeps_the_same_key_set(tmp_path):
    """실패 블록이 키를 생략하면 '데이터 없음'과 '기능 없음'이 구별되지
    않는다(리뷰 M5)."""
    ok = (await _context(tmp_path))["exposure_mechanics"]

    storage = StorageService(db_path=str(tmp_path / "b" / "storage.db"))
    await _seed_eod_review(storage)
    with patch("services.trading.strategy_panel._exposure_mechanics",
               side_effect=RuntimeError("boom")):
        context = await build_strategy_context(storage, _TRADE_DATE, dict(_KNOBS))
    err = context["exposure_mechanics"]

    assert err["status"] == "error"
    assert set(ok) <= set(err)
    assert set(err["convergence"]) == set(ok["convergence"])
    assert err["m_vol"] is None and err["convergence"]["target_pct"] is None


async def test_missing_knobs_are_not_backfilled_with_module_defaults(tmp_path):
    """노브가 컨텍스트에 없으면 18.0/0.5(모듈 기본값)를 조용히 넣지 않는다."""
    context = await _context(tmp_path, knobs={"risk_tolerance": "moderate"})
    block = context["exposure_mechanics"]
    assert block["target_vol_pct"] is None
    assert block["vol_multiplier_min"] is None
    assert block["m_vol"] is None
    assert block["convergence"]["by_regime_anchor"] is None
    assert "target_vol_pct" in block["unknown"]


# --------------------------------- 6. 다음 목표는 m_drawdown을 포함한다

async def test_projected_next_target_includes_drawdown_multiplier(tmp_path):
    """리뷰 Important 2. `ramped × m_vol`로 재계산하면 낙폭 국면에서
    최대 233% 과대가 된다 -- 엔진이 낸 값을 그대로 실어야 한다."""
    equity, peak = 60_000_000.0, 100_000_000.0   # 낙폭 40% -> m_drawdown 바닥
    context = await _context(tmp_path, equity=equity, peak=peak)
    block = context["exposure_mechanics"]

    expected = _engine(equity=equity, peak=peak)
    assert block["next_target_pct_projected"] == pytest.approx(expected.target_pct)
    assert block["m_drawdown_used"] == pytest.approx(expected.m_drawdown)
    assert expected.m_drawdown < 0.5   # 방어가 실제로 물린 국면

    # 낙폭을 빼먹은 값(ramped × m_vol)과 **다르다**.
    naive = block["ramped_pct"] * block["m_vol"]
    assert block["next_target_pct_projected"] < naive * 0.9
    assert "m_drawdown" in block["next_target_assumes"]


async def test_unknown_drawdown_is_declared_not_silently_one(tmp_path):
    context = await _context(tmp_path, with_judgment=False)
    block = context["exposure_mechanics"]
    assert "m_drawdown" in block["unknown"]


# --------------------------------------------- 7. 블록이 실제로 프롬프트에 닿는다

def _block_from_prompt(provider) -> dict:
    messages = provider.generate_structured.await_args_list[0].args[0]
    sent = "\n".join(str(m.content) for m in messages)
    payload = json.loads(sent[sent.index("{"):])
    return payload["exposure_mechanics"]


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
    block = _block_from_prompt(provider)
    assert block["m_vol_binding"] == "floor"
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["convergence"]["target_pct"] == pytest.approx(0.15)


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
    block = _block_from_prompt(provider)

    assert block["status"] == "ok"
    assert block["target_vol_pct"] == pytest.approx(22.0)
    assert block["m_vol_binding"] == "floor"
    assert block["target_vol_pct_can_lift_m_vol"] is False
    assert block["target_vol_pct_to_lift_m_vol"] == pytest.approx(
        0.5 * _LIVE_VOL_PCT, rel=1e-6
    )
    assert block["convergence"]["target_pct"] == pytest.approx(0.15)


# ------------------------------------------------- 8. 프레이밍 중립성

def _knob_segments(text: str, knob: str) -> list[str]:
    """노브 이름이 나오는 **모든 줄**. 권고 어휘 검사는 넓을수록 좋다."""
    return [s for s in re.split(r"\n", text) if knob in s]


def _knob_bullets(text: str, knob: str) -> list[str]:
    """그 노브의 **방향 서술 불릿**만(`- `로 시작하는 줄).

    ⚠️ 대칭 단언에 `_knob_segments`를 쓰면 위양성이 난다(2026-08-11 리뷰 1).
    첫 줄의 노브 목록에는 두 노브 이름이 **둘 다** 들어 있고, 그 줄에
    `consensus_threshold`를 설명하는 "낮추면 진입 기회가 늘고"가 있다.
    그래서 불릿의 하향 서술을 통째로 지워도 첫 줄이 대신 단언을 만족시켜
    **대칭 가드의 하향 절반이 아무것도 안 지키는** 상태였다.
    """
    return [s for s in text.split("\n") if s.lstrip().startswith("- ") and knob in s]


async def test_knob_description_states_the_floor_and_the_dead_zone():
    """노브 설명이 '축소에 하한이 있다'와 '그 구간에서 target_vol_pct가
    소거된다'를 말한다. 라이브 수치는 프롬프트 상수에 박지 않는다."""
    from services.trading.strategy_panel import _SCHEMA_INSTRUCTION

    assert "m_vol" in _SCHEMA_INSTRUCTION
    assert "exposure_mechanics" in _SCHEMA_INSTRUCTION
    # base의 프레이밍 한 절이 살아 있다 -- 이 노브가 '방어의 상한'이라는
    # 것을 프롬프트에서 말하는 유일한 문장이었다(리뷰 Important 1).
    assert "이 배수 아래로는 안 줄인다" in _SCHEMA_INSTRUCTION
    # 낡을 라이브 수치가 상수에 박혀 있지 않다.
    assert "101" not in _SCHEMA_INSTRUCTION
    assert "50.9" not in _SCHEMA_INSTRUCTION
    # 허용 범위는 블록이 라이브로 싣는다 -- 문단에 두 번째 사본을 만들지
    # 않는다(리뷰 M4).
    assert _SCHEMA_INSTRUCTION.count("10~40") == 1
    assert _SCHEMA_INSTRUCTION.count("0.2~0.8") == 1


async def test_knob_description_is_symmetric_and_non_directive():
    """이 태스크의 최우선 속성: 사실을 주되 **조종하지 않는다**.

    존재/부재 단언만으로는 문단을 '올리십시오'로 바꿔도 통과한다 --
    그래서 (a) 두 노브 모두 상·하향이 같이 서술되는지 (b) 노브 이름이
    나오는 문장에 권고 어휘가 없는지를 본다.
    """
    from services.trading.strategy_panel import _SCHEMA_INSTRUCTION

    for knob in ("vol_multiplier_min", "target_vol_pct"):
        bullets = _knob_bullets(_SCHEMA_INSTRUCTION, knob)
        assert bullets, f"{knob}: 방향 서술 불릿이 없다"
        segs = " ".join(bullets)
        assert "올리면" in segs, f"{knob}: 상향 효과 서술이 없다"
        assert "낮추면" in segs, f"{knob}: 하향 효과 서술이 없다"

    # 방어의 세기라는 프레이밍이 상향 쪽에도 붙어 있다.
    assert "방어" in _SCHEMA_INSTRUCTION

    # 권고 어휘는 **모든** 줄에서 본다(불릿 밖에 숨겨도 잡히게).
    directive = ("올리십시오", "올리세요", "높이십시오", "높이세요", "낮추십시오",
                 "낮추세요", "줄이십시오", "권장", "추천", "바람직", "해야 합니다",
                 # 동의어 -- 완전한 목록은 불가능하지만 흔한 우회는 막는다.
                 "편이 낫", "편이 좋", "것이 낫", "것이 좋", "제안하십시오", "권합니다")
    for knob in ("vol_multiplier_min", "target_vol_pct"):
        for seg in _knob_segments(_SCHEMA_INSTRUCTION, knob):
            for word in directive:
                assert word not in seg, f"{knob} 문장에 권고 어휘 '{word}'"
