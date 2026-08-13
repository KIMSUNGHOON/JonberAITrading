import json
import pytest
from services.storage_service import StorageService


@pytest.mark.asyncio
async def test_backfill_stamps_market_context_onto_decisions(tmp_path):
    st = StorageService(db_path=str(tmp_path / "s.db"))
    await st.initialize()
    # 그날 결정 1건 삽입 (market_sentiment/flow는 write-time None).
    # save_agent_chat_decision(decision, votes) — 인자 2개(votes는 빈 리스트).
    await st.save_agent_chat_decision(
        {
            "id": "d1", "ticker": "005930", "stock_name": "삼성전자",
            "trade_date": "2026-07-16", "status": "completed", "action": "BUY",
            "confidence": 0.7, "consensus_level": 0.8, "rationale": "x",
            "market_sentiment": None, "flow": None,
        },
        [],
    )
    sentiment_json = json.dumps({"label": "bullish", "score": 0.6})
    flow_json = json.dumps({"foreign_net_amount": 500.0, "institution_net_amount": 300.0})
    await st.backfill_market_context("2026-07-16", sentiment_json, flow_json)

    # 조회: get_agent_chat_decisions(ticker=...) — SELECT * newest-first(by_date 메서드 없음)
    rows = await st.get_agent_chat_decisions(ticker="005930")
    assert rows
    assert json.loads(rows[0]["market_sentiment"])["label"] == "bullish"
    assert json.loads(rows[0]["flow"])["foreign_net_amount"] == 500.0
