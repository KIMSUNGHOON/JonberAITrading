"""보유 종목에 그날의 4에이전트 리서치를 붙인다."""
import json
import pytest
from unittest.mock import AsyncMock

from services.reports.collect import attach_research
from services.reports.models import PositionResearch


def _unresolved_pos(ticker="004370") -> PositionResearch:
    """`collect_positions`가 실제로 채우는 결함 상태 -- 라이브
    `ManagedPosition.stock_name`이 종목코드와 같아 name==ticker가 된다
    (2026-08-13 postmarket 리포트 첫 실물: "004370 004370" 헤더)."""
    return PositionResearch(
        ticker=ticker, name=ticker, quantity=25, avg_price=1.0,
        current_price=1.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def _pos(ticker="028670") -> PositionResearch:
    return PositionResearch(
        ticker=ticker, name="팬오션", quantity=3115, avg_price=5969.0,
        current_price=5710.0, pnl_pct=-5.13, stop_loss=5520.0,
        stop_loss_source="coordinator",
    )


def _storage(decisions, votes):
    s = AsyncMock()
    s.get_ticker_day_decisions_full = AsyncMock(return_value=decisions)
    s.get_agent_chat_votes = AsyncMock(return_value=votes)
    return s


@pytest.mark.asyncio
async def test_attaches_latest_decision_and_votes():
    decisions = [
        {"id": "d1", "action": "HOLD", "consensus_level": 0.70,
         "behavioral_signals": None, "news_count": 10, "news_sentiment": "neutral"},
        {"id": "d2", "action": "HOLD", "consensus_level": 0.7425,
         "behavioral_signals": json.dumps({"rsi": 57.19, "volume_ratio": 0.6,
                                           "trend": "bullish", "cross": "none"}),
         "news_count": 50, "news_sentiment": "neutral"},
    ]
    votes = [
        {"agent_type": "technical", "vote": "hold", "confidence": 0.58,
         "reasoning": "정배열 유지" * 40,
         "key_factors": json.dumps(["가격이 20·60일선 위에서 정배열"])},
        {"agent_type": "fundamental", "vote": "buy", "confidence": 0.62,
         "reasoning": "저평가", "key_factors": json.dumps(["PER 10.11배 저평가"])},
    ]
    p = _pos()
    await attach_research([p], "2026-08-13", _storage(decisions, votes))

    assert p.discussion_count == 2
    assert p.action == "HOLD"                 # 최신(d2) 기준
    assert round(p.consensus, 4) == 0.7425
    assert p.signals["rsi"] == 57.19
    assert [v.agent_type for v in p.votes] == ["technical", "fundamental"]
    assert p.votes[0].headline == "가격이 20·60일선 위에서 정배열"   # key_factors 우선
    assert p.votes[1].is_dissent is True       # buy != HOLD
    assert p.dissent_count == 1


@pytest.mark.asyncio
async def test_headline_falls_back_to_truncated_reasoning():
    votes = [{"agent_type": "risk", "vote": "hold", "confidence": 0.62,
              "reasoning": "가" * 300, "key_factors": None}]
    p = _pos()
    await attach_research(
        [p], "2026-08-13",
        _storage([{"id": "d1", "action": "HOLD", "consensus_level": 0.9,
                   "behavioral_signals": None}], votes),
    )
    assert len(p.votes[0].headline) == 121      # 120자 + '…'
    assert p.votes[0].headline.endswith("…")


@pytest.mark.asyncio
async def test_no_decisions_leaves_position_intact():
    """신규 편입 종목의 정상 상태 — 빈 카드가 되어야지 예외가 되면 안 된다."""
    p = _pos()
    await attach_research([p], "2026-08-13", _storage([], []))
    assert p.discussion_count == 0
    assert p.action is None
    assert p.votes == []


@pytest.mark.asyncio
async def test_storage_error_does_not_raise():
    s = AsyncMock()
    s.get_ticker_day_decisions_full = AsyncMock(side_effect=RuntimeError("db down"))
    p = _pos()
    await attach_research([p], "2026-08-13", s)     # 예외가 나면 실패
    assert p.discussion_count == 0


@pytest.mark.asyncio
async def test_malformed_behavioral_signals_is_ignored():
    p = _pos()
    await attach_research(
        [p], "2026-08-13",
        _storage([{"id": "d1", "action": "HOLD", "consensus_level": 0.9,
                   "behavioral_signals": "not json"}], []),
    )
    assert p.signals == {}


@pytest.mark.asyncio
async def test_name_equal_to_ticker_is_corrected_from_decision_stock_name():
    """결함 1 -- 결정 행의 `stock_name`(제대로 된 한글명)으로 보정한다."""
    p = _unresolved_pos()
    decisions = [{"id": "d1", "action": "HOLD", "consensus_level": 0.7,
                  "behavioral_signals": None, "stock_name": "농심"}]
    await attach_research([p], "2026-08-13", _storage(decisions, []))
    assert p.name == "농심"


@pytest.mark.asyncio
async def test_blank_name_is_corrected_from_decision_stock_name():
    p = PositionResearch(
        ticker="004370", name="", quantity=25, avg_price=1.0,
        current_price=1.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )
    decisions = [{"id": "d1", "action": "HOLD", "consensus_level": 0.7,
                  "behavioral_signals": None, "stock_name": "농심"}]
    await attach_research([p], "2026-08-13", _storage(decisions, []))
    assert p.name == "농심"


@pytest.mark.asyncio
async def test_already_correct_name_is_not_overwritten():
    """이미 제대로 된 이름이 있으면 결정 행의 stock_name으로 덮지 않는다."""
    p = _pos()  # name="팬오션"
    decisions = [{"id": "d1", "action": "HOLD", "consensus_level": 0.7,
                  "behavioral_signals": None, "stock_name": "이상한이름"}]
    await attach_research([p], "2026-08-13", _storage(decisions, []))
    assert p.name == "팬오션"


@pytest.mark.asyncio
async def test_name_correction_skipped_when_decision_stock_name_is_blank():
    """덮어쓸 이름이 없으면 name==ticker 상태를 그대로 둔다 -- attach_news가
    뒤에서 이 상태(name==ticker)를 보고 뉴스 조회를 스킵한다."""
    p = _unresolved_pos()
    decisions = [{"id": "d1", "action": "HOLD", "consensus_level": 0.7,
                  "behavioral_signals": None, "stock_name": None}]
    await attach_research([p], "2026-08-13", _storage(decisions, []))
    assert p.name == "004370"
