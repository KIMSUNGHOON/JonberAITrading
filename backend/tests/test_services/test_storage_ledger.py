import pytest, uuid
from services.storage_service import StorageService

@pytest.mark.asyncio
async def test_agent_chat_decision_roundtrip(tmp_path):
    st = StorageService(db_path=str(tmp_path / "t.db"))
    did = str(uuid.uuid4())
    dec = {
        "id": did, "ticker": "005930", "stock_name": "삼성전자",
        "trade_date": "2026-07-15", "status": "decided", "action": "BUY",
        "confidence": 0.69, "consensus_level": 0.82, "rationale": "돌파",
        "dissenting_opinions": ["리스크 과열"], "entry_price": 277000.0,
        "stop_loss": 246000.0, "take_profit": 289000.0, "position_pct": 0.1,
        "news_sentiment": "positive", "news_count": 12,
        "behavioral_signals": {"volume_ratio": 1.8, "trend": "bullish", "cross": "golden_cross", "rsi": 61.0},
        "market_sentiment": None, "flow": None,
    }
    votes = [
        {"decision_id": did, "agent_type": "technical", "vote": "buy", "confidence": 0.7,
         "reasoning": "골든크로스", "key_factors": ["golden_cross"],
         "suggested_position_pct": None, "suggested_stop_loss_pct": None, "suggested_take_profit_pct": None},
        {"decision_id": did, "agent_type": "risk", "vote": "hold", "confidence": 0.6,
         "reasoning": "변동성", "key_factors": ["vol"], "suggested_position_pct": 0.1,
         "suggested_stop_loss_pct": 0.05, "suggested_take_profit_pct": 0.08},
    ]
    assert await st.save_agent_chat_decision(dec, votes) is True

    st2 = StorageService(db_path=str(tmp_path / "t.db"))  # reopen → durable
    got = await st2.get_agent_chat_decisions(ticker="005930")
    assert len(got) == 1 and got[0]["action"] == "BUY" and got[0]["consensus_level"] == 0.82
    import json
    assert json.loads(got[0]["behavioral_signals"])["cross"] == "golden_cross"
    assert json.loads(got[0]["dissenting_opinions"]) == ["리스크 과열"]
    v = await st2.get_agent_chat_votes(did)
    assert len(v) == 2 and {r["agent_type"] for r in v} == {"technical", "risk"}
