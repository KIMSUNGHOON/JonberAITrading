"""Phase4 T4: calibration-driven dynamic consensus weights.

- single source: DEFAULT_AGENT_WEIGHTS replaces the 3 hardcoded dicts
- opt-in: agent_weights=None == legacy behavior exactly
- tilt formula + clamps + min-sample gate
- single-vote guard: <2 scoring votes -> consensus 0.0 (audit defect C seal)
- panel-coverage factor: raw ratio * (participating_weight / panel_weight) so
  a partially-answering panel (LLM dropout) can't report full agreement
  (audit 2026-07-22 Finding 1/4, second pass — 2026-08-04)
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.agent_chat.models import (
    DEFAULT_AGENT_WEIGHTS, AgentType, AgentVote, ChatSession, VoteType,
    calculate_weighted_confidence,
)

pytestmark = pytest.mark.asyncio


def _vote(agent_type, vote=VoteType.BUY, confidence=0.8):
    return AgentVote(agent_type=agent_type, vote=vote, confidence=confidence, reasoning="r")


def _session(votes, weights=None):
    session = ChatSession(ticker="005930", stock_name="삼성전자")
    session.votes = votes
    if weights is not None:
        session.agent_weights = weights
    return session


def test_default_weights_constant_shape():
    assert DEFAULT_AGENT_WEIGHTS == {
        AgentType.TECHNICAL: 0.25, AgentType.FUNDAMENTAL: 0.25,
        AgentType.SENTIMENT: 0.20, AgentType.RISK: 0.30,
    }
    assert AgentType.MODERATOR not in DEFAULT_AGENT_WEIGHTS


def test_consensus_without_weights_matches_legacy():
    """No-op proof: full 4-of-4 panel votes -> participating_weight ==
    panel_weight -> coverage == 1.0 -> unchanged from pre-coverage-fix math.
    This is what proves the panel-coverage factor does not disturb normal
    (everyone-answered) operation."""
    votes = [_vote(AgentType.TECHNICAL), _vote(AgentType.FUNDAMENTAL),
             _vote(AgentType.SENTIMENT, VoteType.SELL), _vote(AgentType.RISK, VoteType.HOLD)]
    session = _session(votes)
    # legacy: bull=(0.25+0.25)*0.8=0.4, bear=0.2*0.8=0.16, neutral=0.3*0.8=0.24
    assert session.calculate_consensus() == pytest.approx(0.4 / 0.8)


def test_consensus_uses_injected_weights():
    """Only technical+risk vote (2 of 4 panel seats) -> coverage < 1 scales
    the raw ratio down, on top of the injected-weight tilt."""
    votes = [_vote(AgentType.TECHNICAL), _vote(AgentType.RISK, VoteType.SELL)]
    session = _session(votes, weights={"technical": 0.375, "risk": 0.15})
    # raw: bull=0.375*0.8=0.3, bear=0.15*0.8=0.12 -> 0.3/0.42 = 5/7
    # panel_weight (tech 0.375 + fundamental fallback 0.25 + sentiment
    # fallback 0.20 + risk 0.15) = 0.975; participating_weight = 0.375+0.15
    # = 0.525 -> coverage = 0.525/0.975 = 7/13
    # consensus = (5/7) * (7/13) = 5/13
    assert session.calculate_consensus() == pytest.approx(5 / 13)


def test_single_vote_guard_consensus_zero():
    """단독투표=100% 결함 봉합 — 유효 1표는 합의 0.0 (75% 게이트 미달 확정)."""
    session = _session([_vote(AgentType.TECHNICAL, VoteType.STRONG_BUY, 0.95)])
    assert session.calculate_consensus() == 0.0
    assert session.consensus_level == 0.0


def test_two_votes_still_score():
    """2 of 4 panel seats vote (>= 2-scoring-vote guard passes) and fully
    agree -> raw ratio is 1.0, but panel-coverage (0.5/1.0=0.5) must scale
    that down. Pre-fix this asserted 1.0 -- a half-dead panel manufacturing
    full-confidence consensus was exactly the audit 2026-07-22 Finding 1/4
    inflation this fix seals."""
    session = _session([_vote(AgentType.TECHNICAL), _vote(AgentType.FUNDAMENTAL)])
    assert session.calculate_consensus() == pytest.approx(0.5)


def test_weighted_confidence_accepts_weights_param():
    votes = [_vote(AgentType.TECHNICAL, confidence=1.0),
             _vote(AgentType.RISK, confidence=0.5)]
    legacy = calculate_weighted_confidence(votes)
    assert legacy == pytest.approx((0.25 * 1.0 + 0.30 * 0.5) / 0.55)
    tilted = calculate_weighted_confidence(votes, {"technical": 0.375, "risk": 0.15})
    assert tilted == pytest.approx((0.375 * 1.0 + 0.15 * 0.5) / 0.525)


def _vote_conf(agent_type, vote, confidence):
    return AgentVote(agent_type=agent_type, vote=vote, confidence=confidence, reasoning="r")


# ---------- panel-coverage factor (audit 2026-07-22 Finding 1/4, 2nd pass) ----------


def test_moderator_vote_excluded_from_participating_weight():
    """모더레이터 투표가 self.votes에 섞여 있어도(정상 흐름에선 안 생기지만
    방어적으로) participating_weight에는 절대 얹히면 안 된다 — 얹히면
    resolve_agent_weight의 0.25 폴백이 커버리지를 부풀린다(제약 #2).
    tech+fund 2석만 실제 패널 참여, moderator는 continue로 제외 ->
    coverage = 0.5/1.0 = 0.5 (0.75가 아니라)."""
    votes = [_vote(AgentType.TECHNICAL), _vote(AgentType.FUNDAMENTAL),
             _vote_conf(AgentType.MODERATOR, VoteType.BUY, 1.0)]
    session = _session(votes)
    assert session.calculate_consensus() == pytest.approx(0.5)


def test_full_panel_plus_moderator_consensus_does_not_exceed_one():
    """패널 4석 전원 만장일치 + 모더레이터 투표까지 섞여도 커버리지는
    1.0을 넘을 수 없다 (모더레이터 폴백 가중이 새면 participating_weight >
    panel_weight가 되어 합의가 100%를 초과해 소비자 쪽 게이트 비교를
    무의미하게 만들 수 있었다)."""
    votes = [
        _vote_conf(AgentType.TECHNICAL, VoteType.STRONG_BUY, 0.9),
        _vote_conf(AgentType.FUNDAMENTAL, VoteType.STRONG_BUY, 0.9),
        _vote_conf(AgentType.SENTIMENT, VoteType.STRONG_BUY, 0.9),
        _vote_conf(AgentType.RISK, VoteType.STRONG_BUY, 0.9),
        _vote_conf(AgentType.MODERATOR, VoteType.BUY, 1.0),
    ]
    session = _session(votes)
    assert session.calculate_consensus() == pytest.approx(1.0)


def test_calculate_consensus_and_consensus_from_votes_agree():
    """두 진입점(calculate_consensus/_consensus_from_votes)이 같은 votes에
    대해 항상 같은 값을 내야 한다 — 갈라지면 tilt_changed_gate_verdict의
    두 경로 비교가 허위 경고를 낸다(models.py :433-434)."""
    votes = [_vote(AgentType.TECHNICAL), _vote(AgentType.RISK, VoteType.SELL)]
    session = _session(votes, weights={"technical": 0.375, "risk": 0.15})
    live = session.calculate_consensus()
    pure = session._consensus_from_votes(session.agent_weights)
    assert live == pytest.approx(pure)
    assert session.consensus_level == pytest.approx(live)


def test_tilt_changed_gate_verdict_none_without_weights():
    """agent_weights 없음(옵트인 안 함) → 비교 자체가 무의미하므로 None."""
    votes = [_vote(AgentType.TECHNICAL), _vote(AgentType.FUNDAMENTAL)]
    session = _session(votes)
    session.calculate_consensus()
    assert session.tilt_changed_gate_verdict() is None


def test_tilt_changed_gate_verdict_false_when_unanimous():
    """만장일치 강세 → 가중/기본 모두 게이트 통과(threshold 0.75) → 뒤집힘 없음."""
    votes = [
        _vote_conf(AgentType.TECHNICAL, VoteType.STRONG_BUY, 0.95),
        _vote_conf(AgentType.FUNDAMENTAL, VoteType.STRONG_BUY, 0.95),
        _vote_conf(AgentType.SENTIMENT, VoteType.STRONG_BUY, 0.90),
        _vote_conf(AgentType.RISK, VoteType.STRONG_BUY, 0.90),
    ]
    session = _session(votes, weights={"technical": 0.375, "fundamental": 0.375,
                                        "sentiment": 0.10, "risk": 0.15})
    session.calculate_consensus()
    assert session.tilt_changed_gate_verdict() is False


def test_tilt_changed_gate_verdict_true_when_flipped():
    """최종리뷰 산술 예: TECH/FUND 0.375 BUY conf 0.95 + RISK 0.15 SELL 0.90 +
    SENT 0.10 HOLD 0.90 → 가중 합의 0.76>=0.75(통과), 기본 가중 0.514<0.75
    (미달) → 게이트 판정이 가중 때문에 뒤집힘 → True."""
    votes = [
        _vote_conf(AgentType.TECHNICAL, VoteType.BUY, 0.95),
        _vote_conf(AgentType.FUNDAMENTAL, VoteType.BUY, 0.95),
        _vote_conf(AgentType.RISK, VoteType.SELL, 0.90),
        _vote_conf(AgentType.SENTIMENT, VoteType.HOLD, 0.90),
    ]
    session = _session(votes, weights={"technical": 0.375, "fundamental": 0.375,
                                        "sentiment": 0.10, "risk": 0.15})
    consensus = session.calculate_consensus()
    assert consensus == pytest.approx(0.76, abs=0.005)
    assert session.tilt_changed_gate_verdict() is True


def test_majority_direction_uses_same_weights():
    votes = [_vote(AgentType.TECHNICAL, VoteType.BUY, 0.9),
             _vote(AgentType.RISK, VoteType.SELL, 0.9)]
    # legacy: RISK 0.30 > TECH 0.25 → SELL 지배
    assert _session(votes).get_majority_direction() in (VoteType.SELL, VoteType.STRONG_SELL)
    # 틸트: TECH 0.375 > RISK 0.15 → BUY 지배
    tilted = _session(votes, weights={"technical": 0.375, "risk": 0.15})
    assert tilted.get_majority_direction() in (VoteType.BUY, VoteType.STRONG_BUY)


# ---------- _compute_agent_weights ----------

def _calib_row(agent_type, accuracy, scored, created="2026-07-16"):
    return {"agent_type": agent_type, "accuracy": accuracy,
            "decisions_scored": scored, "created_at": created}


async def test_compute_weights_tilts_and_clamps():
    from services.agent_chat.coordinator import ChatCoordinator

    rows = [
        _calib_row("technical", 1.0, 10),   # ×1.5 → 0.375
        _calib_row("sentiment", 0.0, 10),   # ×0.5 → 0.10
        _calib_row("risk", 0.5, 10),        # ×1.0 → 0.30 (중립)
        _calib_row("fundamental", 0.9, 3),  # 표본 미달 → base 0.25
    ]
    storage = AsyncMock()
    storage.get_agent_calibration = AsyncMock(return_value=rows)
    coordinator = ChatCoordinator()
    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        weights = await coordinator._compute_agent_weights()
    assert weights["technical"] == pytest.approx(0.375)
    assert weights["sentiment"] == pytest.approx(0.10)
    assert weights["risk"] == pytest.approx(0.30)
    assert weights["fundamental"] == pytest.approx(0.25)
    assert "moderator" not in weights


async def test_compute_weights_no_calibration_returns_none():
    from services.agent_chat.coordinator import ChatCoordinator

    storage = AsyncMock()
    storage.get_agent_calibration = AsyncMock(return_value=[])
    coordinator = ChatCoordinator()
    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(return_value=storage)):
        assert await coordinator._compute_agent_weights() is None


async def test_compute_weights_failure_is_none():
    from services.agent_chat.coordinator import ChatCoordinator

    coordinator = ChatCoordinator()
    with patch("services.storage_service.get_storage_service",
               new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await coordinator._compute_agent_weights() is None


def test_chat_room_injects_weights_into_session():
    from services.agent_chat.chat_room import ChatRoom
    from services.agent_chat.models import MarketContext

    ctx = MarketContext(ticker="005930", stock_name="삼성전자",
                        current_price=70000, price_change_pct=0.0)
    room = ChatRoom("005930", "삼성전자", ctx, agent_weights={"technical": 0.3})
    assert room.session.agent_weights == {"technical": 0.3}
    room2 = ChatRoom("005930", "삼성전자", ctx)
    assert room2.session.agent_weights is None
