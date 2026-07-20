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


def test_no_breadth_scan_coverage_pct_is_none():
    """SC-3: breadth 세션이 없는 날(스캐너 미완료 등)의 스켈레톤은
    scan_coverage_pct=None이어야 한다 -- 표본 자체가 없으므로 0이나 다른
    숫자로 오인되면 안 된다."""
    index = {"index_kospi": 2500.0, "index_kospi_chg_pct": 1.5,
             "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 1.0}
    out = compute_market_regime(None, index, None, "2026-07-16", 0.1)
    assert out["scan_coverage_pct"] is None


def test_breadth_scan_coverage_pct_is_preserved_through_enrich():
    """SC-3: breadth가 있으면 그 scan_coverage_pct(SC-1의 partial 세션
    등에서 유래)는 compute_market_regime을 거쳐도 그대로 보존돼야 한다
    (다른 breadth 필드들과 동일한 dict(breadth) 보존 규칙)."""
    breadth = {"id": "x", "trade_date": "2026-07-16", "breadth_buy": 300,
               "breadth_sell": 50, "breadth_hold": 100, "breadth_ratio": 0.55,
               "regime_label": "risk_on", "source": "scanner",
               "scan_coverage_pct": 84.0}
    out = compute_market_regime(breadth, None, None, "2026-07-16", threshold=0.1)
    assert out["scan_coverage_pct"] == 84.0


def test_index_only_no_flow_still_scores():
    breadth = {"id": "a", "trade_date": "2026-07-16", "breadth_buy": 200,
               "breadth_sell": 100, "breadth_hold": 50, "breadth_ratio": 0.29,
               "regime_label": "risk_on", "source": "scanner"}
    index = {"index_kospi": 2500.0, "index_kospi_chg_pct": 2.0,
             "index_kosdaq": 850.0, "index_kosdaq_chg_pct": 2.0}
    out = compute_market_regime(breadth, index, None, "2026-07-16", threshold=0.1)
    assert out["market_sentiment_label"] == "bullish"
    assert out["foreign_net_amount"] is None


# --- L-5: regime_label breadth-부재 폴백 융합 -------------------------------


def test_no_breadth_crash_day_falls_back_to_risk_off():
    """L-5 core contract: breadth 부재(스캐너 미완료)라도 지수 -6%/심리 -1.0인
    폭락일은 regime_label='risk_off'여야 한다. 폴백 이전에는 breadth None 분기가
    'neutral'을 하드코딩해 이 실측 버그(spec §1)를 재현했다."""
    index = {"index_kospi": 2350.0, "index_kospi_chg_pct": -6.0,
              "index_kosdaq": 780.0, "index_kosdaq_chg_pct": -6.0}
    out = compute_market_regime(None, index, None, "2026-07-16", threshold=0.1)
    assert out["sentiment_score"] == -1.0
    assert out["market_sentiment_label"] == "bearish"
    assert out["regime_label"] == "risk_off"


def test_no_breadth_no_signals_at_all_stays_neutral():
    """breadth 부재 + 지수·수급 신호 전부 없음(필드 전부 None) -> 폴백을 태우지
    않고 기존 'neutral' 스켈레톤 값을 그대로 유지해야 한다(threshold=0인 극단
    케이스에서 score>=0이 'risk_on'으로 오분류되는 것을 막는 안전장치)."""
    index = {"index_kospi": None, "index_kospi_chg_pct": None,
              "index_kosdaq": None, "index_kosdaq_chg_pct": None}
    flow = {"foreign_net_amount": None, "institution_net_amount": None}
    out = compute_market_regime(None, index, flow, "2026-07-16", threshold=0.1)
    assert out["sentiment_score"] == 0.0
    assert out["market_sentiment_label"] == "neutral"
    assert out["regime_label"] == "neutral"


def test_breadth_present_regime_label_byte_invariant_even_when_sentiment_disagrees():
    """breadth 존재 시 regime_label은 sentiment_score와 무관하게 breadth 자체
    값을 그대로 보존해야 한다(byte-불변 회귀) — 폴백 분기가 breadth-존재 경로를
    절대 건드리지 않는다는 것을 sentiment가 정반대로 나오는 케이스로 못박는다."""
    breadth = {"id": "b1", "trade_date": "2026-07-16", "breadth_buy": 300,
               "breadth_sell": 50, "breadth_hold": 100, "breadth_ratio": 0.55,
               "regime_label": "risk_on", "source": "scanner"}
    index = {"index_kospi": 2350.0, "index_kospi_chg_pct": -6.0,
              "index_kosdaq": 780.0, "index_kosdaq_chg_pct": -6.0}
    flow = {"foreign_net_amount": -400.0, "institution_net_amount": -200.0}
    out = compute_market_regime(breadth, index, flow, "2026-07-16", threshold=0.1)
    # sentiment_score는 지수/수급이 강한 음수라 음전(=bearish)으로 나오지만
    # regime_label은 breadth 필드('risk_on')를 그대로 보존해야 한다.
    assert out["sentiment_score"] < -0.1
    assert out["market_sentiment_label"] == "bearish"
    assert out["regime_label"] == "risk_on"
    assert out["id"] == "b1"


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
