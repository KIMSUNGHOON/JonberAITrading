"""
SQLite Storage Service for Session Persistence

Provides:
- Session state storage
- LangGraph checkpointing
- Cache management

No external server required - uses embedded SQLite database.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "storage.db"


class StorageService:
    """
    SQLite-based storage service for session and state management.

    Provides high-level methods for:
    - Session storage
    - State checkpointing
    - Cache operations

    No external server required!
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self):
        """Initialize database tables."""
        if self._initialized:
            return

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                # Sessions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                """)

                # Checkpoints table (for LangGraph)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(session_id, thread_id)
                    )
                """)

                # Cache table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                """)

                # Coin trades table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS coin_trades (
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
                """)

                # Coin positions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS coin_positions (
                        market TEXT PRIMARY KEY,
                        currency TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        avg_entry_price REAL NOT NULL,
                        stop_loss REAL,
                        take_profit REAL,
                        session_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Coin realized P&L table (P2-4 Task P0: coin had no
                # realized-P&L record at all — paper_performance is KR-only.
                # Minimal shape: one row per close/reduce, mirroring
                # coin_trades' style rather than trying to reuse it (a trade
                # row is a single execution; a realized row is a matched
                # entry/exit pair with the resulting P&L).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS coin_realized_pnl (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        market TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        exit_price REAL NOT NULL,
                        quantity REAL NOT NULL,
                        realized_amount REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # KR stock trades table (P1-1: the /trades tab had no backing
                # storage — nothing recorded a fill anywhere, and the route
                # masked the missing methods as an empty list via
                # `except AttributeError`). Mirrors coin_trades' shape,
                # adapted to KRStockTradeRecord's field names.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS kr_stock_trades (
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
                """)

                # App settings table (generic key-value; e.g. trading_mode:kiwoom)
                # — runtime settings that must survive restarts (R3).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Agent-chat decisions ledger (Phase1 C1: decisions/votes were
                # in-memory-only and evaporated on restart). One row per
                # decision reached by the agent-chat debate for a ticker;
                # regime_snapshot_id/outcome_* are placeholders for later
                # tasks (provenance/EOD outcome labeling) and stay unused here.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_chat_decisions (
                        id TEXT PRIMARY KEY,
                        ticker TEXT NOT NULL,
                        stock_name TEXT,
                        trade_date TEXT,
                        status TEXT,
                        action TEXT,
                        confidence REAL,
                        consensus_level REAL,
                        rationale TEXT,
                        dissenting_opinions TEXT,
                        entry_price REAL,
                        stop_loss REAL,
                        take_profit REAL,
                        position_pct REAL,
                        news_sentiment TEXT,
                        news_count INTEGER,
                        behavioral_signals TEXT,
                        market_sentiment TEXT,
                        flow TEXT,
                        regime_snapshot_id TEXT,
                        outcome_realized_pnl REAL,
                        outcome_label TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Per-agent votes backing a decision (technical/risk/sentiment/...).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_chat_votes (
                        id TEXT PRIMARY KEY,
                        decision_id TEXT NOT NULL,
                        agent_type TEXT NOT NULL,
                        vote TEXT,
                        confidence REAL,
                        reasoning TEXT,
                        key_factors TEXT,
                        suggested_position_pct REAL,
                        suggested_stop_loss_pct REAL,
                        suggested_take_profit_pct REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Trade <-> decision provenance (Phase1 C2): kr_stock_trades
                # and coin_trades predate decision_id/strategy_id/
                # entry_or_exit -- there is no migration mechanism in this
                # project, so an already-deployed DB only ever gets these
                # columns via this ALTER path on the next initialize().
                await self._ensure_columns(
                    conn,
                    "kr_stock_trades",
                    {
                        "decision_id": "TEXT",
                        "strategy_id": "TEXT",
                        "entry_or_exit": "TEXT",
                    },
                )
                await self._ensure_columns(
                    conn,
                    "coin_trades",
                    {
                        "decision_id": "TEXT",
                        "strategy_id": "TEXT",
                        "entry_or_exit": "TEXT",
                    },
                )

                # Create indexes for better query performance
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints(thread_id)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at DESC)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_market ON coin_trades(market)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_session ON coin_trades(session_id)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_created ON coin_trades(created_at DESC)"
                )
                # Composite index for market + time sorting (frequently used together)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_market_created ON coin_trades(market, created_at DESC)"
                )
                # Index for state filtering
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_state ON coin_trades(state)"
                )
                # Index for side filtering (buy/sell statistics)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_trades_side ON coin_trades(side)"
                )

                # KR stock trades indexes (mirrors coin_trades' set above)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kr_stock_trades_stk_cd ON kr_stock_trades(stk_cd)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kr_stock_trades_created ON kr_stock_trades(created_at DESC)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kr_stock_trades_stk_cd_created ON kr_stock_trades(stk_cd, created_at DESC)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kr_stock_trades_session ON kr_stock_trades(session_id)"
                )

                # Additional indexes for common query patterns
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_positions_quantity ON coin_positions(quantity)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_positions_updated ON coin_positions(updated_at DESC)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_positions_session ON coin_positions(session_id)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_realized_pnl_market ON coin_realized_pnl(market)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_coin_realized_pnl_created ON coin_realized_pnl(created_at DESC)"
                )

                # Agent-chat ledger indexes (Phase1 C1)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_acd_ticker ON agent_chat_decisions(ticker)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_acd_trade_date ON agent_chat_decisions(trade_date)"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_acv_decision ON agent_chat_votes(decision_id)"
                )

                await conn.commit()
                self._initialized = True
                logger.info("storage_initialized", db_path=str(self.db_path))
        except Exception as e:
            logger.error("storage_init_failed", error=str(e))
            raise

    @staticmethod
    async def _ensure_columns(
        conn: "aiosqlite.Connection", table: str, cols: dict[str, str]
    ) -> None:
        """Add any of `cols` missing from `table` via ALTER TABLE ADD COLUMN.

        This project has no migration mechanism -- CREATE TABLE IF NOT EXISTS
        is a no-op against a table that already exists, so a column added to
        the schema after a DB file was first created would otherwise never
        appear on that file. Every column added this way must be nullable
        (no DEFAULT/NOT NULL requirement), since SQLite's ADD COLUMN cannot
        backfill existing rows with anything but a constant.
        """
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, col_type in cols.items():
            if name not in existing:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                )

    # -------------------------------------------
    # Session Management
    # -------------------------------------------

    async def save_session(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl: Optional[timedelta] = None,
    ) -> bool:
        """
        Save session data.

        Args:
            session_id: Unique session identifier
            data: Session data dictionary
            ttl: Time to live (default: 24 hours)

        Returns:
            True if saved successfully
        """
        await self.initialize()
        ttl = ttl or timedelta(hours=24)
        expires_at = datetime.now() + ttl

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions (session_id, data, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, json.dumps(data, default=str), expires_at),
                )
                await conn.commit()
                logger.debug("session_saved", session_id=session_id)
                return True
        except Exception as e:
            logger.error("session_save_failed", session_id=session_id, error=str(e))
            return False

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve session data.

        Args:
            session_id: Unique session identifier

        Returns:
            Session data dictionary or None if not found/expired
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT data FROM sessions
                    WHERE session_id = ? AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (session_id, datetime.now()),
                )
                row = await cursor.fetchone()
                if row:
                    return json.loads(row["data"])
                return None
        except Exception as e:
            logger.error("session_get_failed", session_id=session_id, error=str(e))
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?", (session_id,)
                )
                await conn.commit()
                logger.debug("session_deleted", session_id=session_id)
                return True
        except Exception as e:
            logger.error("session_delete_failed", session_id=session_id, error=str(e))
            return False

    async def list_sessions(self, pattern: str = "*") -> list[str]:
        """
        List all session IDs.

        Args:
            pattern: Glob pattern for matching (uses SQL LIKE)

        Returns:
            List of session IDs
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                # Convert glob pattern to SQL LIKE pattern
                sql_pattern = pattern.replace("*", "%").replace("?", "_")
                cursor = await conn.execute(
                    """
                    SELECT session_id FROM sessions
                    WHERE session_id LIKE ? AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (sql_pattern, datetime.now()),
                )
                rows = await cursor.fetchall()
                return [row["session_id"] for row in rows]
        except Exception as e:
            logger.error("session_list_failed", error=str(e))
            return []

    # -------------------------------------------
    # State Checkpointing (for LangGraph)
    # -------------------------------------------

    async def save_checkpoint(
        self,
        session_id: str,
        thread_id: str,
        checkpoint_data: dict[str, Any],
    ) -> bool:
        """
        Save LangGraph checkpoint for a session.

        Args:
            session_id: Session identifier
            thread_id: LangGraph thread ID
            checkpoint_data: Checkpoint state data

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoints (session_id, thread_id, data)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, thread_id, json.dumps(checkpoint_data, default=str)),
                )
                await conn.commit()
                logger.debug(
                    "checkpoint_saved",
                    session_id=session_id,
                    thread_id=thread_id,
                )
                return True
        except Exception as e:
            logger.error(
                "checkpoint_save_failed",
                session_id=session_id,
                thread_id=thread_id,
                error=str(e),
            )
            return False

    async def get_checkpoint(
        self,
        session_id: str,
        thread_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve LangGraph checkpoint.

        Args:
            session_id: Session identifier
            thread_id: LangGraph thread ID

        Returns:
            Checkpoint data or None
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT data FROM checkpoints WHERE session_id = ? AND thread_id = ?",
                    (session_id, thread_id),
                )
                row = await cursor.fetchone()
                if row:
                    return json.loads(row["data"])
                return None
        except Exception as e:
            logger.error(
                "checkpoint_get_failed",
                session_id=session_id,
                thread_id=thread_id,
                error=str(e),
            )
            return None

    async def list_checkpoints(self, session_id: str) -> list[str]:
        """List all checkpoints for a session."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT thread_id FROM checkpoints WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                return [row["thread_id"] for row in rows]
        except Exception as e:
            logger.error("checkpoint_list_failed", session_id=session_id, error=str(e))
            return []

    async def delete_checkpoints(self, session_id: str) -> bool:
        """Delete all checkpoints for a session."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "DELETE FROM checkpoints WHERE session_id = ?", (session_id,)
                )
                await conn.commit()
                return True
        except Exception as e:
            logger.error("checkpoint_delete_failed", session_id=session_id, error=str(e))
            return False

    # -------------------------------------------
    # Cache Operations
    # -------------------------------------------

    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl: Optional[timedelta] = None,
    ) -> bool:
        """
        Set a cache value.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live (default: 30 minutes)
        """
        await self.initialize()
        ttl = ttl or timedelta(minutes=30)
        expires_at = datetime.now() + ttl

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO cache (key, value, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, json.dumps(value, default=str), expires_at),
                )
                await conn.commit()
                return True
        except Exception as e:
            logger.error("cache_set_failed", key=key, error=str(e))
            return False

    async def cache_get(self, key: str) -> Optional[Any]:
        """Get a cached value."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT value FROM cache
                    WHERE key = ? AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (key, datetime.now()),
                )
                row = await cursor.fetchone()
                if row:
                    return json.loads(row["value"])
                return None
        except Exception as e:
            logger.error("cache_get_failed", key=key, error=str(e))
            return None

    async def cache_delete(self, key: str) -> bool:
        """Delete a cached value."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                await conn.commit()
                return True
        except Exception as e:
            logger.error("cache_delete_failed", key=key, error=str(e))
            return False

    async def cleanup_expired(self) -> int:
        """
        Remove expired sessions and cache entries.

        Returns:
            Number of records deleted
        """
        await self.initialize()
        deleted = 0

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                # Clean expired sessions
                cursor = await conn.execute(
                    "DELETE FROM sessions WHERE expires_at < ?", (datetime.now(),)
                )
                deleted += cursor.rowcount

                # Clean expired cache
                cursor = await conn.execute(
                    "DELETE FROM cache WHERE expires_at < ?", (datetime.now(),)
                )
                deleted += cursor.rowcount

                await conn.commit()
                logger.info("cleanup_completed", deleted_count=deleted)
                return deleted
        except Exception as e:
            logger.error("cleanup_failed", error=str(e))
            return 0

    # -------------------------------------------
    # Coin Trading Operations
    # -------------------------------------------

    async def save_coin_trade(self, trade: dict[str, Any]) -> bool:
        """
        Save a coin trade record.

        Args:
            trade: Trade data dictionary with keys:
                - id, session_id, market, side, order_type, price,
                - volume, executed_volume, fee, total_krw, state, order_uuid

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO coin_trades
                    (id, session_id, market, side, order_type, price, volume,
                     executed_volume, fee, total_krw, state, order_uuid, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade["id"],
                        trade.get("session_id"),
                        trade["market"],
                        trade["side"],
                        trade["order_type"],
                        trade["price"],
                        trade["volume"],
                        trade["executed_volume"],
                        trade.get("fee", 0),
                        trade["total_krw"],
                        trade["state"],
                        trade.get("order_uuid"),
                        trade.get("created_at", datetime.now()),
                    ),
                )
                await conn.commit()
                logger.debug("coin_trade_saved", trade_id=trade["id"])
                return True
        except Exception as e:
            logger.error("coin_trade_save_failed", trade_id=trade.get("id"), error=str(e))
            return False

    async def get_coin_trades(
        self,
        market: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get coin trade history.

        Args:
            market: Filter by market code (optional)
            limit: Maximum records to return
            offset: Offset for pagination

        Returns:
            List of trade records
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if market:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM coin_trades
                        WHERE market = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (market.upper(), limit, offset),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM coin_trades
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("coin_trades_get_failed", error=str(e))
            return []

    async def get_coin_trade(self, trade_id: str) -> Optional[dict[str, Any]]:
        """Get a single trade by ID."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT * FROM coin_trades WHERE id = ?",
                    (trade_id,),
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("coin_trade_get_failed", trade_id=trade_id, error=str(e))
            return None

    async def get_coin_trades_count(self, market: Optional[str] = None) -> int:
        """Get total count of trades for pagination."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                if market:
                    cursor = await conn.execute(
                        "SELECT COUNT(*) FROM coin_trades WHERE market = ?",
                        (market.upper(),),
                    )
                else:
                    cursor = await conn.execute("SELECT COUNT(*) FROM coin_trades")
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("coin_trades_count_failed", error=str(e))
            return 0

    async def save_coin_position(self, position: dict[str, Any]) -> bool:
        """
        Save or update a coin position, weighted-averaging repeat buys.

        `position["quantity"]`/`["avg_entry_price"]` are treated as the
        INCREMENTAL buy being added, not the total position — every caller
        (paper + live BUY execution) passes this trade's own qty/price. If a
        position already exists for the market, the stored quantity/avg
        entry price are combined with the incoming values via a
        quantity-weighted average; otherwise this is just the first buy.

        (P2-4 Task P0 fix: this used to be `INSERT OR REPLACE`, so a second
        BUY of the same market overwrote avg_entry_price/quantity with only
        the last buy's values instead of averaging — repeated buys silently
        discarded all prior cost basis.)

        Args:
            position: Position data with keys:
                - market, currency, quantity, avg_entry_price,
                - stop_loss, take_profit, session_id

        Returns:
            True if saved successfully
        """
        await self.initialize()

        market = position["market"].upper()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT quantity, avg_entry_price FROM coin_positions WHERE market = ?",
                    (market,),
                )
                existing = await cursor.fetchone()

                incoming_quantity = float(position["quantity"])
                incoming_price = float(position["avg_entry_price"])

                final_quantity = incoming_quantity
                final_avg_entry_price = incoming_price

                if existing and float(existing["quantity"]) > 0:
                    old_quantity = float(existing["quantity"])
                    old_avg_entry_price = float(existing["avg_entry_price"])
                    combined_quantity = old_quantity + incoming_quantity

                    if combined_quantity > 0:
                        final_avg_entry_price = (
                            old_quantity * old_avg_entry_price
                            + incoming_quantity * incoming_price
                        ) / combined_quantity
                    final_quantity = combined_quantity

                await conn.execute(
                    """
                    INSERT OR REPLACE INTO coin_positions
                    (market, currency, quantity, avg_entry_price, stop_loss,
                     take_profit, session_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?,
                            COALESCE((SELECT created_at FROM coin_positions WHERE market = ?), ?),
                            ?)
                    """,
                    (
                        market,
                        position["currency"],
                        final_quantity,
                        final_avg_entry_price,
                        position.get("stop_loss"),
                        position.get("take_profit"),
                        position.get("session_id"),
                        market,
                        datetime.now(),
                        datetime.now(),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "coin_position_saved",
                    market=market,
                    quantity=final_quantity,
                    avg_entry_price=final_avg_entry_price,
                )
                return True
        except Exception as e:
            logger.error(
                "coin_position_save_failed",
                market=position.get("market"),
                error=str(e),
            )
            return False

    async def get_coin_positions(self) -> list[dict[str, Any]]:
        """Get all open coin positions."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM coin_positions
                    WHERE quantity > 0
                    ORDER BY updated_at DESC
                    """
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("coin_positions_get_failed", error=str(e))
            return []

    async def get_coin_position(self, market: str) -> Optional[dict[str, Any]]:
        """Get a single position by market."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT * FROM coin_positions WHERE market = ?",
                    (market.upper(),),
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("coin_position_get_failed", market=market, error=str(e))
            return None

    async def update_coin_position(
        self, market: str, updates: dict[str, Any]
    ) -> bool:
        """
        Update specific fields of a position.

        Args:
            market: Market code
            updates: Dict of fields to update

        Returns:
            True if updated successfully
        """
        await self.initialize()

        allowed_fields = {"quantity", "avg_entry_price", "stop_loss", "take_profit"}
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

        if not update_fields:
            return False

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                set_clause = ", ".join(f"{k} = ?" for k in update_fields)
                values = list(update_fields.values()) + [datetime.now(), market.upper()]

                await conn.execute(
                    f"""
                    UPDATE coin_positions
                    SET {set_clause}, updated_at = ?
                    WHERE market = ?
                    """,
                    values,
                )
                await conn.commit()
                logger.debug("coin_position_updated", market=market)
                return True
        except Exception as e:
            logger.error("coin_position_update_failed", market=market, error=str(e))
            return False

    async def delete_coin_position(self, market: str) -> bool:
        """Delete a position (when closed)."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "DELETE FROM coin_positions WHERE market = ?",
                    (market.upper(),),
                )
                await conn.commit()
                logger.debug("coin_position_deleted", market=market)
                return True
        except Exception as e:
            logger.error("coin_position_delete_failed", market=market, error=str(e))
            return False

    async def save_coin_realized_pnl(self, record: dict[str, Any]) -> bool:
        """
        Persist a minimal realized-P&L record for a coin close/reduce.

        (P2-4 Task P0: coin had no realized-P&L aggregation at all — every
        SELL's outcome simply vanished. Kept intentionally minimal — entry/
        exit/qty/realized only, no fees yet (that's a later fill-realism
        task). Full performance-panel integration is out of scope here.)

        Args:
            record: dict with keys id, market, entry_price, exit_price,
                quantity, realized_amount, and optionally session_id/created_at.

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO coin_realized_pnl
                    (id, session_id, market, entry_price, exit_price,
                     quantity, realized_amount, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record.get("session_id"),
                        record["market"].upper(),
                        record["entry_price"],
                        record["exit_price"],
                        record["quantity"],
                        record["realized_amount"],
                        record.get("created_at", datetime.now()),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "coin_realized_pnl_saved",
                    market=record["market"],
                    realized_amount=record["realized_amount"],
                )
                return True
        except Exception as e:
            logger.error(
                "coin_realized_pnl_save_failed",
                market=record.get("market"),
                error=str(e),
            )
            return False

    async def get_coin_realized_pnl(
        self,
        market: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get realized coin P&L records, newest first, optionally filtered by market."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if market:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM coin_realized_pnl
                        WHERE market = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (market.upper(), limit, offset),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM coin_realized_pnl
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("coin_realized_pnl_get_failed", error=str(e))
            return []

    # -------------------------------------------
    # KR Stock Trading Operations (P1-1)
    # -------------------------------------------

    async def add_kr_stock_trade(self, record: dict[str, Any]) -> bool:
        """
        Save a KR stock trade record (a confirmed fill).

        Args:
            record: Trade data dictionary with keys:
                - id, session_id, stk_cd, stk_nm, side, order_type, price,
                - quantity, executed_quantity, fee, total_krw, status, order_id

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO kr_stock_trades
                    (id, session_id, stk_cd, stk_nm, side, order_type, price,
                     quantity, executed_quantity, fee, total_krw, status, order_id, created_at,
                     decision_id, strategy_id, entry_or_exit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record.get("session_id"),
                        record["stk_cd"],
                        record.get("stk_nm"),
                        record["side"],
                        record["order_type"],
                        record["price"],
                        record["quantity"],
                        record["executed_quantity"],
                        record.get("fee", 0),
                        record["total_krw"],
                        record["status"],
                        record.get("order_id"),
                        record.get("created_at", datetime.now()),
                        record.get("decision_id"),
                        record.get("strategy_id"),
                        record.get("entry_or_exit"),
                    ),
                )
                await conn.commit()
                logger.debug("kr_stock_trade_saved", trade_id=record["id"])
                return True
        except Exception as e:
            logger.error(
                "kr_stock_trade_save_failed", trade_id=record.get("id"), error=str(e)
            )
            return False

    async def get_kr_stock_trades(
        self,
        stk_cd: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get KR stock trade history, newest first.

        Args:
            stk_cd: Filter by stock code (optional)
            limit: Maximum records to return
            offset: Offset for pagination

        Returns:
            List of trade records
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if stk_cd:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM kr_stock_trades
                        WHERE stk_cd = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (stk_cd, limit, offset),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM kr_stock_trades
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("kr_stock_trades_get_failed", error=str(e))
            return []

    async def get_kr_stock_trade(self, trade_id: str) -> Optional[dict[str, Any]]:
        """Get a single KR stock trade by ID."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT * FROM kr_stock_trades WHERE id = ?",
                    (trade_id,),
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error("kr_stock_trade_get_failed", trade_id=trade_id, error=str(e))
            return None

    async def get_kr_stock_trades_count(self, stk_cd: Optional[str] = None) -> int:
        """Get total count of KR stock trades for pagination."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                if stk_cd:
                    cursor = await conn.execute(
                        "SELECT COUNT(*) FROM kr_stock_trades WHERE stk_cd = ?",
                        (stk_cd,),
                    )
                else:
                    cursor = await conn.execute("SELECT COUNT(*) FROM kr_stock_trades")
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("kr_stock_trades_count_failed", error=str(e))
            return 0

    # -------------------------------------------
    # App Settings (persisted key-value)
    # -------------------------------------------

    async def get_app_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a persisted app setting (e.g. 'trading_mode:kiwoom')."""
        await self.initialize()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            async with conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default

    async def set_app_setting(self, key: str, value: str) -> None:
        """Set (upsert) a persisted app setting."""
        await self.initialize()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
            await conn.commit()
        logger.debug("app_setting_saved", key=key)

    # -------------------------------------------
    # Agent-Chat Decisions Ledger (Phase1 C1)
    # -------------------------------------------

    async def save_agent_chat_decision(
        self, decision: dict[str, Any], votes: list[dict[str, Any]]
    ) -> bool:
        """
        Persist an agent-chat decision plus its backing per-agent votes.

        (Phase1 C1: decisions/votes were in-memory-only and evaporated on
        restart. Mirrors add_kr_stock_trade's shape — a single connection/
        transaction covers the decision row and all vote rows so a decision
        never persists without its votes or vice versa.)

        Args:
            decision: dict with keys id, ticker, stock_name, trade_date,
                status, action, confidence, consensus_level, rationale,
                dissenting_opinions (list), entry_price, stop_loss,
                take_profit, position_pct, news_sentiment, news_count,
                behavioral_signals (dict), market_sentiment (dict/None),
                flow (dict/None).
            votes: list of dicts with keys decision_id, agent_type, vote,
                confidence, reasoning, key_factors (list),
                suggested_position_pct, suggested_stop_loss_pct,
                suggested_take_profit_pct.

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_chat_decisions
                    (id, ticker, stock_name, trade_date, status, action,
                     confidence, consensus_level, rationale, dissenting_opinions,
                     entry_price, stop_loss, take_profit, position_pct,
                     news_sentiment, news_count, behavioral_signals,
                     market_sentiment, flow)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision["id"],
                        decision["ticker"],
                        decision.get("stock_name"),
                        decision.get("trade_date"),
                        decision.get("status"),
                        decision.get("action"),
                        decision.get("confidence"),
                        decision.get("consensus_level"),
                        decision.get("rationale"),
                        json.dumps(decision["dissenting_opinions"])
                        if decision.get("dissenting_opinions") is not None
                        else None,
                        decision.get("entry_price"),
                        decision.get("stop_loss"),
                        decision.get("take_profit"),
                        decision.get("position_pct"),
                        decision.get("news_sentiment"),
                        decision.get("news_count"),
                        json.dumps(decision["behavioral_signals"])
                        if decision.get("behavioral_signals") is not None
                        else None,
                        json.dumps(decision["market_sentiment"])
                        if decision.get("market_sentiment") is not None
                        else None,
                        json.dumps(decision["flow"])
                        if decision.get("flow") is not None
                        else None,
                    ),
                )

                for v in votes:
                    await conn.execute(
                        """
                        INSERT INTO agent_chat_votes
                        (id, decision_id, agent_type, vote, confidence, reasoning,
                         key_factors, suggested_position_pct,
                         suggested_stop_loss_pct, suggested_take_profit_pct)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            v["decision_id"],
                            v["agent_type"],
                            v.get("vote"),
                            v.get("confidence"),
                            v.get("reasoning"),
                            json.dumps(v["key_factors"])
                            if v.get("key_factors") is not None
                            else None,
                            v.get("suggested_position_pct"),
                            v.get("suggested_stop_loss_pct"),
                            v.get("suggested_take_profit_pct"),
                        ),
                    )

                await conn.commit()
                logger.debug(
                    "agent_chat_decision_saved",
                    decision_id=decision.get("id"),
                    ticker=decision.get("ticker"),
                    vote_count=len(votes),
                )
                return True
        except Exception as e:
            logger.error(
                "agent_chat_decision_save_failed",
                decision_id=decision.get("id"),
                error=str(e),
            )
            return False

    async def get_agent_chat_decisions(
        self,
        ticker: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get agent-chat decisions, newest first, optionally filtered by ticker."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if ticker:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM agent_chat_decisions
                        WHERE ticker = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (ticker, limit, offset),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM agent_chat_decisions
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("agent_chat_decisions_get_failed", error=str(e))
            return []

    async def get_agent_chat_votes(self, decision_id: str) -> list[dict[str, Any]]:
        """Get all per-agent votes backing a decision."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM agent_chat_votes
                    WHERE decision_id = ?
                    ORDER BY created_at ASC
                    """,
                    (decision_id,),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(
                "agent_chat_votes_get_failed", decision_id=decision_id, error=str(e)
            )
            return []

    # -------------------------------------------
    # Health Check
    # -------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """
        Check storage health.

        Returns:
            Health status dictionary
        """
        try:
            await self.initialize()

            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                # Get database stats
                cursor = await conn.execute(
                    "SELECT COUNT(*) as count FROM sessions"
                )
                row = await cursor.fetchone()
                session_count = row["count"] if row else 0

                cursor = await conn.execute(
                    "SELECT COUNT(*) as count FROM checkpoints"
                )
                row = await cursor.fetchone()
                checkpoint_count = row["count"] if row else 0

            # Get file size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            db_size_mb = round(db_size / (1024 * 1024), 2)

            return {
                "status": "healthy",
                "type": "sqlite",
                "db_path": str(self.db_path),
                "size_mb": db_size_mb,
                "sessions": session_count,
                "checkpoints": checkpoint_count,
            }
        except Exception as e:
            logger.error("storage_health_check_failed", error=str(e))
            return {
                "status": "unhealthy",
                "type": "sqlite",
                "error": str(e),
            }


# -------------------------------------------
# Service Singleton
# -------------------------------------------

_storage_service: Optional[StorageService] = None


async def get_storage_service() -> StorageService:
    """Get or create StorageService singleton."""
    global _storage_service

    if _storage_service is None:
        _storage_service = StorageService()
        await _storage_service.initialize()

    return _storage_service


async def close_storage_service():
    """Close storage service connections."""
    global _storage_service
    if _storage_service is not None:
        # SQLite connections are closed automatically via context manager
        # Just reset the singleton
        _storage_service = None
        logger.info("storage_service_closed")


async def reset_storage_service():
    """Reset storage service (for testing)."""
    await close_storage_service()
