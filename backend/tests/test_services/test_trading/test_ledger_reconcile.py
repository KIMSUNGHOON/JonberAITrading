"""E1-5: EOD 원장 대사 백스톱 (`services.trading.ledger_reconcile`).

E1-1~E1-4는 fill_tracker가 **추적 중인** 주문만 커버한다. 이 모듈은 그
바깥의 갭 — 프로세스 사망/미추적으로 원장(kr_stock_trades)에서 영구히
누락된 주문 — 을 마감 시 ka10076 전수 대조로 회수하는 백스톱을 검증한다.

Fixture pattern follows test_trades_recording_wiring.py (real StorageService
against tmp_path, monkeypatched into the `services.storage_service` module
singleton so record_trade_fill_async/record_kr_realized_pnl_async's internal
`get_storage_service()` resolves to the same db).
"""

import inspect
from datetime import date

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.kiwoom.models import FilledOrder
from services.trading.ledger_reconcile import reconcile_trade_ledger
from services.trading.trade_log import record_trade_fill_async

pytestmark = pytest.mark.asyncio

TRADE_DATE = date.today().strftime("%Y-%m-%d")


@pytest_asyncio.fixture
async def temp_storage(tmp_path, monkeypatch):
    storage = ss.StorageService(db_path=tmp_path / "test_storage.db")
    await storage.initialize()
    monkeypatch.setattr(ss, "_storage_service", storage)
    yield storage
    monkeypatch.setattr(ss, "_storage_service", None)


def _filled(ord_no, qty, price, *, stk_cd="005930", stk_nm="삼성전자", buy_sell_tp="2"):
    """buy_sell_tp uses the REAL get_filled_orders() consumer contract:
    "1"=매수(buy), "2"=매도(sell) — see KiwoomClient._normalize_buy_sell."""
    return FilledOrder(
        ord_no=ord_no,
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        ccld_qty=qty,
        ccld_uv=price,
        ccld_amt=qty * price,
        ccld_dt="",
        ccld_tm="",
        buy_sell_tp=buy_sell_tp,
    )


class _FakeKiwoom:
    def __init__(self, fills=None, raise_error=False):
        self._fills = fills or []
        self._raise_error = raise_error
        self.calls = []

    async def get_filled_orders(self, use_cache=True):
        self.calls.append(use_cache)
        if self._raise_error:
            raise RuntimeError("broker unreachable")
        return list(self._fills)


async def _seed_ledger_row(
    *, order_id, quantity, price, side, entry_or_exit, stk_cd="005930", stk_nm="삼성전자"
):
    """Insert a real ledger row via the same write path production code uses,
    so the row shape is guaranteed correct."""
    await record_trade_fill_async(
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        side=side,
        order_type="limit",
        price=price,
        quantity=quantity,
        executed_quantity=quantity,
        status="completed",
        order_id=order_id,
        entry_or_exit=entry_or_exit,
    )


# ---------------------------------------------------------------------------
# ① 원장 부분 vs 브로커 전체 → 부족분 upsert (+ 실현손익, entry 소스가 있을 때)
# ---------------------------------------------------------------------------


async def test_partial_ledger_gap_upserts_missing_delta_with_realized_pnl(temp_storage):
    # 진입가 소스: 이 종목의 이전 entry(매수) 원장 행.
    await _seed_ledger_row(
        order_id="ORD-ENTRY", quantity=144, price=200_000,
        side="buy", entry_or_exit="entry",
    )
    # 원장에는 매도 144주 중 37주만 기록됨 (프로세스 사망으로 잔여 누락).
    await _seed_ledger_row(
        order_id="ORD-A", quantity=37, price=250_000,
        side="sell", entry_or_exit="exit",
    )

    kiwoom = _FakeKiwoom([_filled("ORD-A", 144, 250_000, buy_sell_tp="2")])
    result = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)

    assert result == {"checked": 1, "missing_orders": 1, "upserted_qty": 107}

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930", limit=50)
    ord_a_rows = [r for r in rows if r["order_id"] == "ORD-A"]
    assert sum(r["executed_quantity"] for r in ord_a_rows) == 144
    new_row = next(r for r in ord_a_rows if r["executed_quantity"] == 107)
    assert new_row["side"] == "sell"
    assert new_row["price"] == 250_000
    assert new_row["status"] == "completed"

    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930", limit=50)
    assert len(pnl_rows) == 1
    assert pnl_rows[0]["quantity"] == 107
    assert pnl_rows[0]["entry_price"] == 200_000
    assert pnl_rows[0]["exit_price"] == 250_000
    assert pnl_rows[0]["realized_amount"] == pytest.approx((250_000 - 200_000) * 107)


