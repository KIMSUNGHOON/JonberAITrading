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
