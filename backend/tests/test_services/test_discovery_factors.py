"""
DS-1: 4전략 팩터 엔진 테스트.

전부 순수 함수(services.discovery.factors) 대상 — 실 네트워크·DB 없음, 합성
OHLCV DataFrame만 사용. 모든 픽스처는 수식으로 결정적으로 생성한다(랜덤 시드
없음 — 랜덤 자체를 쓰지 않아 재현성 문제가 원천 차단됨).
"""

import math

import pandas as pd
import pytest

from services.discovery.factors import (
    DEFAULT_MIN_HISTORY,
    REASON_INSUFFICIENT_HISTORY,
    REASON_LIQUIDITY_INCONSISTENT,
    REASON_LIQUIDITY_LOW,
    REASON_MARKET_CAP_LOW,
    REASON_PRICE_TOO_LOW,
    REASON_NEGATIVE_EPS,
    REASON_PRICE_ZERO,
    REASON_ZERO_VOLUME_DAY,
    STRATEGIES,
    FlowRank,
    StockSnapshot,
    compute_strategy_scores,
    passes_quality_filter,
)

# ---------------------------------------------------------------------------
# 결정적 합성 OHLCV 빌더
# ---------------------------------------------------------------------------


def _make_chart_df(closes, volumes, wick_days=None):
    """closes/volumes로 OHLCV DataFrame을 만든다(technical_indicators.py가 기대하는
    date/open/high/low/close/volume 컬럼, 오름차순 — kiwoom get_daily_chart_df와
    동일 스키마). 종가 기준 ±0.4% 밴드로 open/high/low를 파생하되, wick_days로
    특정 일자(급락/패닉 당일)의 저가를 더 깊게 강제할 수 있다."""
    n = len(closes)
    assert len(volumes) == n
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    opens = [closes[0]] + list(closes[:-1])
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    if wick_days:
        for idx, (low_mult, high_mult) in wick_days.items():
            lows[idx] = closes[idx] * low_mult
            highs[idx] = closes[idx] * high_mult
    opens = [min(max(o, lo), hi) for o, lo, hi in zip(opens, lows, highs)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _calm_phase(n, start=10000.0, drift=0.0005, amp=0.006, freq=0.8):
    """저변동 완만한 상승(볼린저 밴드를 좁게 유지) — sin 파형, 완전히 결정적."""
    return [start * (1 + drift) ** i * (1 + amp * math.sin(i * freq)) for i in range(n)]


def _snapshot(ticker, df, *, price=None, market_cap=1_000_000_000_000):
    close = float(df["close"].iloc[-1]) if len(df) else 0.0
    volume = float(df["volume"].iloc[-1]) if len(df) else 0.0
    return StockSnapshot(
        ticker=ticker,
        name=f"종목{ticker}",
        price=close if price is None else price,
        market_cap=market_cap,
        per=10.0,
        pbr=1.2,
        volume=volume,
        chart_df=df,
    )


def _valid_history_df(n=DEFAULT_MIN_HISTORY):
    closes = [10000.0 + i * 5.0 for i in range(n)]
    volumes = [100_000.0] * n
    return _make_chart_df(closes, volumes)


# ---------------------------------------------------------------------------
# 4대 픽스처 — 브리프 Step 1
# ---------------------------------------------------------------------------


def _uptrend_df():
    """정배열 상승: SMA5>20>60, MACD 상향, 20일 신고가 근접, 거래량 급증 → momentum.

    거래대금(value) 컬럼: 유동성 인지 아크(A2) 이전에 작성된 픽스처라 원래
    없었다. `value` 없이는 momentum의 거래대금 성분이 전부 0으로 수렴해
    (fail-closed) 이 테스트가 기대하는 "유동성 충분한 정배열 상승"을 더 이상
    표현하지 못하므로, 구 수식 롤백이 아니라 픽스처를 새 스키마에 맞춰 갱신한다.
    """
    n = 80
    closes = [10000.0 * (1.006**i) for i in range(n)]
    volumes = [100_000.0] * (n - 5) + [300_000.0] * 5  # 최근 5일 거래량 급증
    df = _make_chart_df(closes, volumes)
    df["value"] = [150 * 억] * (n - 5) + [300 * 억] * 5  # ADTV 충분(>100억) + 거래대금 확장
    return df


def _sideways_df():
    """횡보 지지: 장기 상승 후 SMA20 근접 박스권 유지, RSI 40~55대 → pullback."""
    closes = [10000.0 * (1.004**i) for i in range(60)]
    base = closes[-1]
    for k in range(1, 31):
        drift = base * (1 + 0.0006 * k)
        closes.append(drift * (1 + 0.012 * math.sin(k * 0.9)))
    volumes = [100_000.0] * len(closes)
    return _make_chart_df(closes, volumes)


_CALM_N = 75
_CRASH_DAYS = 5
_CRASH_PCT = 0.06


def _crash_df():
    """급락(진행형, 반등 없음): 저변동 구간 후 5일 연속 -6%/day로 마감 —
    볼린저 하단을 이탈했지만 재진입하지 못한 채 종가가 여전히 밴드 아래(위험)."""
    closes = _calm_phase(_CALM_N)
    base = closes[-1]
    for k in range(1, _CRASH_DAYS + 1):
        closes.append(base * (1 - _CRASH_PCT) ** k)
    volumes = [100_000.0] * len(closes)
    wick_days = {len(closes) - 1 - o: (0.92, 1.0) for o in range(3)}
    return _make_chart_df(closes, volumes, wick_days)


def _oversold_bounce_df():
    """과매도 반등: _crash_df와 동일한 5일 급락 뒤 1일 반등(+5%)으로 볼린저 하단을
    다시 뚫고 올라옴(복귀) — RSI는 여전히 깊은 과매도(<30)라 meanrev가 최고여야 함."""
    closes = _calm_phase(_CALM_N)
    base = closes[-1]
    for k in range(1, _CRASH_DAYS + 1):
        closes.append(base * (1 - _CRASH_PCT) ** k)
    trough = closes[-1]
    closes.append(trough * 1.05)  # 반등 1일
    volumes = [100_000.0] * len(closes)
    wick_days = {_CALM_N + o: (0.92, 1.0) for o in range(3)}
    return _make_chart_df(closes, volumes, wick_days)


_FIXTURE_FACTORIES = {
    "uptrend": _uptrend_df,
    "sideways": _sideways_df,
    "crash": _crash_df,
    "bounce": _oversold_bounce_df,
}


# ---------------------------------------------------------------------------
# ① 4픽스처 — 각 전략이 자기 픽스처에서 최고 스코어
# ---------------------------------------------------------------------------


class TestFourStrategyFixtures:
    def test_uptrend_favors_momentum(self):
        scores = compute_strategy_scores(_snapshot("100001", _uptrend_df()), None)
        assert scores["momentum"] == max(scores[s] for s in STRATEGIES)
        assert scores["momentum"] > 0.8

    def test_sideways_favors_pullback(self):
        scores = compute_strategy_scores(_snapshot("100002", _sideways_df()), None)
        assert scores["pullback"] == max(scores[s] for s in STRATEGIES)
        assert scores["pullback"] > scores["momentum"]

    def test_crash_meanrev_lower_and_riskier_than_bounce(self):
        """급락(진행형)은 아직 밴드 재진입을 못했으므로 반등 픽스처보다
        meanrev가 뚜렷이 낮아야 한다 — '위험한 급락'과 '과매도 반등'을 가르는
        핵심 단언(단순 RSI<30/낙폭만으로는 이 둘을 구별할 수 없어야 실패)."""
        crash_scores = compute_strategy_scores(_snapshot("100003", _crash_df()), None)
        bounce_scores = compute_strategy_scores(_snapshot("100004", _oversold_bounce_df()), None)
        assert crash_scores["meanrev"] < bounce_scores["meanrev"]
        assert bounce_scores["meanrev"] - crash_scores["meanrev"] > 0.1
        # 급락 픽스처는 볼린저 재진입 원자 팩터가 꺼져 있어야 한다(위험 신호).
        assert crash_scores["_atoms"]["touched_lower_recently"] is True
        assert crash_scores["_atoms"]["current_price"] < crash_scores["_atoms"]["bb_lower"]

    def test_oversold_bounce_favors_meanrev_globally(self):
        all_scores = {
            name: compute_strategy_scores(_snapshot(f"1000{i}", factory()), None)
            for i, (name, factory) in enumerate(_FIXTURE_FACTORIES.items(), start=1)
        }
        bounce = all_scores["bounce"]
        assert bounce["meanrev"] == max(bounce[s] for s in STRATEGIES)
        assert bounce["meanrev"] == max(sc["meanrev"] for sc in all_scores.values())
        # 재진입(복귀) 원자 팩터가 켜져 있어야 한다.
        assert bounce["_atoms"]["touched_lower_recently"] is True
        assert bounce["_atoms"]["current_price"] > bounce["_atoms"]["bb_lower"]


# ---------------------------------------------------------------------------
# ② 품질 필터 3사유
# ---------------------------------------------------------------------------


class TestQualityFilter:
    def test_passes_when_all_conditions_met(self):
        ok, reason = passes_quality_filter(_snapshot("200001", _valid_history_df()))
        assert ok is True
        assert reason is None

    def test_fails_price_zero(self):
        ok, reason = passes_quality_filter(_snapshot("200002", _valid_history_df(), price=0.0))
        assert ok is False
        assert reason == REASON_PRICE_ZERO

    def test_fails_price_negative(self):
        ok, reason = passes_quality_filter(_snapshot("200003", _valid_history_df(), price=-500.0))
        assert ok is False
        assert reason == REASON_PRICE_ZERO

    def test_fails_market_cap_below_min(self):
        snap = _snapshot("200004", _valid_history_df(), market_cap=10_000_000_000)
        ok, reason = passes_quality_filter(snap)
        assert ok is False
        assert reason == REASON_MARKET_CAP_LOW

    def test_fails_insufficient_history(self):
        snap = _snapshot("200005", _valid_history_df(n=DEFAULT_MIN_HISTORY - 1))
        ok, reason = passes_quality_filter(snap)
        assert ok is False
        assert reason == REASON_INSUFFICIENT_HISTORY

    def test_custom_thresholds_respected(self):
        snap = _snapshot("200006", _valid_history_df(n=20), market_cap=1_000_000_000)
        ok, reason = passes_quality_filter(snap, min_market_cap=500_000_000, min_history=20)
        assert ok is True
        assert reason is None

    def test_check_order_price_before_market_cap(self):
        """가격 0과 시총 미달이 동시에 있으면 price_zero가 먼저 잡혀야 한다."""
        snap = _snapshot("200007", _valid_history_df(), price=0.0, market_cap=1)
        ok, reason = passes_quality_filter(snap)
        assert ok is False
        assert reason == REASON_PRICE_ZERO


# ---------------------------------------------------------------------------
# ③ flow 케이스
# ---------------------------------------------------------------------------


class TestFlowStrategy:
    def _snap(self):
        return _snapshot("300001", _sideways_df())

    def test_flow_none_scores_zero(self):
        scores = compute_strategy_scores(self._snap(), None)
        assert scores["flow"] == 0.0

    def test_flow_present_scores_above_zero(self):
        flow = FlowRank(
            ticker="300001",
            orgn_net_amt=1_000_000_000,
            frgnr_net_amt=0,
            orgn_cont_days=1,
            frgnr_cont_days=0,
            rank=10,
        )
        assert compute_strategy_scores(self._snap(), flow)["flow"] > 0.0

    def test_flow_continuous_days_bonus_below_threshold(self):
        one_day = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=1, frgnr_cont_days=0, rank=10
        )
        three_day = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=3, frgnr_cont_days=0, rank=10
        )
        one_score = compute_strategy_scores(self._snap(), one_day)["flow"]
        three_score = compute_strategy_scores(self._snap(), three_day)["flow"]
        assert three_score > one_score

    def test_flow_continuous_days_plateaus_at_three(self):
        three_day = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=3, frgnr_cont_days=0, rank=1
        )
        five_day = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=5, frgnr_cont_days=0, rank=1
        )
        three_score = compute_strategy_scores(self._snap(), three_day)["flow"]
        five_score = compute_strategy_scores(self._snap(), five_day)["flow"]
        assert three_score == five_score

    def test_flow_foreign_continuous_days_also_counts(self):
        """기관 연속일수가 0이어도 외인 연속일수만으로 가점을 받아야 한다."""
        flow = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=0, frgnr_cont_days=4, rank=1
        )
        no_cont = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=0, frgnr_cont_days=0, rank=1
        )
        assert compute_strategy_scores(self._snap(), flow)["flow"] > compute_strategy_scores(self._snap(), no_cont)["flow"]

    def test_flow_net_amount_normalization(self):
        small = FlowRank(
            ticker="300001", orgn_net_amt=100_000_000, frgnr_net_amt=0, orgn_cont_days=0, frgnr_cont_days=0, rank=50
        )
        large = FlowRank(
            ticker="300001",
            orgn_net_amt=25_000_000_000,
            frgnr_net_amt=25_000_000_000,
            orgn_cont_days=0,
            frgnr_cont_days=0,
            rank=1,
        )
        small_score = compute_strategy_scores(self._snap(), small)["flow"]
        large_score = compute_strategy_scores(self._snap(), large)["flow"]
        assert large_score > small_score
        assert large_score <= 1.0

    def test_flow_negative_net_amount_does_not_go_negative(self):
        outflow = FlowRank(
            ticker="300001",
            orgn_net_amt=-50_000_000_000,
            frgnr_net_amt=-50_000_000_000,
            orgn_cont_days=0,
            frgnr_cont_days=0,
            rank=1,
        )
        score = compute_strategy_scores(self._snap(), outflow)["flow"]
        assert score >= 0.0

    def test_atoms_record_flow_fields_for_ledger_debugging(self):
        flow = FlowRank(
            ticker="300001", orgn_net_amt=1_000_000_000, frgnr_net_amt=2_000_000_000, orgn_cont_days=4, frgnr_cont_days=1, rank=7
        )
        atoms = compute_strategy_scores(self._snap(), flow)["_atoms"]
        assert atoms["flow_rank"] == 7
        assert atoms["flow_orgn_cont_days"] == 4
        assert atoms["flow_frgnr_cont_days"] == 1
        assert atoms["flow_net_amt"] == 3_000_000_000

    def test_atoms_expose_flow_present_flag(self):
        """DQ-2: compute_strategy_scores 반환(_atoms)에 flow_present bool이
        노출돼야 한다 -- scanner.py가 factor_json 최상위에 저장하는 값과
        별개로, 이 모듈 자체의 반환값에서도 결측 여부를 직접 판단할 수
        있어야 한다는 계약."""
        assert compute_strategy_scores(self._snap(), None)["_atoms"]["flow_present"] is False

        flow = FlowRank(
            ticker="300001", orgn_net_amt=0, frgnr_net_amt=0, orgn_cont_days=0, frgnr_cont_days=0, rank=1
        )
        assert compute_strategy_scores(self._snap(), flow)["_atoms"]["flow_present"] is True


