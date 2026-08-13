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
    market_type: "MarketType | str" = MarketType.KIWOOM,
    status: SessionStatus = SessionStatus.AWAITING_APPROVAL,
) -> AnalysisSession:
    if market_type == MarketType.KIWOOM:
        kwargs = {
            "ticker": "005930",
            "display_name": "삼성전자",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
        }
    else:
        # 코인 스택 제거(2026-08-01) 이후 KIWOOM 외 값은 전부 레거시/미지원
        # 취급이다 -- market_type을 굳이 MarketType 인스턴스로 강제하지 않는다
        # (services/session_manager.py._row_to_session의 열거형 파싱 실패
        # 폴백이 원본 문자열을 그대로 남기는 것과 같은 모양).
        kwargs = {"ticker": "KRW-BTC", "display_name": "비트코인"}
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
    세션이 coin 그래프를 고른다는 대칭성을 검증했다 — coin 그래프도, COIN
    열거형 멤버도 삭제된 지금은 그 대신, 남아 있는 비-KIWOOM 체크포인트
    (동결 이전의 레거시 coin 세션 — market_type이 문자열 "coin"으로 남아
    있을 수 있다)가 KR 그래프로 조용히 흘러들지 않고 명시적으로 410
    거부되는지 핀한다."""
    from fastapi import HTTPException

    session_id = "b-empty-coin-1"
    wired["set_sm_session"](_sm_session(session_id, market_type="coin"))

    def boom():
        raise AssertionError("kr graph factory must not be called for a non-KIWOOM session")

    wired["set_kr_graph"](boom)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 410
    assert "coin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_unrecognized_market_type_fails_closed_410_at_graph_selection(wired):
    """Task 3(코인 스택 제거) 이후 MarketType은 KIWOOM 하나뿐이다 -- 예전엔
    "인식되지만 아직 거절"(coin, 410)과 "아예 모르는 값"(stock, 400) 두
    단으로 나뉘어 있었으나 그 구분이 사라졌다: KIWOOM이 아닌 값은 무엇이든
    (여기서는 한 번도 유효했던 적 없는 값도 포함) 그래프 선택 이전에
    동일하게 410 fail-closed 되어야 한다 -- 절대 어느 쪽 그래프로도 조용히
    넘어가지 않는다.
    """
    from fastapi import HTTPException

    session_id = "b-empty-stock-1"
    wired["set_sm_session"](_sm_session(session_id, market_type="stock"))

    def boom():
        raise AssertionError("graph factory must not be called for an unknown market")

    wired["set_kr_graph"](boom)

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.submit_decision(session_id, "approved")

    assert exc_info.value.status_code == 410
    assert "stock" in exc_info.value.detail
