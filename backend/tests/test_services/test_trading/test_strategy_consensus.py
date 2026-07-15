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


def test_knob_delta_cap_limits_change():
    current = TradingStrategy()  # max_position_pct=0.10
    votes = [_vote(adjustments={"max_position_pct": 0.30}, panelist="a"),
             _vote(adjustments={"max_position_pct": 0.30}, panelist="b")]
    out = apply_consensus(current, votes, "aggressive", 0.8, "2026-07-15", "rev-1")
    # 0.30은 바운드(≤0.30) 안이지만 델타캡: 0.10 * (1+0.25) = 0.125
    assert out.position_sizing.max_position_pct == pytest.approx(
        0.10 * (1 + MAX_RELATIVE_DELTA)
    )


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
