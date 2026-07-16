import pytest
from services.trading.regime import compute_market_regime


def test_compose_bullish_when_all_positive():
    breadth = {"id": "x", "trade_date": "2026-07-16", "breadth_buy": 300,
               "breadth_sell": 50, "breadth_hold": 100, "breadth_ratio": 0.55,
               "regime_label": "risk_on", "source": "scanner"}
    index = {"index_kospi": 2500.0, "index_kospi_chg_pct": 1.5,
             "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 1.0}
    flow = {"foreign_net_amount": 500.0, "institution_net_amount": 300.0}
    out = compute_market_regime(breadth, index, flow, "2026-07-16", threshold=0.1)
    assert out["market_sentiment_label"] == "bullish"
    assert out["sentiment_score"] > 0.1
    assert out["index_kospi_chg_pct"] == 1.5
    assert out["foreign_net_amount"] == 500.0
    # breadth 필드 보존 (하위호환)
    assert out["regime_label"] == "risk_on"
    assert out["id"] == "x"


def test_compose_bearish_when_all_negative():
    breadth = {"id": "y", "trade_date": "2026-07-16", "breadth_buy": 40,
               "breadth_sell": 260, "breadth_hold": 100, "breadth_ratio": -0.55,
               "regime_label": "risk_off", "source": "scanner"}
    index = {"index_kospi": 2200.0, "index_kospi_chg_pct": -2.0,
             "index_kosdaq": 750.0, "index_kosdaq_chg_pct": -1.5}
    flow = {"foreign_net_amount": -400.0, "institution_net_amount": -200.0}
    out = compute_market_regime(breadth, index, flow, "2026-07-16", threshold=0.1)
    assert out["market_sentiment_label"] == "bearish"
    assert out["sentiment_score"] < -0.1


def test_fallback_breadth_only_when_index_and_flow_none():
    breadth = {"id": "z", "trade_date": "2026-07-16", "breadth_buy": 100,
               "breadth_sell": 100, "breadth_hold": 100, "breadth_ratio": 0.0,
               "regime_label": "neutral", "source": "scanner"}
    out = compute_market_regime(breadth, None, None, "2026-07-16", threshold=0.1)
    assert out["market_sentiment_label"] == "neutral"
    assert out["index_kospi"] is None
    assert out["foreign_net_amount"] is None
    assert out["regime_label"] == "neutral"


def test_none_when_all_inputs_none():
    assert compute_market_regime(None, None, None, "2026-07-16", threshold=0.1) is None


def test_no_breadth_still_gets_trade_date_from_arg():
    """FIX 1: breadth=None 스켈레톤도 trade_date 인자를 정확히 반영해야 함
    (index/flow dict는 trade_date 키를 갖지 않으므로 반드시 인자로 threading)."""
    index = {"index_kospi": 2500.0, "index_kospi_chg_pct": 1.5,
             "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 1.0}
    flow = {"foreign_net_amount": 500.0, "institution_net_amount": 300.0}
    out = compute_market_regime(None, index, flow, "2026-07-16", 0.1)
    assert out["trade_date"] == "2026-07-16"
    assert out["index_kospi"] == 2500.0
    assert out["foreign_net_amount"] == 500.0


def test_index_only_no_flow_still_scores():
    breadth = {"id": "a", "trade_date": "2026-07-16", "breadth_buy": 200,
               "breadth_sell": 100, "breadth_hold": 50, "breadth_ratio": 0.29,
               "regime_label": "risk_on", "source": "scanner"}
    index = {"index_kospi": 2500.0, "index_kospi_chg_pct": 2.0,
             "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 2.0}
    out = compute_market_regime(breadth, index, None, "2026-07-16", threshold=0.1)
    assert out["market_sentiment_label"] == "bullish"
    assert out["foreign_net_amount"] is None


import pytest
from services.storage_service import StorageService


@pytest.mark.asyncio
async def test_save_and_get_enriched_regime_roundtrip(tmp_path):
    st = StorageService(db_path=str(tmp_path / "s.db"))
    await st.initialize()
    rec = {
        "id": "rid1", "trade_date": "2026-07-16", "breadth_buy": 300,
        "breadth_sell": 50, "breadth_hold": 100, "breadth_ratio": 0.55,
        "regime_label": "risk_on", "source": "scanner",
        "index_kospi": 2500.0, "index_kospi_chg_pct": 1.5,
        "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 1.0,
        "foreign_net_amount": 500.0, "institution_net_amount": 300.0,
        "market_sentiment_label": "bullish", "sentiment_score": 0.6,
    }
    assert await st.save_regime_snapshot(rec) is True
    rows = await st.get_regime_snapshots(limit=5)
    assert rows and rows[0]["market_sentiment_label"] == "bullish"
    assert rows[0]["index_kospi"] == 2500.0
    assert rows[0]["foreign_net_amount"] == 500.0
