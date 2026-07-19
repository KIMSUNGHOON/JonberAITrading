"""P1-1 wiring: kr_stock_execution_node records the confirmed fill for
/trades via services.trading.trade_log.record_trade_fill.

Uses the REAL trade_log module backed by an isolated temp-SQLite storage
(not mocked) to prove the end-to-end write — unlike
test_kr_execution_fill_confirm.py / test_hitl_execution_routing.py, which
neutralize trade_log entirely (via an autouse fixture) to keep their own,
unrelated assertions free of real storage I/O.

Fixture pattern follows test_kr_execution_fill_confirm.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.storage_service as ss
from agents.graph.kr_stock_nodes.execution import kr_stock_execution_node
from services.kiwoom.models import FilledOrder, OrderResponse
from services.trading import trade_log

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


async def _no_sleep(_seconds):
    return None


class _FakeKiwoomClient:
    def __init__(self, filled_orders, ord_no="ORD1"):
        self._filled_orders = filled_orders
        self._ord_no = ord_no

    async def place_buy_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="정상")

    async def place_sell_order(self, stk_cd, qty, price=None, order_type=None):
        return OrderResponse(ord_no=self._ord_no, return_code=0, return_msg="정상")

    async def get_filled_orders(
        self, sell_tp="0", stex_tp="0", stk_cd=None, use_cache=True
    ):
        return list(self._filled_orders)


def _filled(ord_no, qty, price, buy_sell_tp="매수"):
    return FilledOrder(
        ord_no=ord_no,
        stk_cd="005930",
        stk_nm="삼성전자",
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


def _state(action="BUY", quantity=10, entry_price=70000, existing_position=None):
    return {
        "approval_status": "approved",
        "trade_proposal": {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "action": action,
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": 66500,
            "take_profit": 77000,
            "risk_score": 0.6,
        },
        "existing_position": existing_position,
        "reasoning_log": [],
        "session_id": "sess-graph-1",
    }


def _mock_coordinator():
    coordinator = MagicMock()
    coordinator.fill_tracker = MagicMock()
    coordinator._schedule_persist = MagicMock()
    coordinator.risk_params = MagicMock()
    return coordinator


async def test_buy_full_fill_records_trade(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([_filled("ORD1", 10, 70000)])
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ), patch(
        "services.trading.position_registration.register_fill_as_position",
        new_callable=AsyncMock,
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["stk_cd"] == "005930"
    assert row["stk_nm"] == "삼성전자"
    assert row["side"] == "buy"
    assert row["order_type"] == "limit"
    assert row["price"] == 70000
    assert row["quantity"] == 10
    assert row["executed_quantity"] == 10
    assert row["status"] == "completed"
    assert row["order_id"] == "ORD1"
    assert row["session_id"] == "sess-graph-1"


async def test_sell_partial_fill_records_partial_trade(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(
        [_filled("ORD2", 12, 71000, buy_sell_tp="매도")], ord_no="ORD2"
    )
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(
            _state(
                action="REDUCE",
                quantity=30,
                entry_price=71000,
                existing_position=existing,
            )
        )

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == "sell"
    assert row["price"] == 71000
    assert row["quantity"] == 30
    assert row["executed_quantity"] == 12
    assert row["status"] == "partial"
    assert row["order_id"] == "ORD2"


async def test_zero_fill_records_nothing(monkeypatch, temp_storage):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([])
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "placed_pending_fill"
    await trade_log.wait_for_pending_trade_fill_writes()

    assert await temp_storage.get_kr_stock_trades() == []


# -------------------------------------------
# L2 (decision lineage restoration): the graph execution node persists a
# durable decision-ledger row (L1's persist_analysis_decision) just before
# order placement and threads its id into BOTH record_trade_fill's
# decision_id/entry_or_exit AND register_fill_as_position's session_id
# (-> ManagedPosition.analysis_session_id). Previously record_trade_fill was
# called here with neither decision_id nor entry_or_exit at all (a bare
# keyword-omission bug — both columns landed NULL for every graph-approved
# trade), and register_fill_as_position received state["session_id"] (the
# SessionManager id, a dangling pointer once that session is GC'd) instead
# of a durable id.
# -------------------------------------------


async def test_buy_records_decision_id_and_entry_or_exit(monkeypatch, temp_storage):
    """Step 1 test 1 (BUY leg): a successful BUY fill's kr_stock_trades row
    carries a freshly-issued decision_id (a uuid, not the SessionManager
    session_id) and entry_or_exit='entry'."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([_filled("ORD1", 10, 70000)])
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ), patch(
        "services.trading.position_registration.register_fill_as_position",
        new_callable=AsyncMock,
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    row = rows[0]
    assert row["entry_or_exit"] == "entry"
    assert row["decision_id"] is not None
    assert row["decision_id"] != "sess-graph-1"  # NOT the SessionManager session id

    import uuid

    uuid.UUID(row["decision_id"])  # a real uuid4, not a placeholder string

    decisions = await temp_storage.get_agent_chat_decisions(limit=10)
    matching = [d for d in decisions if d["id"] == row["decision_id"]]
    assert len(matching) == 1
    assert matching[0]["decision_source"] == "analysis"
    assert matching[0]["session_ref"] == "sess-graph-1"


async def test_sell_records_decision_id_and_entry_or_exit(monkeypatch, temp_storage):
    """Step 1 test 1 (SELL leg): entry_or_exit='exit' for a SELL/REDUCE
    fill, mirroring the BUY leg's 'entry'."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(
        [_filled("ORD2", 12, 71000, buy_sell_tp="매도")], ord_no="ORD2"
    )
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(
            _state(
                action="REDUCE",
                quantity=30,
                entry_price=71000,
                existing_position=existing,
            )
        )

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["entry_or_exit"] == "exit"
    assert rows[0]["decision_id"] is not None


async def test_decision_ledger_persist_failure_does_not_block_order_or_fill_recording(
    monkeypatch, temp_storage
):
    """Step 1 test 2: persist_analysis_decision raising must never block
    order placement or fill recording (spec D5, best-effort) — the trade
    still records, just with decision_id=NULL (today's status quo, not a
    regression)."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([_filled("ORD1", 10, 70000)])
    coordinator = _mock_coordinator()

    async def _boom(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ), patch(
        "services.trading.position_registration.register_fill_as_position",
        new_callable=AsyncMock,
    ), patch(
        "services.trading.decision_ledger.persist_analysis_decision",
        AsyncMock(side_effect=_boom),
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    rows = await temp_storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["decision_id"] is None
    assert rows[0]["entry_or_exit"] == "entry"


async def test_buy_decision_id_survives_into_position_and_subsequent_close(
    monkeypatch, temp_storage
):
    """Step 1 test 5 (chain): the decision_id persisted for a graph BUY is
    threaded into ManagedPosition.analysis_session_id (NOT
    state["session_id"], the SessionManager id) via register_fill_as_
    position's session_id kwarg, using a REAL ExecutionCoordinator so the
    position is actually recorded. That same id then survives as
    kr_realized_pnl.entry_decision_id when the SAME coordinator later closes
    the position — proving the durable id, not the ephemeral session id,
    is what lineage consumers (calibration, EOD review) will see."""
    from services.trading.coordinator import ExecutionCoordinator
    from services.trading.models import OrderResult, OrderSide

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([_filled("ORD1", 10, 70000)])
    coordinator = ExecutionCoordinator(kiwoom_client=None)
    coordinator._persistence_active = True

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "completed"
    await trade_log.wait_for_pending_trade_fill_writes()

    positions = coordinator._state.positions
    assert len(positions) == 1
    decision_id = positions[0].analysis_session_id
    assert decision_id is not None
    assert decision_id != "sess-graph-1"  # spec-change pin: NOT the session id

    async def _exec_close(order):
        return OrderResult(
            order_id="CLOSE1",
            ticker=order.ticker,
            side=OrderSide.SELL,
            requested_quantity=order.quantity,
            filled_quantity=order.quantity,
            avg_price=71000,
            status="filled",
        )

    coordinator._execute_order = _exec_close
    await coordinator._close_position("005930")
    await trade_log.wait_for_pending_trade_fill_writes()

    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930")
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["entry_decision_id"] == decision_id



# -------------------------------------------
# I2 (final-review fix, spec D2 parity): the graph node's OWN
# fill-tracker registrations for an unfilled BUY remainder (execution.py
# ~522) and a SELL/REDUCE remainder (execution.py ~567) must carry the SAME
# durable decision_id as `register_fill_as_position`'s session_id kwarg
# above (L2, line ~501) -- both previously read state.get("session_id")
# (the ephemeral SessionManager id) instead. Uses `_mock_coordinator()`
# (fill_tracker is a bare MagicMock) rather than the real
# ExecutionCoordinator above, since these assert on the TrackedOrder object
# passed to `fill_tracker.register(...)` directly.
# -------------------------------------------


async def test_buy_decision_id_survives_into_tracked_order_remainder(
    monkeypatch, temp_storage
):
    """A zero-fill BUY's unfilled remainder is tracked via
    `coordinator.fill_tracker.register(TrackedOrder(...))` -- its
    `source_session_id` must be the durable decision_id persist_analysis_
    decision (backed by REAL tmp storage here, so a genuine fresh uuid4 is
    returned), NOT state["session_id"] ("sess-graph-1")."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient([])  # zero fill -> remaining_qty > 0 branch
    coordinator = _mock_coordinator()

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ), patch(
        "services.trading.position_registration.register_fill_as_position",
        new_callable=AsyncMock,
    ):
        result = await kr_stock_execution_node(_state())

    assert result["execution_status"] == "placed_pending_fill"
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert tracked.side == "buy"
    assert tracked.source_session_id is not None
    assert tracked.source_session_id != "sess-graph-1"

    import uuid

    uuid.UUID(tracked.source_session_id)  # a real uuid4, not a placeholder


async def test_sell_decision_id_survives_into_tracked_order_remainder(
    monkeypatch, temp_storage
):
    """The SELL/REDUCE-side sibling of the BUY test above (execution.py's
    OTHER fill-tracker registration site, ~567) -- a partial REDUCE's
    unfilled remainder must carry the durable decision_id too. This is the
    id the post-fill poll path (`_poll_tracked_fills` ->
    `_apply_sell_position_delta` -> `record_kr_realized_pnl(exit_decision_
    id=...)`) later reads as the EXIT decision's lineage anchor."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeKiwoomClient(
        [_filled("ORD2", 12, 71000, buy_sell_tp="매도")], ord_no="ORD2"
    )
    coordinator = _mock_coordinator()
    existing = {
        "quantity": 100,
        "entry_price": 65000,
        "stop_loss": 60000,
        "take_profit": 75000,
    }

    with patch(
        "agents.graph.kr_stock_nodes.execution.get_shared_kiwoom_client_async",
        AsyncMock(return_value=client),
    ), patch(
        "app.dependencies.get_trading_coordinator",
        AsyncMock(return_value=coordinator),
    ):
        result = await kr_stock_execution_node(
            _state(
                action="REDUCE",
                quantity=30,
                entry_price=71000,
                existing_position=existing,
            )
        )

    assert result["execution_status"] == "completed"
    coordinator.fill_tracker.register.assert_called_once()
    tracked = coordinator.fill_tracker.register.call_args.args[0]
    assert tracked.side == "sell"
    assert tracked.source_session_id is not None
    assert tracked.source_session_id != "sess-graph-1"

    import uuid

    uuid.UUID(tracked.source_session_id)
