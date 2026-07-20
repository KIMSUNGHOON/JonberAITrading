"""Phase3 T2: strategy consensus math — pure functions, no LLM.

Known-defect corrections under test:
- single-vote != 100% consensus (min_valid gate)
- tie / below-threshold -> "no_change"
- numeric knobs: median -> hard bounds -> per-run relative delta cap
"""

import pytest

from services.trading.strategy import RiskTolerance, TradingStrategy
from services.trading.strategy_consensus import (
    KNOB_BOUNDS,
    MAX_RELATIVE_DELTA,
    STRATEGY_VOTE_SCHEMA,
    aggregate_stance,
    apply_consensus,
    semantic_fingerprint,
    valid_votes,
)


def _vote(stance="defensive", confidence=0.8, adjustments=None, panelist="risk_officer"):
    return {
        "panelist": panelist,
        "stance": stance,
        "confidence": confidence,
        "reasoning": "r",
        "key_factors": [],
        "adjustments": adjustments or {},
    }


# ---------- aggregate_stance ----------

def test_single_valid_vote_is_no_change():
    """단독투표=100% 결함(models.py:319-325)의 교정 — 1표는 절대 합의가 아니다."""
    result = aggregate_stance([_vote()], min_valid=2, threshold=0.5)
    assert result["stance"] == "no_change"
    assert result["valid_votes"] == 1


def test_error_entries_and_bad_stances_are_excluded():
    votes = [
        {"panelist": "regime_strategist", "error": "LLMAllBackendsFailed"},
        _vote(stance="mystery"),          # 미지 stance → 무효
        _vote(stance="abstain"),          # 명시적 기권도 유권자 아님 (plan ABSTAIN 배제)
        _vote(stance="defensive"),
    ]
    assert len(valid_votes(votes)) == 1
    assert aggregate_stance(votes, min_valid=2, threshold=0.5)["stance"] == "no_change"


def test_dominant_stance_wins():
    votes = [
        _vote("defensive", 0.9, panelist="risk_officer"),
        _vote("defensive", 0.7, panelist="regime_strategist"),
        _vote("aggressive", 0.8, panelist="performance_reviewer"),
    ]
    result = aggregate_stance(votes, min_valid=2, threshold=0.5)
    assert result["stance"] == "defensive"
    assert result["consensus_level"] == pytest.approx(1.6 / 2.4)
    assert result["valid_votes"] == 3


def test_three_way_split_below_threshold_is_no_change():
    votes = [_vote("defensive", 0.8), _vote("neutral", 0.8), _vote("aggressive", 0.8)]
    result = aggregate_stance(votes, min_valid=2, threshold=0.5)
    assert result["stance"] == "no_change"
    assert result["consensus_level"] == pytest.approx(1 / 3)


def test_exact_tie_is_no_change():
    votes = [_vote("defensive", 0.8), _vote("aggressive", 0.8)]
    assert aggregate_stance(votes, min_valid=2, threshold=0.5)["stance"] == "no_change"


def test_confidence_is_clamped_to_unit_interval():
    votes = [_vote("defensive", 5.0), _vote("aggressive", 0.5)]
    # clamp(5.0)=1.0 → defensive 1.0 vs aggressive 0.5 → 1.0/1.5
    result = aggregate_stance(votes, min_valid=2, threshold=0.5)
    assert result["stance"] == "defensive"
    assert result["consensus_level"] == pytest.approx(1.0 / 1.5)


# ---------- apply_consensus ----------

def test_stance_maps_to_risk_tolerance():
    current = TradingStrategy()
    out = apply_consensus(current, [_vote()], "defensive", 0.8, "2026-07-15", "rev-1")
    assert out.risk_tolerance == RiskTolerance.CONSERVATIVE
    assert current.risk_tolerance == RiskTolerance.MODERATE  # 원본 불변
    out2 = apply_consensus(current, [_vote("aggressive")], "aggressive", 0.8, "2026-07-15", "rev-2")
    assert out2.risk_tolerance == RiskTolerance.AGGRESSIVE


