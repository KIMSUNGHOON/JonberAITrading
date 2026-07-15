"""Phase1 C2: trade <-> decision provenance.

Root cause: agent-chat's execution path recorded a SYNTHETIC
`session_id=f"chat_{timestamp}"` on every fill, which can never be joined
back to the agent_chat_decisions row that produced it. This pins two things:

(a) storage — kr_stock_trades gains decision_id/strategy_id/entry_or_exit via
    an ALTER-COLUMN migration helper (no migration mechanism existed before;
    a DB created before this change must still pick the columns up on the
    next `initialize()`), and `add_kr_stock_trade` round-trips them.
(b) threading — ChatCoordinator._execute_trade must pass the REAL
    `session.id` as `on_trade_approved`'s `session_id`, not the old
    `chat_<timestamp>` synthetic value.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

import services.storage_service as ss
from services.agent_chat.coordinator import ChatCoordinator
from services.agent_chat.models import (
    ChatSession,
    DecisionAction,
    MarketContext,
    TradeDecision,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# (a) storage: ALTER-COLUMN migration + round-trip
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def legacy_db_path(tmp_path):
    """A DB file created via a StorageService instance that predates the new
    columns -- simulated here by creating the OLD table shape directly with
    raw SQL (no decision_id/strategy_id/entry_or_exit), then handing back the
    path so a fresh StorageService can `initialize()` against it and exercise
    the ALTER path."""
    import aiosqlite

    db_path = tmp_path / "legacy_storage.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            CREATE TABLE kr_stock_trades (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                stk_cd TEXT NOT NULL,
                stk_nm TEXT,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                executed_quantity INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                total_krw INTEGER NOT NULL,
                status TEXT NOT NULL,
                order_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE coin_trades (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                market TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL NOT NULL,
                volume REAL NOT NULL,
                executed_volume REAL NOT NULL,
                fee REAL DEFAULT 0,
                total_krw REAL NOT NULL,
                state TEXT NOT NULL,
                order_uuid TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.commit()

    return db_path


async def test_initialize_alters_legacy_kr_stock_trades_table(legacy_db_path):
    """A pre-existing kr_stock_trades table (created before this change)
    must gain the new columns the NEXT time initialize() runs -- there is no
    migration mechanism today, so this is the only way an already-deployed
    DB ever gets them."""
    import aiosqlite

    storage = ss.StorageService(db_path=legacy_db_path)
    await storage.initialize()

    async with aiosqlite.connect(str(legacy_db_path)) as conn:
        cursor = await conn.execute("PRAGMA table_info(kr_stock_trades)")
        columns = {row[1] for row in await cursor.fetchall()}

    assert {"decision_id", "strategy_id", "entry_or_exit"} <= columns


async def test_initialize_alters_legacy_coin_trades_table(legacy_db_path):
    import aiosqlite

    storage = ss.StorageService(db_path=legacy_db_path)
    await storage.initialize()

    async with aiosqlite.connect(str(legacy_db_path)) as conn:
        cursor = await conn.execute("PRAGMA table_info(coin_trades)")
        columns = {row[1] for row in await cursor.fetchall()}

    assert {"decision_id", "strategy_id", "entry_or_exit"} <= columns


async def test_initialize_is_idempotent_across_repeated_alters(legacy_db_path):
    """Calling initialize() twice (e.g. two StorageService instances against
    the same file, or a restart) must not raise -- _ensure_columns has to
    check PRAGMA table_info before each ALTER, not assume it only ever runs
    once."""
    storage1 = ss.StorageService(db_path=legacy_db_path)
    await storage1.initialize()

    storage2 = ss.StorageService(db_path=legacy_db_path)
    await storage2.initialize()  # must not raise "duplicate column name"


async def test_add_kr_stock_trade_round_trips_decision_id_and_entry_or_exit(
    legacy_db_path,
):
    storage = ss.StorageService(db_path=legacy_db_path)
    await storage.initialize()

    record = {
        "id": "t-prov-1",
        "session_id": "real-session-id",
        "stk_cd": "005930",
        "stk_nm": "삼성전자",
        "side": "buy",
        "order_type": "limit",
        "price": 70000,
        "quantity": 10,
        "executed_quantity": 10,
        "fee": 0,
        "total_krw": 700000,
        "status": "completed",
        "order_id": "ORD1",
        "decision_id": "real-session-id",
        "entry_or_exit": "entry",
    }
    ok = await storage.add_kr_stock_trade(record)
    assert ok is True

    rows = await storage.get_kr_stock_trades()
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "real-session-id"
    assert rows[0]["entry_or_exit"] == "entry"
    assert rows[0]["strategy_id"] is None  # not provided -- stays NULL


# ---------------------------------------------------------------------------
# (b) threading: ChatCoordinator._execute_trade must pass the REAL session.id
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator():
    return ChatCoordinator()


@pytest.fixture
def chat_session():
    context = MarketContext(
        ticker="005930",
        stock_name="삼성전자",
        current_price=72500,
        price_change_pct=0.5,
    )
    return ChatSession(ticker="005930", stock_name="삼성전자", context=context)


async def test_execute_trade_passes_real_session_id_not_synthetic_chat_id(
    coordinator, chat_session
):
    """Before this fix, _execute_trade hardcoded
    session_id=f"chat_{datetime.now():%Y%m%d_%H%M%S}" -- unjoinable to any
    agent_chat_decisions row. It must now pass session.id (the actual
    ChatSession's id) through to on_trade_approved."""
    import app.dependencies as deps_module

    fake_trading_coord = MagicMock()
    fake_trading_coord.on_trade_approved = AsyncMock(return_value=None)
    fake_trading_coord.mark_watch_converted = MagicMock(return_value=True)
    fake_trading_coord.get_activity_log = MagicMock(return_value=[])

    async def fake_get_trading_coordinator():
        return fake_trading_coord

    decision = TradeDecision(
        action=DecisionAction.BUY,
        confidence=0.9,
        consensus_level=0.9,
        rationale="워치리스트 목표가 도달",
        quantity=10,
        entry_price=72_500,
    )

    from unittest.mock import patch

    with patch.object(
        deps_module, "get_trading_coordinator", fake_get_trading_coordinator
    ):
        await coordinator._execute_trade("005930", decision, chat_session)

    fake_trading_coord.on_trade_approved.assert_awaited_once()
    call_kwargs = fake_trading_coord.on_trade_approved.call_args.kwargs
    assert call_kwargs["session_id"] == chat_session.id
    assert not call_kwargs["session_id"].startswith("chat_")