# ---------------------------------------------------------------------------
# ④ 클램프 — 스코어 전부 [0,1]
# ---------------------------------------------------------------------------


class TestScoreClamping:
    @pytest.mark.parametrize("fixture_name", list(_FIXTURE_FACTORIES.keys()))
    def test_all_scores_within_unit_interval(self, fixture_name):
        extreme_flow = FlowRank(
            ticker="X",
            orgn_net_amt=999_000_000_000,
            frgnr_net_amt=999_000_000_000,
            orgn_cont_days=99,
            frgnr_cont_days=99,
            rank=1,
        )
        df = _FIXTURE_FACTORIES[fixture_name]()
        scores = compute_strategy_scores(_snapshot("400001", df), extreme_flow)
        for strat in STRATEGIES:
            assert 0.0 <= scores[strat] <= 1.0

    def test_scores_dict_shape(self):
        scores = compute_strategy_scores(_snapshot("400002", _uptrend_df()), None)
        assert set(STRATEGIES).issubset(scores.keys())
        assert "_atoms" in scores
        for strat in STRATEGIES:
            assert isinstance(scores[strat], float)

    def test_insufficient_data_never_crashes_and_stays_bounded(self):
        """len<20이라 다수 지표가 계산 불가 — 크래시 없이 성분 0으로 수렴해야
        (스펙: '성분 계산이 데이터 부족으로 불가하면 그 성분 0, 전체 NaN 전파 금지')."""
        closes = [10000.0, 10050.0, 9950.0, 10100.0, 9900.0]
        volumes = [100_000.0] * 5
        df = _make_chart_df(closes, volumes)
        scores = compute_strategy_scores(_snapshot("400003", df), None)
        for strat in STRATEGIES:
            assert 0.0 <= scores[strat] <= 1.0
            assert scores[strat] == scores[strat]  # NaN != NaN 이므로 자기비교로 NaN 배제

    def test_empty_chart_df_never_crashes(self):
        empty_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        snap = _snapshot("400004", empty_df, price=10000.0)
        scores = compute_strategy_scores(snap, None)
        for strat in STRATEGIES:
            assert scores[strat] == 0.0


