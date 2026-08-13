"""GET /api/trading/operations aggregate endpoint tests."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes import trading as trading_mod
from services.session_manager import AnalysisSession, MarketType, SessionStatus
from services.trading.models import ManagedPosition, QueuedTrade, WatchedStock
from services.trading.fill_costs import effective_pnl, effective_pnl_pct
from services.kiwoom.models import FilledOrder, Holding, PendingOrder


def _session(sid, status, state=None, stk_cd="005930", stk_nm="삼성전자", kind="analysis"):
    return AnalysisSession(
        session_id=sid, market_type=MarketType.KIWOOM, ticker=stk_cd,
        display_name=stk_nm, status=status, state=state or {},
        stk_cd=stk_cd, stk_nm=stk_nm, kind=kind,
    )


def _coordinator(watch=None, queue=None, positions=None):
    coord = MagicMock()
    coord.get_watch_list.return_value = watch or []
    coord.get_trade_queue.return_value = queue or []
    coord.state.positions = positions or []
    return coord


def _kiwoom(pending=None, filled=None, holdings=None):
    client = MagicMock()
    client.get_pending_orders = AsyncMock(return_value=pending or [])
    client.get_filled_orders = AsyncMock(return_value=filled or [])
    balance = MagicMock()
    balance.holdings = holdings or []
    client.get_account_balance = AsyncMock(return_value=balance)
    return client


def _sm(sessions):
    sm = MagicMock()

    async def _get_all(market_type=None, status=None, kind=None):
        return {
            s.session_id: s for s in sessions
            if (market_type is None or s.market_type == market_type)
            and (status is None or s.status == status)
            and (kind is None or s.kind == kind)
        }

    sm.get_all_sessions = AsyncMock(side_effect=_get_all)
    return sm


async def test_operations_aggregates_all_sections():
    running = _session("s-run", SessionStatus.RUNNING,
                       state={"current_stage": "technical_analysis"})
    awaiting = _session("s-await", SessionStatus.AWAITING_APPROVAL, state={
        "trade_proposal": {"id": "p1", "action": "WATCH", "entry_price": 268000,
                           "stop_loss": 246560, "take_profit": 289440,
                           "risk_score": 0.7, "rationale": "관망"},
        "auto_approve_at": "2026-07-13T03:00:00+00:00",
    })
    watch = WatchedStock(session_id="s1", ticker="005930", stock_name="삼성전자",
                         current_price=266000.0)
    queued = QueuedTrade(session_id="s2", ticker="000660", stock_name="SK하이닉스",
                         action="BUY", entry_price=1908960.0)
    pos = ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10,
                          avg_price=260000.0, stop_loss=246560.0, take_profit=289440.0)
    # NOTE: PendingOrder has no `trde_tp` field (verified against
    # services/kiwoom/models.py) — only `buy_sell_tp`, and `ord_dt` is required.
    pending = PendingOrder(ord_no="0101535", stk_cd="005930", stk_nm="삼성전자",
                           ord_qty=48, ord_uv=260000, rmn_qty=48, ccld_qty=0,
                           ord_dt="20260713", ord_tm="111819", buy_sell_tp="1")
    # buy_sell_tp consumer contract is "1"=매수(buy), "2"=매도(sell) — confirmed via
    # app/api/routes/kr_stocks/orders.py:156 and
    # tests/test_services/test_kiwoom/test_account_contract.py:144,186 (the brief's
    # "2"=매수 assumption was backwards; fixed here and in the mapping).
    fill = FilledOrder(ord_no="0090001", stk_cd="005930", stk_nm="삼성전자",
                       ccld_qty=5, ccld_uv=265000, ccld_amt=1325000,
                       ccld_dt="20260713", ccld_tm="101000", buy_sell_tp="1")
    # Real Holding model (kt00004) — fields are hldg_qty/avg_buy_prc/cur_prc/
    # evlu_pfls_amt/evlu_pfls_rt (services/kiwoom/models.py:196-206), so a wrong
    # field name in the handler mapping fails loudly here instead of degrading
    # to null via the handler's per-section except.
    holding = Holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                      avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                      evlu_pfls_amt=60000, evlu_pfls_rt=2.31)

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([running, awaiting]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=_kiwoom([pending], [fill], [holding]))):
        res = await trading_mod.get_operations(
            market="kiwoom",
            coordinator=_coordinator([watch], [queued], [pos]),
        )

    assert [a.session_id for a in res.analyzing] == ["s-run"]
    assert res.analyzing[0].current_stage == "technical_analysis"
    assert res.awaiting[0].session_id == "s-await"
    assert res.awaiting[0].proposal["action"] == "WATCH"
    assert res.awaiting[0].auto_approve_at == "2026-07-13T03:00:00+00:00"
    assert res.watching[0]["ticker"] == "005930"
    assert res.pending_buy.queue[0]["ticker"] == "000660"
    assert res.pending_buy.open_orders[0].order_id == "0101535"
    assert res.pending_buy.open_orders[0].remaining_quantity == 48
    # holding: 브로커 수량/평단 + 코디네이터 스탑 병합
    h = res.holding[0]
    assert h.quantity == 10 and h.stop_loss == 246560.0 and h.take_profit == 289440.0
    assert h.avg_price == 260000.0 and h.current_price == 266000.0
    # P2-4 Task P1: pnl/pnl_pct are now net of round-trip KR cost (this is
    # the live position tile's real data source — see
    # PositionsPanel.tsx header note), NOT the broker's raw evlu_pfls_amt/
    # evlu_pfls_rt (60000.0 / 2.31) pass-through anymore. Compare against
    # the same helper the route uses rather than hardcoding the
    # commission/tax math here.
    expected_pnl = effective_pnl(260000.0, 266000.0, 10, "BUY")
    expected_pnl_pct = effective_pnl_pct(260000.0, 266000.0, 10, "BUY")
    assert h.pnl == pytest.approx(expected_pnl)
    assert h.pnl_pct == pytest.approx(expected_pnl_pct)
    # Sanity: net must be strictly less than the broker's raw gross figure
    # (60000.0) — cost-aware display must never show MORE than raw.
    assert h.pnl < 60000.0
    assert res.today_fills[0].side == "buy"  # buy_sell_tp "1" == 매수
    assert res.errors == {}


async def test_operations_broker_failure_degrades_honestly():
    """브로커 실패 → open_orders/holding/today_fills=None + errors 사유, 나머지 정상."""
    client = MagicMock()
    client.get_pending_orders = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    client.get_filled_orders = AsyncMock(side_effect=RuntimeError("kiwoom down"))
    client.get_account_balance = AsyncMock(side_effect=RuntimeError("kiwoom down"))

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=client)):
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator())

    assert res.pending_buy.open_orders is None
    assert res.holding is None
    assert res.today_fills is None
    assert "kiwoom down" in res.errors["open_orders"]
    assert "kiwoom down" in res.errors["holding"]
    assert "kiwoom down" in res.errors["today_fills"]
    assert res.watching == [] and res.analyzing == []  # 타 섹션은 정상(빈 값)


def _chat_coordinator(pm=None):
    coord = MagicMock()
    coord.position_manager = pm
    return coord


def _chat_position(stop_loss=None, take_profit=None):
    pos = MagicMock()
    pos.stop_loss = stop_loss
    pos.take_profit = take_profit
    return pos


async def test_operations_holding_stops_from_agent_chat_position_manager():
    """트레이딩 코디네이터에 스탑이 없으면(빈 positions) agent-chat PositionManager에서 병합."""
    holding = Holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                      avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                      evlu_pfls_amt=60000, evlu_pfls_rt=2.31)
    pm = MagicMock()
    pm.get_position.return_value = _chat_position(stop_loss=250000.0, take_profit=280000.0)

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=_kiwoom(holdings=[holding]))), \
         patch.object(trading_mod, "get_chat_coordinator",
                      AsyncMock(return_value=_chat_coordinator(pm))) as mock_get_chat_coord:
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator())  # no trading-coordinator positions

    assert res.holding[0].stop_loss == 250000.0
    assert res.holding[0].take_profit == 280000.0
    pm.get_position.assert_called_once_with("005930")
    mock_get_chat_coord.assert_awaited()
    assert res.errors == {}


async def test_operations_holding_stops_trading_coordinator_wins():
    """양쪽 다 있으면 트레이딩 코디네이터(ManagedPosition) 값이 우선."""
    holding = Holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                      avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                      evlu_pfls_amt=60000, evlu_pfls_rt=2.31)
    pos = ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10,
                          avg_price=260000.0, stop_loss=246560.0, take_profit=289440.0)
    pm = MagicMock()
    pm.get_position.return_value = _chat_position(stop_loss=111111.0, take_profit=222222.0)

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=_kiwoom(holdings=[holding]))), \
         patch.object(trading_mod, "get_chat_coordinator",
                      AsyncMock(return_value=_chat_coordinator(pm))) as mock_get_chat_coord:
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator(positions=[pos]))

    assert res.holding[0].stop_loss == 246560.0
    assert res.holding[0].take_profit == 289440.0
    pm.get_position.assert_not_called()
    mock_get_chat_coord.assert_not_awaited()
    assert res.errors == {}


async def test_operations_holding_stops_per_field_coalescing():
    """양쪽 소스 모두 존재 + 코디네이터 stop_loss=None/take_profit 有 →
    stop_loss는 PM 값, take_profit은 코디네이터 값 (per-FIELD coalescing —
    ManagedPosition 존재 자체가 agent-chat 스탑을 가리면 안 된다)."""
    holding = Holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                      avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                      evlu_pfls_amt=60000, evlu_pfls_rt=2.31)
    pos = ManagedPosition(ticker="005930", stock_name="삼성전자", quantity=10,
                          avg_price=260000.0, stop_loss=None, take_profit=289440.0)
    pm = MagicMock()
    pm.get_position.return_value = _chat_position(stop_loss=250000.0, take_profit=222222.0)

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=_kiwoom(holdings=[holding]))), \
         patch.object(trading_mod, "get_chat_coordinator",
                      AsyncMock(return_value=_chat_coordinator(pm))):
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator(positions=[pos]))

    assert res.holding[0].stop_loss == 250000.0    # PM이 보충 (코디네이터 None)
    assert res.holding[0].take_profit == 289440.0  # 코디네이터 값 우선 (non-None)
    pm.get_position.assert_called_once_with("005930")
    assert res.errors == {}


async def test_operations_holding_survives_agent_chat_coordinator_failure():
    """agent-chat 코디네이터 조회 실패 → holding은 브로커 데이터로 정상 반환, 스탑=None, errors 無."""
    holding = Holding(stk_cd="005930", stk_nm="삼성전자", hldg_qty=10,
                      avg_buy_prc=260000, cur_prc=266000, evlu_amt=2660000,
                      evlu_pfls_amt=60000, evlu_pfls_rt=2.31)

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))), \
         patch.object(trading_mod, "get_shared_kiwoom_client_async",
                      AsyncMock(return_value=_kiwoom(holdings=[holding]))), \
         patch.object(trading_mod, "get_chat_coordinator",
                      AsyncMock(side_effect=RuntimeError("agent-chat down"))):
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator())  # no trading-coordinator positions

    assert res.holding[0].ticker == "005930"
    assert res.holding[0].quantity == 10
    assert res.holding[0].stop_loss is None
    assert res.holding[0].take_profit is None
    assert "holding" not in res.errors


async def test_operations_awaiting_proposal_is_slimmed():
    """awaiting 제안은 슬림 필드만 응답에 실린다 — `analyses`(LLM 원문 배열 포함,
    5초 폴링마다 직렬화되어 응답 크기를 지배하던 원인) 및 그 외 잡키는 제외.
    FE 소비자(kiwoomSessionHandlers.ts rehydrateKiwoomSessions)는 정확히 이
    슬림 필드 집합만 읽으므로 회귀 없음."""
    huge_analyses = [{"agent_type": "technical", "raw_llm_output": "x" * 5000}] * 20
    awaiting = _session("s-await", SessionStatus.AWAITING_APPROVAL, state={
        "trade_proposal": {
            "id": "p1", "stk_cd": "005930", "stk_nm": "삼성전자",
            "action": "BUY", "quantity": 10,
            "entry_price": 268000, "stop_loss": 246560, "take_profit": 289440,
            "risk_score": 0.7, "position_size_pct": 5.0,
            "rationale": "관망", "bull_case": "상승 여력", "bear_case": "하락 위험",
            "created_at": "2026-07-13T02:00:00+00:00",
            "analyses": huge_analyses,
            "some_other_internal_field": "junk",
        },
    })

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([awaiting]))):
        res = await trading_mod.get_operations(
            market="kiwoom", coordinator=_coordinator())

    proposal = res.awaiting[0].proposal
    assert "analyses" not in proposal
    assert "some_other_internal_field" not in proposal
    assert proposal == {
        "id": "p1", "stk_cd": "005930", "stk_nm": "삼성전자",
        "action": "BUY", "quantity": 10,
        "entry_price": 268000, "stop_loss": 246560, "take_profit": 289440,
        "risk_score": 0.7, "position_size_pct": 5.0,
        "rationale": "관망", "bull_case": "상승 여력", "bear_case": "하락 위험",
        "created_at": "2026-07-13T02:00:00+00:00",
    }


async def test_operations_awaiting_approval_actionable_reflects_state_flag():
    """Zombie-resurrection guard: an sm row stuck in AWAITING_APPROVAL whose
    state['awaiting_approval'] was cleared (e.g. a cancel whose mirror later
    failed) must surface as non-actionable so the board can't offer a doomed
    approve/reject on it."""
    actionable = _session("s-actionable", SessionStatus.AWAITING_APPROVAL,
                          state={"awaiting_approval": True})
    zombie = _session("s-zombie", SessionStatus.AWAITING_APPROVAL,
                      state={"awaiting_approval": False})

    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([actionable, zombie]))):
        res = await trading_mod.get_operations(market="kiwoom", coordinator=_coordinator())

    by_id = {a.session_id: a for a in res.awaiting}
    assert by_id["s-actionable"].actionable is True
    assert by_id["s-zombie"].actionable is False


async def test_operations_excludes_non_analysis_kind_sessions():
    """P4-1: a kind='discussion' session sharing the SM store must never
    surface on /operations -- neither as 'analyzing' (RUNNING) nor as
    'awaiting' (AWAITING_APPROVAL). Guards against P4-2's future agent-chat
    discussion sessions polluting the operations board with ghost cards."""
    analysis_running = _session("s-analysis-run", SessionStatus.RUNNING)
    discussion_running = _session(
        "s-discussion-run", SessionStatus.RUNNING, kind="discussion"
    )
    discussion_awaiting = _session(
        "s-discussion-await", SessionStatus.AWAITING_APPROVAL, kind="discussion",
        state={"trade_proposal": {"id": "p1", "action": "BUY"}, "awaiting_approval": True},
    )

    with patch.object(
        trading_mod, "get_session_manager",
        AsyncMock(return_value=_sm([analysis_running, discussion_running, discussion_awaiting])),
    ):
        res = await trading_mod.get_operations(market="kiwoom", coordinator=_coordinator())

    assert [a.session_id for a in res.analyzing] == ["s-analysis-run"]
    assert res.awaiting == []


async def test_operations_non_kiwoom_market_returns_no_sections():
    """코인 스택 제거(2026-08-01) 이후: SessionMarketType에 KIWOOM 외 값이
    없으므로 market="coin" 같은 요청은 세션 조회 자체를 건너뛴다(존재할 수
    없는 market의 세션을 찾으려 들지 않는다) -- 전 섹션 null, errors 없음
    (비해당, 실패 아님). 프리즈 이전 프런트가 아직 보낼 수 있는
    ?market=coin 요청이 여기서 죽지 않는지도 함께 확인한다."""
    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([]))):
        res = await trading_mod.get_operations(
            market="coin", coordinator=_coordinator())

    assert res.analyzing is None and res.awaiting is None
    assert res.watching is None and res.pending_buy.queue is None
    assert res.pending_buy.open_orders is None and res.holding is None
    assert res.errors == {}
