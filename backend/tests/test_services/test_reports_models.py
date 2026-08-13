"""리포트 데이터 모델 — 계산 필드와 결측 허용."""
import pytest

from services.reports.models import AgentVote, PositionResearch

pytestmark = pytest.mark.usefixtures("isolated_storage_service")


def test_stop_margin_is_computed_from_current_and_stop():
    p = PositionResearch(
        ticker="028670", name="팬오션", quantity=3115,
        avg_price=5969.0, current_price=5710.0, pnl_pct=-5.13,
        stop_loss=5520.0, stop_loss_source="coordinator",
    )
    assert round(p.stop_margin_pct, 2) == 3.33


def test_stop_margin_is_none_when_stop_missing():
    """손절가가 없는데 0%로 표시하면 '즉시 손절'로 오독된다."""
    p = PositionResearch(
        ticker="005930", name="삼성전자", quantity=1,
        avg_price=1.0, current_price=1.0, pnl_pct=0.0,
        stop_loss=None, stop_loss_source=None,
    )
    assert p.stop_margin_pct is None


def test_dissent_count_counts_votes_differing_from_action():
    p = PositionResearch(
        ticker="028670", name="팬오션", quantity=1,
        avg_price=1.0, current_price=1.0, pnl_pct=0.0,
        stop_loss=None, stop_loss_source=None,
        action="HOLD",
        votes=[
            AgentVote("technical", "hold", 0.58, "정배열", False),
            AgentVote("fundamental", "buy", 0.62, "PER 10.11", False),
        ],
    )
    assert p.dissent_count == 1
    assert p.votes[1].is_dissent is False  # 원본은 건드리지 않는다


def test_empty_position_renders_nothing_but_does_not_raise():
    p = PositionResearch(
        ticker="X", name="X", quantity=0, avg_price=0.0,
        current_price=0.0, pnl_pct=0.0, stop_loss=None, stop_loss_source=None,
    )
    assert p.discussion_count == 0
    assert p.votes == []
    assert p.news == []


@pytest.mark.asyncio
async def test_full_decisions_filters_by_kst_trade_date(isolated_storage_service):
    """created_at은 UTC다. KST 2026-08-13 00:30은 UTC 2026-08-12 15:30이다."""
    s = isolated_storage_service
    await s.initialize()
    import aiosqlite
    async with aiosqlite.connect(str(s.db_path)) as conn:
        await conn.execute(
            "INSERT INTO agent_chat_decisions (id,ticker,trade_date,action,"
            "consensus_level,rationale,created_at) VALUES (?,?,?,?,?,?,?)",
            ("d1", "028670", "2026-08-13", "HOLD", 0.79, "r", "2026-08-12 15:30:00"),
        )
        await conn.execute(
            "INSERT INTO agent_chat_decisions (id,ticker,trade_date,action,"
            "consensus_level,rationale,created_at) VALUES (?,?,?,?,?,?,?)",
            ("d2", "028670", "2026-08-12", "HOLD", 0.70, "r", "2026-08-11 15:30:00"),
        )
        await conn.commit()

    rows = await s.get_ticker_day_decisions_full("028670", "2026-08-13")
    assert [r["id"] for r in rows] == ["d1"]
    assert rows[0]["consensus_level"] == 0.79