# ---------------------------------------------------------------------------
# A1: 유동성 게이트
# ---------------------------------------------------------------------------

억 = 100_000_000.0


def _liquid_snap(values, closes=None, volumes=None, market_cap=600 * 억):
    """유동성 게이트 테스트용 스냅샷 — 시총/히스토리는 항상 통과하도록 고정."""
    n = len(values)
    cl = closes if closes is not None else [10_000.0] * n
    vol = volumes if volumes is not None else [1000] * n
    df = _make_chart_df(cl, vol)
    df["value"] = [float(v) for v in values]
    return StockSnapshot(
        ticker="000000", name="테스트", price=cl[-1], market_cap=market_cap,
        per=10.0, pbr=1.0, volume=vol[-1], chart_df=df,
    )


def test_liquidity_gate_skipped_when_min_adtv_none():
    """하위 호환 — min_adtv를 안 주면 유동성 검사를 하지 않는다."""
    snap = _liquid_snap([0.5 * 억] * 60)
    passed, reason = passes_quality_filter(snap)
    assert passed is True
    assert reason is None


def test_liquidity_gate_rejects_below_min_adtv():
    snap = _liquid_snap([1.2 * 억] * 60)          # 빅솔론 대역
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_LOW


def test_liquidity_gate_accepts_at_or_above_min_adtv():
    snap = _liquid_snap([20 * 억] * 60)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is True
    assert reason is None