# ---------------------------------------------------------------------------
# ② 원장 == 브로커 누적 → no-op
# ---------------------------------------------------------------------------


async def test_matching_ledger_is_noop(temp_storage):
    await _seed_ledger_row(
        order_id="ORD-B", quantity=50, price=71_000,
        side="buy", entry_or_exit="entry",
    )

    kiwoom = _FakeKiwoom([_filled("ORD-B", 50, 71_000, buy_sell_tp="1")])
    result = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)

    assert result == {"checked": 1, "missing_orders": 0, "upserted_qty": 0}

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930", limit=50)
    assert len(rows) == 1  # nothing appended


# ---------------------------------------------------------------------------
# ③ 원장에 아예 없는 order_id → 신규 전량 append
# ---------------------------------------------------------------------------


async def test_order_absent_from_ledger_is_appended_in_full(temp_storage):
    kiwoom = _FakeKiwoom([_filled("ORD-C", 30, 68_500, buy_sell_tp="1")])
    result = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)

    assert result == {"checked": 1, "missing_orders": 1, "upserted_qty": 30}

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930", limit=50)
    assert len(rows) == 1
    row = rows[0]
    assert row["order_id"] == "ORD-C"
    assert row["quantity"] == 30
    assert row["executed_quantity"] == 30
    assert row["price"] == 68_500
    assert row["side"] == "buy"
    assert row["entry_or_exit"] == "entry"
    assert row["status"] == "completed"

    # BUY side never triggers realized P&L.
    pnl_rows = await temp_storage.get_kr_realized_pnl(stk_cd="005930", limit=50)
    assert pnl_rows == []


# ---------------------------------------------------------------------------
# ④ 브로커 조회 실패 → never-raise, 전부 0
# ---------------------------------------------------------------------------


async def test_broker_failure_never_raises_and_returns_zero_counts(temp_storage):
    kiwoom = _FakeKiwoom(raise_error=True)
    result = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)

    assert result == {"checked": 0, "missing_orders": 0, "upserted_qty": 0}
    rows = await temp_storage.get_kr_stock_trades(limit=50)
    assert rows == []


# ---------------------------------------------------------------------------
# ⑤ 재실행 idempotent
# ---------------------------------------------------------------------------


async def test_rerun_is_idempotent(temp_storage):
    await _seed_ledger_row(
        order_id="ORD-D", quantity=10, price=100_000,
        side="sell", entry_or_exit="exit",
    )
    kiwoom = _FakeKiwoom([_filled("ORD-D", 60, 100_000, buy_sell_tp="2")])

    first = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)
    assert first == {"checked": 1, "missing_orders": 1, "upserted_qty": 50}

    second = await reconcile_trade_ledger(kiwoom, temp_storage, TRADE_DATE)
    assert second == {"checked": 1, "missing_orders": 0, "upserted_qty": 0}

    rows = await temp_storage.get_kr_stock_trades(stk_cd="005930", limit=50)
    ord_d_rows = [r for r in rows if r["order_id"] == "ORD-D"]
    assert sum(r["executed_quantity"] for r in ord_d_rows) == 60
    assert len(ord_d_rows) == 2  # original 10 + one 50 delta, never re-appended


# ---------------------------------------------------------------------------
# 배선 핀: reconcile_trade_ledger는 마감 엣지에서 run_strategy_consensus
# 직후에 호출된다 (E3-3 통지 스텝이 나중에 이 뒤에 붙을 자리).
# test_strategy_orchestrator.py:261의 inspect.getsource 관례를 그대로 미러.
# ---------------------------------------------------------------------------


def test_coordinator_close_edge_calls_ledger_reconcile_after_strategy_consensus():
    from services.trading.coordinator import ExecutionCoordinator

    source = inspect.getsource(ExecutionCoordinator._check_queue_on_market_open)
    assert "reconcile_trade_ledger(" in source
    assert source.index("run_strategy_consensus(") < source.index("reconcile_trade_ledger(")
