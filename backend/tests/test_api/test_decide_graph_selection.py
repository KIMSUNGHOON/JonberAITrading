"""/decide graph selection & market discrimination must come from the SM
record's market_type, never legacy-dict (B) membership.

CRITICAL (spec adversarial review, P2-2): the pre-fix code selected the
resume graph via a membership check against the legacy KR session dict
(`if session_id in <legacy KR dict>: kr_graph else: coin_graph`). That
membership check was only satisfied because
_adopt_session_from_manager (the restart fallback) happened to register the
adopted session into the matching legacy dict as a side effect, BEFORE the
graph-selection line ran.

P2-5 (session-SSOT) removed _adopt_session_from_manager and every legacy
dict lookup from submit_decision entirely (the legacy dicts themselves were
fully retired in P3-1): the session, its state, its market_type and its
final status now all come from a single sm.get_session() call, held as
`sm_session` for the whole function. This file pins that reality directly.
"""

import pytest

from services.session_manager import AnalysisSession, MarketType, SessionStatus
import app.api.routes.approval as approval_module


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

    async def update_state(self, session_id: str, updates: dict, last_node=None):
        if self._session is None or self._session.session_id != session_id:
            raise KeyError(session_id)
        self._session.state.update(updates)
        if last_node:
            self._session.last_node = last_node


@pytest.fixture
def wired(monkeypatch):
    """No-op notification/commit/mirror side channels + settable SM session."""

    async def noop(*a, **k):
        return None

    for name in (
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

    holder: dict = {"manager": _FakeSessionManager(None)}

    async def fake_get_session_manager():
        return holder["manager"]

    monkeypatch.setattr(approval_module, "get_session_manager", fake_get_session_manager)

    def set_sm_session(sm_session):
        holder["manager"] = _FakeSessionManager(sm_session)

    def set_kr_graph(factory):
        monkeypatch.setattr(approval_module, "get_kr_stock_trading_graph", factory)

    return {
        "set_sm_session": set_sm_session,
        "set_kr_graph": set_kr_graph,
    }


@pytest.mark.asyncio
async def test_kr_session_decide_resumes_kr_graph(wired):
    """CRITICAL pin: a KIWOOM SM session -> /decide must select the KR graph
    (the only graph left — the coin stack was removed 2026-08-01)."""
    session_id = "b-empty-kr-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.KIWOOM))

    picked = {}

    def fake_kr_graph():
        picked["graph"] = "kr"
        raise _StopResume()

    wired["set_kr_graph"](fake_kr_graph)

    with pytest.raises(_StopResume):
        await approval_module.submit_decision(session_id, "approved")

    assert picked.get("graph") == "kr"


@pytest.mark.asyncio
async def test_coin_session_rejected_with_410_at_graph_selection(wired):
    """코인 스택 제거(2026-08-01) 이후 회귀 핀: 이 테스트는 원래 COIN SM
    세션이 coin 그래프를 고른다는 대칭성을 검증했다 — coin 그래프가 삭제된
    지금은 그 대신, 남아 있는 비-KIWOOM 체크포인트(MarketType.COIN은 아직
    열거형에 남아 있다 — Task 3이 정리)가 KR 그래프로 조용히 흘러들지 않고
    명시적으로 410 거부되는지 핀한다."""
    from fastapi import HTTPException

    session_id = "b-empty-coin-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.COIN))

    def boom():
        raise AssertionError("kr graph factory must not be called for a non-KIWOOM session")

    wired["set_kr_graph"](boom)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_unknown_market_type_fails_closed_400_at_graph_selection(wired):
    """A market_type outside {KIWOOM, COIN} reaching the graph-selection site
    must 400 fail-closed -- never silently default to either graph.
    """
    from fastapi import HTTPException

    session_id = "b-empty-stock-1"
    wired["set_sm_session"](_sm_session(session_id, market_type=MarketType.STOCK))

    def boom():
        raise AssertionError("graph factory must not be called for an unknown market")

    wired["set_kr_graph"](boom)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 400
    assert "unknown session market" in exc_info.value.detail