def test_liquidity_gate_rejects_inconsistent_downside():
    """중앙값은 통과하지만 20일 중 6일이 바닥(12억 미만)이면 배제."""
    snap = _liquid_snap([30 * 억] * 54 + [5 * 억] * 6)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_INCONSISTENT


def test_liquidity_gate_rejects_zero_volume_day():
    snap = _liquid_snap([30 * 억] * 60, volumes=[1000] * 59 + [0])
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_ZERO_VOLUME_DAY


def test_liquidity_gate_rejects_penny_stock():
    """종가 2,000원 미만은 호가단위 마찰(0.25%+)로 배제."""
    snap = _liquid_snap([30 * 억] * 60, closes=[1_900.0] * 60)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_PRICE_TOO_LOW


def test_liquidity_gate_rejects_missing_value_column():
    """value 컬럼이 없으면(구 캐시) fail-closed — 통과시키지 않는다."""
    df = _make_chart_df([10_000.0] * 60, [1000] * 60)   # value 없음
    snap = StockSnapshot(
        ticker="000000", name="구캐시", price=10_000.0, market_cap=600 * 억,
        per=10.0, pbr=1.0, volume=1000, chart_df=df,
    )
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_LOW


def test_existing_filters_still_run_first():
    """검사 순서 — 시총 미달이면 유동성 사유가 아니라 시총 사유가 나와야 한다."""
    snap = _liquid_snap([30 * 억] * 60, market_cap=100.0)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_MARKET_CAP_LOW