def test_knob_median_within_delta_cap_applies():
    current = TradingStrategy()  # stop_loss_pct=0.07
    votes = [
        _vote(adjustments={"stop_loss_pct": 0.06}, panelist="a"),
        _vote(adjustments={"stop_loss_pct": 0.08}, panelist="b"),
        _vote(adjustments={"stop_loss_pct": 0.065}, panelist="c"),
    ]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    assert out.exit_conditions.stop_loss_pct == pytest.approx(0.065)  # median
    # 원본 불변: 중첩 서브모델까지 deep copy여야 함 (shallow copy 회귀 감지)
    assert current.exit_conditions.stop_loss_pct == pytest.approx(0.07)


def test_knob_delta_cap_limits_change():
    current = TradingStrategy()  # max_position_pct=0.10
    votes = [_vote(adjustments={"max_position_pct": 0.30}, panelist="a"),
             _vote(adjustments={"max_position_pct": 0.30}, panelist="b")]
    out = apply_consensus(current, votes, "aggressive", 0.8, "2026-07-15", "rev-1")
    # 0.30은 바운드(≤0.30) 안이지만 델타캡: 0.10 * (1+0.25) = 0.125
    assert out.position_sizing.max_position_pct == pytest.approx(
        0.10 * (1 + MAX_RELATIVE_DELTA)
    )
    # 원본 불변: 중첩 서브모델까지 deep copy여야 함 (shallow copy 회귀 감지)
    assert current.position_sizing.max_position_pct == pytest.approx(0.10)


