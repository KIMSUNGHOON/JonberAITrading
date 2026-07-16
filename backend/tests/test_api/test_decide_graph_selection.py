"""/decide graph selection & market discrimination must come from the SM
record's market_type, never legacy-dict (B) membership.

CRITICAL (spec adversarial review, P2-2): the pre-fix code selected the
resume graph via `if session_id in kr_stock_sessions: kr_graph else:
coin_graph` (and re-derived `market` the same way at the reject/re-analysis
site). That membership check is only satisfied TODAY because
_adopt_session_from_manager (the restart fallback) happens to register the
adopted session into the matching legacy dict as a side effect, BEFORE the
graph-selection line runs -- but the graph-selection code has no business
depending on that incidental side channel. Once P2-5 removes B writes from
_adopt_session_from_manager entirely (per the session-SSOT roadmap), or in
the narrow post-restart window before adoption runs, B stays empty straight
through to graph selection and EVERY KR session would silently resume
through the COIN graph (or vice versa).

To pin the fix independent of whatever adoption strategy happens to be wired
today, these tests monkeypatch `_adopt_session_from_manager` itself to
simulate the post-P2-5 shape: it "adopts" the session from the SM record
(state carried over, decision can proceed) but never registers it into the
legacy dict. B is empty when the caller looks it up AND stays empty all the
way through graph selection -- exactly like B writes had been removed
entirely. Graph selection must still resolve the correct market by reading
sm_session.market_type directly (a fresh, independent get_session_manager()
lookup), not by asking whether the legacy dict happens to contain the id.
"""

import pytest

import app.api.routes.approval as approval_module
from services.session_manager import AnalysisSession, MarketType, SessionStatus


class _StopResume(Exception):
    """Raised by the fake graph factories to halt execution right after graph
    selection, before any real resume machinery (aupdate_state/astream) runs.
    """


def _sm_session(
    session_id: str,
    *,
    market_type: MarketType = MarketType.KIWOOM,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
) -> AnalysisSession:
    if market_type == MarketType.KIWOOM:
        kwargs = {
            "ticker": "005930",
            "display_name": "삼성전자",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
        }
    elif market_type == MarketType.COIN:
        kwargs = {
            "ticker": "KRW-BTC",
            "display_name": "비트코인",
            "market": "KRW-BTC",
            "korean_name": "비트코인",
        }
    else:
        kwargs = {"ticker": "AAPL", "display_name": "Apple Inc"}
    state = {
        "awaiting_approval": True,
        "approval_status": None,
        "trade_proposal": {
            "id": "prop-graph-select-1",
            "action": "BUY",
            "quantity": 1,
            "entry_price": 70000,
        },
        "reasoning_log": [],
    }
    return AnalysisSession(
        session_id=session_id,
        market_type=market_type,
        status=status,
        state=state,
        **kwargs,
    )


class _FakeSessionManager:
    def __init__(self, session: AnalysisSession | None):
        self._session = session

    async def get_session(self, session_id: str):
        if self._session is not None and self._session.session_id == session_id:
            return self._session
        return None


@pytest.fixture
def wired(monkeypatch):
    """Empty legacy dicts + no-op notification/mirror/commit side channels.

    Mirrors the mocking approach in tests/test_api/test_approval_restart_resume.py.
    """
    coin_sessions: dict = {}
    kr_stock_sessions: dict = {}
    monkeypatch.setattr(approval_module, "get_coin_sessions", lambda: coin_sessions)
    monkeypatch.setattr(approval_module, "get_kr_stock_sessions", lambda: kr_stock_sessions)

    async def noop(*a, **k):
        return None

    for name in (
        "mirror_session_state",
        "mirror_session_status",
        "commit_session_state",
        "commit_session_status",
        "broadcast_trade_rejected",
        "broadcast_trade_executed",
        "broadcast_trade_queued",
        "broadcast_watch_added",
        "maybe_schedule_auto_approve",
    ):
        monkeypatch.setattr(approval_module, name, noop)

    def set_sm_session(sm_session):
        fake_manager = _FakeSessionManager(sm_session)

        async def fake_get_session_manager():
            return fake_manager

        monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_kr_graph(factory):
        monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", factory)

    def set_coin_graph(factory):
        monkeypatch.setattr(approval_module, "get_coin_trading_graph", factory)

    def simulate_b_empty_adoption():
        """Replace _adopt_session_from_manager with a fake that reads the SM
        row (same as the real one) but never registers into the legacy dict
        -- B stays empty through graph selection, mirroring the post-P2-5
        shape (or the narrow pre-adoption restart window) regardless of
        whatever the real adoption function does today.
        """

        async def fake_adopt(session_id, coin_sess, kr_sess):
            manager = await approval_module.get_session_manager()
            sm_session = await manager.get_session(session_id)
            if sm_session is None:
                return None
            return sm_session.to_legacy_dict()

        monkeypatch.setattr(approval_module, "_adopt_session_from_manager", fake_adopt)

    return {
        "coin_sessions": coin_sessions,
        "kr_stock_sessions": kr_stock_sessions,
        "set_sm_session": set_sm_session,
        "set_kr_graph": set_kr_graph,
        "set_coin_graph": set_coin_graph,
        "simulate_b_empty_adoption": simulate_b_empty_adoption,
    }


@pytest.mark.asyncio
async def test_kr_session_decide_resumes_kr_graph_even_with_b_empty(wired):
    """CRITICAL pin: B dict empty end-to-end (post-P2-5 shape) + a KIWOOM SM
    session -> /decide must select the KR graph, never the COIN graph.
    """
    session_id = "b-empty-kr-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.KIWOOM))
    wired["simulate_b_empty_adoption"]()

    picked = {}

    def fake_kr_graph():
        picked["graph"] = "kr"
        raise _StopResume()

    def fake_coin_graph():
        picked["graph"] = "coin"
        raise _StopResume()

    wired["set_kr_graph"](fake_kr_graph)
    wired["set_coin_graph"](fake_coin_graph)

    with pytest.raises(_StopResume):
        await approval_module.submit_decision(session_id, "approved")

    assert picked.get("graph") == "kr"
    # B genuinely stayed empty the whole time -- the fix must not depend on
    # adoption's (here absent) side effect of registering into the legacy dict.
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_coin_session_decide_resumes_coin_graph_even_with_b_empty(wired):
    """Symmetric case: a COIN SM session with B empty -> COIN graph selected."""
    session_id = "b-empty-coin-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.COIN))
    wired["simulate_b_empty_adoption"]()

    picked = {}

    def fake_kr_graph():
        picked["graph"] = "kr"
        raise _StopResume()

    def fake_coin_graph():
        picked["graph"] = "coin"
        raise _StopResume()

    wired["set_kr_graph"](fake_kr_graph)
    wired["set_coin_graph"](fake_coin_graph)

    with pytest.raises(_StopResume):
        await approval_module.submit_decision(session_id, "approved")

    assert picked.get("graph") == "coin"
    assert session_id not in wired["kr_stock_sessions"]
    assert session_id not in wired["coin_sessions"]


@pytest.mark.asyncio
async def test_unknown_market_type_fails_closed_400_at_graph_selection(wired):
    """A market_type outside {KIWOOM, COIN} reaching the graph-selection site
    must 400 fail-closed -- never silently default to either graph.
    """
    from fastapi import HTTPException

    session_id = "b-empty-stock-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.STOCK))
    wired["simulate_b_empty_adoption"]()

    def boom():
        raise AssertionError("graph factory must not be called for an unknown market")

    wired["set_kr_graph"](boom)
    wired["set_coin_graph"](boom)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "unknown session market" in exc_info.value.detail