# ---------------------------------------------------------------------------
# A2/A3: momentum 거래량 성분 + 고가근접
# ---------------------------------------------------------------------------


def _momentum_snap(values, closes, volumes=None):
    n = len(closes)
    vol = volumes if volumes is not None else [1000] * n
    df = _make_chart_df(closes, vol)
    df["value"] = [float(v) for v in values]
    return StockSnapshot(
        ticker="000000", name="테스트", price=closes[-1], market_cap=200 * 억,
        per=10.0, pbr=1.0, volume=vol[-1], chart_df=df,
    )


def test_momentum_volume_component_zero_when_illiquid():
    """빅솔론 구조 — 거래대금이 10억 미만이면 상대 확장이 커도 vol 성분 0.

    구 수식(vol5/vol20)에서는 만점을 받던 패턴이다."""
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]   # 완만한 상승(정배열)
    values = [1 * 억] * 55 + [3 * 억] * 5                        # 상대 3배 확장, 절대는 빈약
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["adtv20_med"] is not None
    # liq_gate=0 -> 곱셈 게이트로 vol 성분이 0 -> momentum 상한 0.75
    assert scores["momentum"] <= 0.76


def test_momentum_volume_component_rewards_liquid_expansion():
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]
    values = [100 * 억] * 55 + [200 * 억] * 5   # 절대 유동성 충분 + 상대 2배
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    assert scores["momentum"] > 0.85


