"""GET /api/trading/operations aggregate endpoint tests."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes import trading as trading_mod
from services.session_manager import AnalysisSession, MarketType, SessionStatus
from services.trading.models import ManagedPosition, QueuedTrade, WatchedStock
from services.kiwoom.models import FilledOrder, Holding, PendingOrder


def _session(sid, status, state=None, stk_cd="005930", stk_nm="삼성전자"):
    return AnalysisSession(
        session_id=sid, market_type=MarketType.KIWOOM, ticker=stk_cd,
        display_name=stk_nm, status=status, state=state or {},
        stk_cd=stk_cd, stk_nm=stk_nm,
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

    async def _get_all(market_type=None, status=None):
        return {
            s.session_id: s for s in sessions
            if (market_type is None or s.market_type == market_type)
            and (status is None or s.status == status)
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
    assert h.pnl == 60000.0 and h.pnl_pct == 2.31
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


async def test_operations_coin_market_returns_sessions_only():
    """coin: 세션만 채우고 KR 전용 섹션은 null + errors 없음(비해당)."""
    coin_sess = AnalysisSession(session_id="c1", market_type=MarketType.COIN,
                                ticker="KRW-BTC", display_name="비트코인",
                                status=SessionStatus.RUNNING, state={})
    with patch.object(trading_mod, "get_session_manager",
                      AsyncMock(return_value=_sm([coin_sess]))):
        res = await trading_mod.get_operations(
            market="coin", coordinator=_coordinator())

    assert res.analyzing[0].session_id == "c1"
    assert res.watching is None and res.pending_buy.queue is None
    assert res.pending_buy.open_orders is None and res.holding is None
    assert res.errors == {}