def test_knob_hard_bounds_clamp_before_delta():
    current = TradingStrategy()  # min_cash_ratio=0.20
    votes = [_vote(adjustments={"min_cash_ratio": 0.95}, panelist="a"),
             _vote(adjustments={"min_cash_ratio": 0.95}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    lo, hi = KNOB_BOUNDS["min_cash_ratio"]
    # 0.95 → 바운드 0.50 → 델타캡 0.20*1.25=0.25
    assert out.position_sizing.min_cash_ratio == pytest.approx(
        min(hi, 0.20 * (1 + MAX_RELATIVE_DELTA))
    )


def test_int_knob_rounds_and_caps():
    current = TradingStrategy()  # max_positions=10
    votes = [_vote(adjustments={"max_positions": 3}, panelist="a"),
             _vote(adjustments={"max_positions": 3}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    # 델타캡: 10*(1-0.25)=7.5 → round → 8 (int 노브는 round 후 int)
    assert out.position_sizing.max_positions == 8
    assert isinstance(out.position_sizing.max_positions, int)


def test_no_adjustments_leaves_knobs_untouched():
    current = TradingStrategy()
    out = apply_consensus(current, [_vote(), _vote(panelist="b")],
                          "neutral", 0.9, "2026-07-15", "rev-1")
    assert semantic_fingerprint(out)[1:] == semantic_fingerprint(current)[1:]
    # stance=neutral → MODERATE(기본과 동일) → 지문 전체 동일
    assert semantic_fingerprint(out) == semantic_fingerprint(current)


def test_non_numeric_adjustment_is_ignored():
    current = TradingStrategy()
    votes = [_vote(adjustments={"stop_loss_pct": "many"}, panelist="a"),
             _vote(adjustments={"stop_loss_pct": 0.06}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    assert out.exit_conditions.stop_loss_pct == pytest.approx(0.06)


def test_hostile_adjustments_shape_is_non_vote_not_run_killer():
    """One malformed panelist (adjustments as a list — plausible LLM output,
    since the schema only validates top-level required keys) must not raise
    / abort the whole consensus; it's simply excluded from that knob's
    electorate, and a valid co-panelist's suggestion still applies."""
    current = TradingStrategy()  # stop_loss_pct=0.07
    votes = [
        _vote(adjustments=[{"stop_loss_pct": 0.05}], panelist="a"),  # hostile shape
        _vote(adjustments={"stop_loss_pct": 0.06}, panelist="b"),
    ]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    assert out.exit_conditions.stop_loss_pct == pytest.approx(0.06)


def test_bool_adjustment_is_rejected():
    """bool은 int 서브클래스지만 노브 값이 아니다 — True가 1.0으로 새면 안 됨."""
    current = TradingStrategy()  # stop_loss_pct=0.07
    votes = [_vote(adjustments={"stop_loss_pct": True}, panelist="a"),
             _vote(adjustments={"stop_loss_pct": True}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    # 두 제안 모두 bool → 무시 → 노브 불변
    assert out.exit_conditions.stop_loss_pct == pytest.approx(0.07)


def test_identity_and_provenance_stamp():
    current = TradingStrategy()
    out = apply_consensus(current, [_vote()], "defensive", 0.72, "2026-07-15", "rev-9")
    assert out.id == "rev-9"
    assert "2026-07-15" in out.description and "defensive" in out.description
    assert out.name == "EOD 적응형 전략"  # 기본 name('My Strategy')일 때만 개명


def test_user_named_strategy_keeps_its_name():
    current = TradingStrategy(name="나의 가치투자")
    out = apply_consensus(current, [_vote()], "defensive", 0.72, "2026-07-15", "rev-9")
    assert out.name == "나의 가치투자"


def test_vote_schema_shape():
    props = STRATEGY_VOTE_SCHEMA["properties"]
    assert set(STRATEGY_VOTE_SCHEMA["required"]) == {"stance", "confidence", "reasoning"}
    assert props["stance"]["enum"] == ["aggressive", "neutral", "defensive"]
    assert set(props["adjustments"]["properties"]) == set(KNOB_BOUNDS)


# ---------- max_trade_notional_pct (Phase5 결정B) ----------

def test_notional_knob_bound_is_percent_5_to_30():
    """단위 회귀 가드: 다른 5개 노브(소수분율)와 달리 퍼센트 그대로 [5,30] —
    strategy_apply.py STRATEGY_MAPPED_FIELDS와 동일 바운드로 정합."""
    assert KNOB_BOUNDS["max_trade_notional_pct"] == (5.0, 30.0)


def test_notional_knob_hard_bounds_clamp():
    from services.trading.strategy_consensus import clamp_knob
    assert clamp_knob("max_trade_notional_pct", 40.0) == 30.0
    assert clamp_knob("max_trade_notional_pct", 2.0) == 5.0


def test_notional_knob_writes_to_position_sizing():
    """apply_consensus가 max_trade_notional_pct 제안을 median -> hard bound
    -> 델타캡 순으로 클램프해 strategy.position_sizing.max_trade_notional_pct
    에 실제로 반영하는지 (Task2가 심어둔 필드에 대한 배선 검증)."""
    current = TradingStrategy()  # max_trade_notional_pct=15.0 (기본)
    assert current.position_sizing.max_trade_notional_pct == pytest.approx(15.0)
    votes = [_vote(adjustments={"max_trade_notional_pct": 40.0}, panelist="a"),
             _vote(adjustments={"max_trade_notional_pct": 40.0}, panelist="b")]
    out = apply_consensus(current, votes, "aggressive", 0.8, "2026-07-15", "rev-1")
    # 40.0은 바운드(<=30) 밖이지만, 하드바운드 클램프 이후에도 델타캡:
    # 15.0 * (1+0.25) = 18.75가 실제 상한이 된다.
    assert out.position_sizing.max_trade_notional_pct == pytest.approx(
        15.0 * (1 + MAX_RELATIVE_DELTA)
    )
    # 원본 불변
    assert current.position_sizing.max_trade_notional_pct == pytest.approx(15.0)


def test_notional_knob_low_suggestion_clamps_to_hard_bound():
    """현재값을 바운드 하한 근처로 세팅해 델타캡이 아니라 하드바운드가
    실제로 걸리는 경로도 확인 (40->30, 2->5 클램프 사양의 apply_consensus 경로)."""
    current = TradingStrategy()
    current.position_sizing.max_trade_notional_pct = 6.0
    votes = [_vote(adjustments={"max_trade_notional_pct": 2.0}, panelist="a"),
             _vote(adjustments={"max_trade_notional_pct": 2.0}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    lo, hi = KNOB_BOUNDS["max_trade_notional_pct"]
    assert out.position_sizing.max_trade_notional_pct == pytest.approx(
        max(lo, 6.0 * (1 - MAX_RELATIVE_DELTA))
    )


# ---------- consensus_threshold (E-3, 진입 활성화) ----------
#
# 배경: agent_chat models.py:272/chat_room.py:55에 4-에이전트 합의 문턱
# 0.75가 하드코딩돼 있었다(조정 불가). EntryConditions.consensus_threshold
# 신설(strategy.py, Field ge=0.5 le=0.9, 기본 0.75 불변)로 세션 생성 시
# 활성 전략에서 값을 읽어 주입할 수 있게 됐고, 여기 KNOB_BOUNDS[0.60,0.85]
# 는 EOD 전략 합의가 그 값을 조정할 수 있는 안전 레일(수동 PUT은 Field의
# 더 넓은 0.5-0.9까지 허용 — clamp_knob이 coordinator._build_strategy_context
# 소비 경로에서 별도로 방어).

def test_consensus_threshold_knob_bound_is_0_60_to_0_85():
    """단위 회귀 가드: strategy.py Field 범위(0.5-0.9)보다 좁은 EOD 조정
    안전 레일 — max_trade_notional_pct와 동일한 '더 좁은 하드레일' 패턴."""
    assert KNOB_BOUNDS["consensus_threshold"] == (0.60, 0.85)


def test_consensus_threshold_knob_hard_bounds_clamp():
    from services.trading.strategy_consensus import clamp_knob
    assert clamp_knob("consensus_threshold", 0.95) == 0.85
    assert clamp_knob("consensus_threshold", 0.10) == 0.60


def test_consensus_threshold_knob_writes_to_entry_conditions():
    """apply_consensus가 consensus_threshold 제안을 median -> hard bound ->
    델타캡 순으로 클램프해 strategy.entry_conditions.consensus_threshold에
    실제로 반영하는지 (E-3 KNOB_BOUNDS 배선 검증)."""
    current = TradingStrategy()  # consensus_threshold=0.75 (기본)
    assert current.entry_conditions.consensus_threshold == pytest.approx(0.75)
    votes = [_vote(adjustments={"consensus_threshold": 0.95}, panelist="a"),
             _vote(adjustments={"consensus_threshold": 0.95}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    hi = KNOB_BOUNDS["consensus_threshold"][1]
    # 0.95는 하드바운드(<=0.85) 밖 -> 클램프 0.85, 델타캡 상한 0.75*1.25=
    # 0.9375는 0.85보다 넓어 하드바운드가 실제 상한이 된다.
    assert out.entry_conditions.consensus_threshold == pytest.approx(
        min(hi, 0.75 * (1 + MAX_RELATIVE_DELTA))
    )
    # 원본 불변: 중첩 서브모델까지 deep copy여야 함 (shallow copy 회귀 감지)
    assert current.entry_conditions.consensus_threshold == pytest.approx(0.75)


def test_consensus_threshold_knob_delta_caps_before_hard_bound():
    """현재값이 바운드 상단 근처일 때, 극단적으로 낮은 제안은 하드바운드가
    아니라 델타캡에 먼저 걸린다(0.63 != 하드바운드 하한 0.60)."""
    current = TradingStrategy()
    current.entry_conditions.consensus_threshold = 0.84
    votes = [_vote(adjustments={"consensus_threshold": 0.10}, panelist="a"),
             _vote(adjustments={"consensus_threshold": 0.10}, panelist="b")]
    out = apply_consensus(current, votes, "defensive", 0.8, "2026-07-15", "rev-1")
    assert out.entry_conditions.consensus_threshold == pytest.approx(
        0.84 * (1 - MAX_RELATIVE_DELTA)
    )


def test_consensus_threshold_default_is_0_75_unchanged():
    """절대 원칙: 기본값 0.75 불변 — 전략 미조정 시 배포 직후 거동 동일."""
    assert TradingStrategy().entry_conditions.consensus_threshold == pytest.approx(0.75)