def test_momentum_volume_component_blocked_by_surge_cap():
    """5일 평균이 60일 평균의 5배 이상이면 펌프로 보고 vol 성분 0.

    주의: 분모 mean(value[-60:])에 서지 구간 자신이 포함돼 희석되므로,
    surge>=5.0을 만들려면 베이스 대비 원시 배율이 약 7.86배를 넘어야 한다
    (60V/(5500+5V)>=5 → V>=785.7). 여기 9배는 희석 후 surge=5.4다.
    """
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]
    values = [100 * 억] * 55 + [900 * 억] * 5   # 희석 후 surge=5.4 >= 5.0
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["value_surge"] >= 5.0
    assert scores["momentum"] <= 0.76


def test_high20_proximity_rescaled_no_free_points():
    """20일 고가의 90% 미만이면 고가근접 성분이 0 — 무상 바닥점수 제거."""
    closes = [10_000.0] * 40 + [12_000.0] + [10_000.0] * 19   # 현재가/high20 ≈ 0.833
    values = [100 * 억] * 60
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["high20_proximity"] < 0.90
    assert atoms["high20_prox_score"] == 0.0


def test_high20_prox_score_near_max_at_new_high():
    """매일 신고가 + 거래량 확장이면 고가근접 성분이 구조적 상한에 도달한다.

    상한이 1.0이 아닌 이유: 이 파일의 _make_chart_df가 high를 항상 close*1.004로
    만들어 high20_proximity의 상한이 1/1.004=0.996016이고, A3 재스케일
    (0.996016-0.90)/0.10 = 0.96016이 된다. 거래량 확장으로 confirm=1.0이 되어도
    이 값이 천장이다.
    """
    closes = [10_000.0 * (1 + 0.003 * i) for i in range(60)]   # 매일 신고가
    values = [100 * 억] * 55 + [150 * 억] * 5   # value_ratio=1.333>=1.2 -> confirm 1.0
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    assert scores["_atoms"]["high20_prox_score"] == pytest.approx(0.96, abs=0.01)


def test_high20_prox_halved_without_volume_confirmation():
    """거래량 확장(value_ratio>=1.2) 없는 고가근접은 절반 페널티."""
    closes = [10_000.0 * (1 + 0.003 * i) for i in range(60)]
    flat = [100 * 억] * 60                       # value_ratio ≈ 1.0
    s_flat = compute_strategy_scores(_momentum_snap(flat, closes), None)
    expanding = [100 * 억] * 55 + [150 * 억] * 5   # value_ratio >= 1.2
    s_exp = compute_strategy_scores(_momentum_snap(expanding, closes), None)
    assert s_flat["_atoms"]["high20_prox_score"] < s_exp["_atoms"]["high20_prox_score"]


def test_atoms_none_safe_without_value_column():
    """value 컬럼이 없어도 NaN 전파 없이 0 성분으로 수렴한다."""
    closes = [10_000.0] * 60
    df = _make_chart_df(closes, [1000] * 60)     # value 없음
    snap = StockSnapshot(
        ticker="000000", name="구캐시", price=10_000.0, market_cap=200 * 억,
        per=10.0, pbr=1.0, volume=1000, chart_df=df,
    )
    scores = compute_strategy_scores(snap, None)
    assert scores["_atoms"]["adtv20_med"] is None
    assert not math.isnan(scores["momentum"])


# ---------------------------------------------------------------------------
# 적자 배제 게이트 (2026-07-29)
# ---------------------------------------------------------------------------


def _eps_snap(eps, values=None, market_cap=600 * 억):
    """적자 배제 테스트용 — 유동성·시총·히스토리는 항상 통과하도록 고정."""
    n = 60
    vals = values if values is not None else [30 * 억] * n
    df = _make_chart_df([10_000.0] * n, [1000] * n)
    df["value"] = [float(v) for v in vals]
    return StockSnapshot(
        ticker="000000", name="테스트", price=10_000.0, market_cap=market_cap,
        per=10.0, pbr=1.0, volume=1000, chart_df=df, eps=eps,
    )


def test_negative_eps_rejected_when_enabled():
    """적자 기업(EPS<0)은 배제된다.

    2026-07-28 EOD 실물: composite 1위 코오롱티슈진(0.501)이 EPS -2,317원
    적자에 PBR 17.05였다. 문턱에 못 미쳐 매수되진 않았으나, 문턱이 조금만
    낮았다면 랭킹 1순위가 적자기업이었을 것이다 — Asness et al.(2018)이
    말한 "퀄리티 통제 없는 소형주 선별 = junk 매수"의 실물 사례.
    """
    passed, reason = passes_quality_filter(
        _eps_snap(eps=-2317), min_adtv=20 * 억, exclude_negative_eps=True
    )
    assert passed is False
    assert reason == REASON_NEGATIVE_EPS


def test_zero_eps_rejected():
    """EPS 0도 배제 — 이익이 없다는 점에서 적자와 같다."""
    passed, reason = passes_quality_filter(
        _eps_snap(eps=0), min_adtv=20 * 억, exclude_negative_eps=True
    )
    assert passed is False
    assert reason == REASON_NEGATIVE_EPS


def test_positive_eps_passes():
    passed, reason = passes_quality_filter(
        _eps_snap(eps=1278), min_adtv=20 * 억, exclude_negative_eps=True
    )
    assert passed is True
    assert reason is None


def test_missing_eps_is_fail_open():
    """EPS 결측은 통과시킨다(fail-open).

    유동성 게이트는 fail-closed지만 EPS는 다르다 — 결측이 곧 '적자'를
    뜻하지 않고(신규상장·데이터 누락), 적자 기업은 실제로 음수 값을 준다
    (코오롱티슈진 -2,317 실측). fail-closed로 두면 데이터 누락 종목이
    통째로 사라져 후보만 고갈된다.
    """
    passed, reason = passes_quality_filter(
        _eps_snap(eps=None), min_adtv=20 * 억, exclude_negative_eps=True
    )
    assert passed is True
    assert reason is None


def test_negative_eps_ignored_when_disabled():
    """킬스위치 off(기본값)면 적자여도 통과 — 하위 호환."""
    passed, reason = passes_quality_filter(_eps_snap(eps=-2317), min_adtv=20 * 억)
    assert passed is True


def test_eps_gate_runs_after_existing_filters():
    """시총 미달이면 EPS 사유가 아니라 시총 사유가 나와야 한다."""
    passed, reason = passes_quality_filter(
        _eps_snap(eps=-2317, market_cap=100.0), min_adtv=20 * 억,
        exclude_negative_eps=True,
    )
    assert reason == REASON_MARKET_CAP_LOW
