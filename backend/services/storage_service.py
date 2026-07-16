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

                # KR realized P&L table (Phase1 Task 4/C3a: KR had no
                # per-trade realized-P&L record anywhere — only the broker's
                # day-level ka10074, ephemeral and not matched to entry/exit.
                # Mirrors coin_realized_pnl's shape, plus entry/exit decision
                # IDs and holding_period_seconds so a matched close can be
                # attributed back to the agent-chat decision that opened it
                # (see update_decision_outcome below) and to how long the
                # position was held.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS kr_realized_pnl (
                        id TEXT PRIMARY KEY,
                        stk_cd TEXT NOT NULL,
                        entry_price REAL,
                        exit_price REAL,
                        quantity INTEGER,
                        realized_amount REAL,
                        entry_decision_id TEXT,
                        exit_decision_id TEXT,
                        holding_period_seconds INTEGER,
                        entry_at TIMESTAMP,
                        exit_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Daily performance snapshot table (Phase1 Task 5/C3b): equity/
                # realized-P&L/win-rate were only ever recomputed live from
                # ka10074+kt00004, which have a rolling broker query window —
                # a durable end-of-day row per trade_date survives past that
                # window. trade_date is the PK so a snapshot exists at most
                # once per day; the writer uses INSERT OR IGNORE so a second
                # write on the same day is a no-op rather than clobbering the
                # first (see save_daily_perf_snapshot below).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_perf_snapshot (
                        trade_date TEXT PRIMARY KEY,
                        equity REAL,
                        realized_pnl REAL,
                        commission REAL,
                        tax REAL,
                        net_pnl REAL,
                        win_trades INTEGER,
                        loss_trades INTEGER,
                        cumulative_return_pct REAL,
                        regime_snapshot_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Regime snapshot table (Phase2 Task 2): the only durable
                # market-wide artifact is the background scanner's
                # scan_sessions breadth distribution (buy/sell/hold counts
                # across the day's KOSPI/KOSDAQ sweep) — index/flow fetchers
                # are a later phase. One row per compute_regime_snapshot
                # call (services/trading/regime.py); id is NOT the
                # trade_date so re-running the same day intentionally
                # appends rather than overwrites, mirroring
                # agent_calibration's accretion style above.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS regime_snapshot (
                        id TEXT PRIMARY KEY,
                        trade_date TEXT,
                        breadth_buy INTEGER,
                        breadth_sell INTEGER,
                        breadth_hold INTEGER,
                        breadth_ratio REAL,
                        regime_label TEXT,
                        source TEXT DEFAULT 'scanner',
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

                # EOD review report table (Phase2 Task 3): the durable,
                # structured end-of-day review assembled from the Phase1/
                # Phase2 ledgers (daily_perf_snapshot/kr_realized_pnl/
                # agent_calibration/regime_snapshot) — see
                # services/trading/eod_review.py::build_eod_review. Stored as
                # one opaque report_json blob rather than normalized columns
                # since its shape is a nested aggregate, not a flat record.
                # trade_date is the PK so re-running the same day's review
                # (e.g. after a late fill correction) updates the existing
                # row via INSERT OR REPLACE rather than accreting duplicates.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS eod_review (
                        trade_date TEXT PRIMARY KEY,
                        report_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Strategy revision ledger (Phase3: the adaptive
                # TradingStrategy produced by the EOD strategy-consensus
                # panel — and manual /trading/strategy edits — versioned
                # durably; coordinator._strategy alone is in-memory and
                # evaporates on restart). Accrete-style (id PK, one row per
                # consensus run / manual set) like regime_snapshot; the
                # "currently applied" revision is the app_settings
                # 'strategy:active_revision_id' pointer, so restore never
                # guesses. strategy_json is the FULL TradingStrategy dump —
                # the strategy in effect AFTER this run (unchanged runs
                # store the same content with changed=0).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_revisions (
                        id TEXT PRIMARY KEY,
                        trade_date TEXT,
                        source TEXT,
                        stance TEXT,
                        consensus_level REAL,
                        changed INTEGER DEFAULT 0,
                        strategy_json TEXT NOT NULL,
                        parent_revision_id TEXT,
                        rationale TEXT,
                        votes_json TEXT,
                        regime_snapshot_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

                # Discussion transcript ledger (session-ssot P4-3): a completed
                # ChatSession's decision/vote summary lands in
                # agent_chat_decisions/agent_chat_votes above, but the full
                # message/round transcript (context/rounds/all_messages/votes/
                # decision, i.e. ChatSession.model_dump(mode="json")) used to
                # live only in the coordinator's in-memory history and
                # SessionManager's TTL'd state -- evaporating on restart or
                # TTL expiry. One row per session, additive to the existing
                # ledger tables above (no column/semantic changes to either).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_chat_transcripts (
                        session_id TEXT PRIMARY KEY,
                        transcript_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Per-agent calibration ledger (Phase2 Task 1): Phase1 backfills
                # outcome_realized_pnl onto the entry decision but leaves
                # outcome_label nullable and never scores which agent's vote
                # was actually right — without that, adaptive strategy
                # re-weighting (Phase 3) has no data to re-weight against.
                # One row per agent_type per calibration run (as_of_date is
                # NOT a PK/UNIQUE constraint — re-running for the same date
                # simply appends a fresh snapshot row rather than overwriting,
                # mirroring how this ledger accretes elsewhere in this file).
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_calibration (
                        id TEXT PRIMARY KEY,
                        agent_type TEXT,
                        as_of_date TEXT,
                        window_days INTEGER,
                        decisions_scored INTEGER,
                        correct INTEGER,
                        accuracy REAL,
                        avg_confidence REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # agent_chat_decisions.agent_weights (Phase4 T4): persists the
                # consensus weights (default or calibration-tilted) actually
                # used to reach this decision, as a JSON TEXT blob — without
                # this, post-hoc calibration analysis over historical
                # decisions can't tell which weighting produced them.
                await self._ensure_columns(
                    conn,
                    "agent_chat_decisions",
                    {"agent_weights": "TEXT"},
                )

                # agent_chat_decisions.total_messages/total_rounds (session-ssot
                # P4-3): additive count columns so a list view can show
                # transcript size (P4-4) without parsing agent_chat_transcripts'
                # JSON blob per row. serialize_session fills these for new
                # rows; existing rows stay NULL (P4-4 falls back to 0).
                await self._ensure_columns(
                    conn,
                    "agent_chat_decisions",
                    {"total_messages": "INTEGER", "total_rounds": "INTEGER"},
                )

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

                # Regime snapshot index/flow/sentiment 심화 (Phase5): breadth-only
                # 로 만들어진 기존 db에 지수/수급/파생심리 컬럼을 ALTER로 추가.
                await self._ensure_columns(
                    conn,
                    "regime_snapshot",
                    {
                        "index_kospi": "REAL",
                        "index_kospi_chg_pct": "REAL",
                        "index_kosdaq": "REAL",
                        "index_kosdaq_chg_pct": "REAL",
                        "foreign_net_amount": "REAL",
                        "institution_net_amount": "REAL",
                        "market_sentiment_label": "TEXT",
                        "sentiment_score": "REAL",
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
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_kr_realized_pnl_stk_cd ON kr_realized_pnl(stk_cd)"
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

                # Agent calibration ledger index (Phase2 Task 1)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ac_agent_type ON agent_calibration(agent_type)"
                )

                # Regime snapshot index (Phase2 Task 2)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_regime_snapshot_trade_date ON regime_snapshot(trade_date)"
                )

                # Strategy revision index (Phase3)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_strategy_revisions_trade_date"
                    " ON strategy_revisions(trade_date)"
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

    async def get_checkpoint_session_ids(self) -> list[tuple[str, str]]:
        """
        List every distinct session_id that currently owns checkpoint rows,
        paired with the most recent write time across all of that
        session_id's (session_id, thread_id) rows.

        Session-SSOT P5-2: backs the orphan-checkpoint sweep in
        session_manager.py. That sweep needs a "how long has this
        checkpoint gone untouched" signal to apply a grace period before
        reclaiming a checkpoint whose owning session is missing or
        terminal -- rather than adding a schema column for this, it reuses
        `checkpoints.created_at`, which already behaves as a de facto
        last-write timestamp with ZERO migration: `save_checkpoint` above
        uses `INSERT OR REPLACE`, and SQLite's REPLACE conflict-resolution
        algorithm deletes the pre-existing (session_id, thread_id) row and
        inserts a brand new one on every write. `created_at` is not one of
        the columns that INSERT's column list specifies, so the new row
        always takes the column's DEFAULT (CURRENT_TIMESTAMP) -- on every
        save, not just the first. (Verified empirically, not just inferred
        from the CREATE TABLE text -- see the P5-2 task report.)

        Returns:
            List of (session_id, last_written_at) tuples. last_written_at
            is the raw SQLite TIMESTAMP string (e.g. "2026-07-17
            09:00:00"), parseable via datetime.fromisoformat. Empty list on
            any failure (best-effort read, matching this module's other
            list_* methods).
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                cursor = await conn.execute(
                    """
                    SELECT session_id, MAX(created_at)
                    FROM checkpoints
                    GROUP BY session_id
                    """
                )
                rows = await cursor.fetchall()
                return [(row[0], row[1]) for row in rows]
        except Exception as e:
            logger.error("checkpoint_session_ids_get_failed", error=str(e))
            return []

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

    async def save_kr_realized_pnl(self, record: dict[str, Any]) -> bool:
        """
        Persist a matched entry/exit realized-P&L record for a KR stock
        close/reduce.

        (Phase1 Task 4/C3a: KR had no per-trade realized-P&L record at all —
        only the broker's day-level ka10074, ephemeral and unmatched to a
        specific entry. Mirrors save_coin_realized_pnl's shape, plus
        entry/exit decision IDs and holding_period_seconds. Derived/display
        record only — the broker ledger (ka10074) remains the source of
        truth for KR realized P&L math.)

        Args:
            record: dict with keys id, stk_cd, entry_price, exit_price,
                quantity, realized_amount, and optionally
                entry_decision_id/exit_decision_id/holding_period_seconds/
                entry_at/exit_at/created_at.

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO kr_realized_pnl
                    (id, stk_cd, entry_price, exit_price, quantity,
                     realized_amount, entry_decision_id, exit_decision_id,
                     holding_period_seconds, entry_at, exit_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record["stk_cd"],
                        record.get("entry_price"),
                        record.get("exit_price"),
                        record.get("quantity"),
                        record.get("realized_amount"),
                        record.get("entry_decision_id"),
                        record.get("exit_decision_id"),
                        record.get("holding_period_seconds"),
                        record.get("entry_at"),
                        record.get("exit_at"),
                        record.get("created_at", datetime.now()),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "kr_realized_pnl_saved",
                    stk_cd=record["stk_cd"],
                    realized_amount=record.get("realized_amount"),
                )
                return True
        except Exception as e:
            logger.error(
                "kr_realized_pnl_save_failed",
                stk_cd=record.get("stk_cd"),
                error=str(e),
            )
            return False

    async def get_kr_realized_pnl(
        self,
        stk_cd: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get realized KR stock P&L records, newest first, optionally
        filtered by stk_cd."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if stk_cd:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM kr_realized_pnl
                        WHERE stk_cd = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (stk_cd, limit, offset),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM kr_realized_pnl
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("kr_realized_pnl_get_failed", error=str(e))
            return []

    # -------------------------------------------
    # Daily Performance Snapshot (Phase1 Task 5/C3b)
    # -------------------------------------------

    async def save_daily_perf_snapshot(self, record: dict[str, Any]) -> bool:
        """
        Persist one end-of-day performance snapshot row.

        Uses INSERT OR IGNORE against the trade_date PRIMARY KEY: a second
        write for a trade_date that already has a row is a silent no-op
        rather than an overwrite or an error — durable "at most once per
        day" semantics without needing a separate existence check.

        Args:
            record: dict with keys trade_date, equity, realized_pnl,
                commission, tax, net_pnl, win_trades, loss_trades,
                cumulative_return_pct, and optionally regime_snapshot_id.

        Returns:
            True if the statement executed successfully (including when the
            row already existed and the insert was ignored).
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO daily_perf_snapshot
                    (trade_date, equity, realized_pnl, commission, tax,
                     net_pnl, win_trades, loss_trades, cumulative_return_pct,
                     regime_snapshot_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["trade_date"],
                        record.get("equity"),
                        record.get("realized_pnl"),
                        record.get("commission"),
                        record.get("tax"),
                        record.get("net_pnl"),
                        record.get("win_trades"),
                        record.get("loss_trades"),
                        record.get("cumulative_return_pct"),
                        record.get("regime_snapshot_id"),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "daily_perf_snapshot_saved",
                    trade_date=record.get("trade_date"),
                )
                return True
        except Exception as e:
            logger.error(
                "daily_perf_snapshot_save_failed",
                trade_date=record.get("trade_date"),
                error=str(e),
            )
            return False

    async def get_daily_perf_snapshots(self, limit: int = 60) -> list[dict[str, Any]]:
        """Get daily performance snapshots, newest first by trade_date."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM daily_perf_snapshot
                    ORDER BY trade_date DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("daily_perf_snapshots_get_failed", error=str(e))
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
                flow (dict/None), agent_weights (dict/None — Phase4:
                consensus weights actually used, JSON-serialized),
                total_messages/total_rounds (int/None — session-ssot P4-3:
                transcript size, for a list view that shouldn't have to
                parse agent_chat_transcripts' JSON blob per row).
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
                     market_sentiment, flow, agent_weights,
                     total_messages, total_rounds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(decision["agent_weights"])
                        if decision.get("agent_weights") is not None
                        else None,
                        decision.get("total_messages"),
                        decision.get("total_rounds"),
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

    async def count_agent_chat_decisions(self, ticker: Optional[str] = None) -> int:
        """
        Count agent_chat_decisions rows, optionally filtered by ticker.

        session-ssot P4-4: the durable/permanent session count the agent-chat
        `/status` endpoint's `total_sessions` field now reports (the retired
        in-memory `_session_history` list's `len()` used to serve this and
        evaporated on restart; the ledger is the sole, permanent source now).

        Returns:
            Row count, or 0 on any storage error (failure-harmless -- a
            counting outage must never 500 the status endpoint).
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                if ticker:
                    cursor = await conn.execute(
                        "SELECT COUNT(*) FROM agent_chat_decisions WHERE ticker = ?",
                        (ticker,),
                    )
                else:
                    cursor = await conn.execute(
                        "SELECT COUNT(*) FROM agent_chat_decisions"
                    )
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("agent_chat_decisions_count_failed", error=str(e))
            return 0

    async def update_decision_outcome(
        self, decision_id: str, realized_pnl: float
    ) -> bool:
        """
        Backfill the realized P&L outcome of an already-recorded agent-chat
        decision (Phase1 Task 4/C3a).

        Called once the position that decision opened is matched-closed
        (see save_kr_realized_pnl / trade_log.record_kr_realized_pnl_async),
        so a decision's eventual real-world outcome can be attributed back
        to it for later analysis.

        Args:
            decision_id: agent_chat_decisions.id to update
            realized_pnl: realized P&L amount to record

        Returns:
            True if the UPDATE executed successfully (including when no row
            matched decision_id — this is not treated as an error since a
            decision may legitimately not exist, e.g. a monitor-driven
            stop/take-profit close with no originating decision).
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "UPDATE agent_chat_decisions SET outcome_realized_pnl = ? WHERE id = ?",
                    (realized_pnl, decision_id),
                )
                await conn.commit()
                logger.debug(
                    "decision_outcome_updated",
                    decision_id=decision_id,
                    realized_pnl=realized_pnl,
                )
                return True
        except Exception as e:
            logger.error(
                "decision_outcome_update_failed",
                decision_id=decision_id,
                error=str(e),
            )
            return False

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
    # Agent-Chat Transcripts Ledger (session-ssot P4-3)
    # -------------------------------------------

    async def save_agent_chat_transcript(
        self, session_id: str, transcript_json: str
    ) -> bool:
        """
        Persist the full discussion transcript (ChatSession.model_dump(mode=
        "json"), JSON-encoded by the caller) for a completed session.

        INSERT OR REPLACE so re-persisting the same session_id (a session
        that somehow completes twice, or a retry) is idempotent rather than
        erroring on the PRIMARY KEY. Independent of
        save_agent_chat_decision -- decision_log.persist_session calls both
        in separate try/except blocks so a failure in one never blocks or
        rolls back the other.

        Args:
            session_id: ChatSession.id -- same id agent_chat_decisions.id
                uses for the same session, so callers can join the two.
            transcript_json: pre-serialized JSON string (the full
                ChatSession dump), not a dict -- mirrors how other *_json
                columns in this file are already-serialized TEXT blobs.

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO agent_chat_transcripts
                    (session_id, transcript_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, transcript_json, datetime.now().isoformat()),
                )
                await conn.commit()
                logger.debug("agent_chat_transcript_saved", session_id=session_id)
                return True
        except Exception as e:
            logger.error(
                "agent_chat_transcript_save_failed",
                session_id=session_id,
                error=str(e),
            )
            return False

    async def get_agent_chat_transcript(self, session_id: str) -> Optional[str]:
        """Get the persisted transcript JSON for a session, or None if this
        session was never persisted (or storage errors)."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                async with conn.execute(
                    "SELECT transcript_json FROM agent_chat_transcripts"
                    " WHERE session_id = ?",
                    (session_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error(
                "agent_chat_transcript_get_failed",
                session_id=session_id,
                error=str(e),
            )
            return None

    async def update_decision_label(self, decision_id: str, label: str) -> bool:
        """
        Backfill the outcome_label ("correct"/"incorrect"/"flat") of an
        already-recorded agent-chat decision (Phase2 Task 1).

        Called by services/trading/calibration.py::label_and_calibrate once
        a decision's outcome_realized_pnl has been judged. Mirrors
        update_decision_outcome's shape/semantics exactly (a decision_id
        with no matching row is not treated as an error).

        Args:
            decision_id: agent_chat_decisions.id to update
            label: "correct", "incorrect", or "flat"

        Returns:
            True if the UPDATE executed successfully (including a no-op
            match), False on any exception.
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "UPDATE agent_chat_decisions SET outcome_label = ? WHERE id = ?",
                    (label, decision_id),
                )
                await conn.commit()
                logger.debug(
                    "decision_label_updated", decision_id=decision_id, label=label
                )
                return True
        except Exception as e:
            logger.error(
                "decision_label_update_failed",
                decision_id=decision_id,
                error=str(e),
            )
            return False

    # -------------------------------------------
    # Agent Calibration Ledger (Phase2 Task 1)
    # -------------------------------------------

    async def save_agent_calibration(self, record: dict[str, Any]) -> bool:
        """
        Persist one per-agent calibration snapshot row.

        (Phase2 Task 1: per-agent accuracy/avg_confidence over a trailing
        window, computed by services/trading/calibration.py::
        label_and_calibrate from the agent_chat_decisions/agent_chat_votes
        ledger. Mirrors save_coin_realized_pnl's shape.)

        Args:
            record: dict with keys id, agent_type, as_of_date, window_days,
                decisions_scored, correct, accuracy, avg_confidence.

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_calibration
                    (id, agent_type, as_of_date, window_days, decisions_scored,
                     correct, accuracy, avg_confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record.get("agent_type"),
                        record.get("as_of_date"),
                        record.get("window_days"),
                        record.get("decisions_scored"),
                        record.get("correct"),
                        record.get("accuracy"),
                        record.get("avg_confidence"),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "agent_calibration_saved",
                    agent_type=record.get("agent_type"),
                    accuracy=record.get("accuracy"),
                )
                return True
        except Exception as e:
            logger.error(
                "agent_calibration_save_failed",
                agent_type=record.get("agent_type"),
                error=str(e),
            )
            return False

    async def get_agent_calibration(
        self, as_of_date: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Get agent calibration rows, newest first, optionally filtered by
        as_of_date."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                if as_of_date:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM agent_calibration
                        WHERE as_of_date = ?
                        ORDER BY created_at DESC, rowid DESC
                        """,
                        (as_of_date,),
                    )
                else:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM agent_calibration
                        ORDER BY created_at DESC, rowid DESC
                        """
                    )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("agent_calibration_get_failed", error=str(e))
            return []

    # -------------------------------------------
    # Regime Snapshot (Phase2 Task 2)
    # -------------------------------------------

    async def save_regime_snapshot(self, record: dict[str, Any]) -> bool:
        """
        Persist one daily market-regime snapshot row.

        (Phase2 Task 2: computed by services/trading/regime.py::
        compute_regime_snapshot from the background scanner's
        scan_sessions breadth distribution — the only durable market-wide
        artifact in this codebase. Mirrors save_coin_realized_pnl's shape.)

        Args:
            record: dict with keys id, trade_date, breadth_buy,
                breadth_sell, breadth_hold, breadth_ratio, regime_label,
                and optionally source (defaults to 'scanner').

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO regime_snapshot
                    (id, trade_date, breadth_buy, breadth_sell, breadth_hold,
                     breadth_ratio, regime_label, source,
                     index_kospi, index_kospi_chg_pct, index_kosdaq,
                     index_kosdaq_chg_pct, foreign_net_amount,
                     institution_net_amount, market_sentiment_label, sentiment_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"], record.get("trade_date"),
                        record.get("breadth_buy"), record.get("breadth_sell"),
                        record.get("breadth_hold"), record.get("breadth_ratio"),
                        record.get("regime_label"), record.get("source", "scanner"),
                        record.get("index_kospi"), record.get("index_kospi_chg_pct"),
                        record.get("index_kosdaq"), record.get("index_kosdaq_chg_pct"),
                        record.get("foreign_net_amount"),
                        record.get("institution_net_amount"),
                        record.get("market_sentiment_label"),
                        record.get("sentiment_score"),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "regime_snapshot_saved",
                    trade_date=record.get("trade_date"),
                    regime_label=record.get("regime_label"),
                )
                return True
        except Exception as e:
            logger.error(
                "regime_snapshot_save_failed",
                trade_date=record.get("trade_date"),
                error=str(e),
            )
            return False

    async def get_regime_snapshots(self, limit: int = 60) -> list[dict[str, Any]]:
        """Get regime snapshots, newest first by created_at."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM regime_snapshot
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("regime_snapshots_get_failed", error=str(e))
            return []

    # -------------------------------------------
    # EOD Review Report (Phase2 Task 3)
    # -------------------------------------------

    async def save_eod_review(self, record: dict[str, Any]) -> bool:
        """
        Persist one end-of-day review report row.

        (Phase2 Task 3: the assembled report from
        services/trading/eod_review.py::build_eod_review. Uses
        INSERT OR REPLACE against the trade_date PRIMARY KEY so re-running
        the same day's review — e.g. after a late fill correction — updates
        the existing row rather than accreting a duplicate.)

        Args:
            record: dict with keys trade_date, report_json (a JSON string).

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO eod_review (trade_date, report_json)
                    VALUES (?, ?)
                    """,
                    (
                        record["trade_date"],
                        record.get("report_json"),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "eod_review_saved", trade_date=record.get("trade_date")
                )
                return True
        except Exception as e:
            logger.error(
                "eod_review_save_failed",
                trade_date=record.get("trade_date"),
                error=str(e),
            )
            return False

    async def get_eod_reviews(self, limit: int = 30) -> list[dict[str, Any]]:
        """Get EOD review reports, newest first by trade_date."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM eod_review
                    ORDER BY trade_date DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("eod_reviews_get_failed", error=str(e))
            return []

    # -------------------------------------------
    # Strategy Revisions (Phase3 Task 1)
    # -------------------------------------------

    async def save_strategy_revision(self, record: dict[str, Any]) -> bool:
        """Persist one strategy revision row (Phase3 — EOD consensus run or
        manual /trading/strategy edit). Accrete-style; the active revision is
        the app_settings 'strategy:active_revision_id' pointer, not a flag
        here. Failure-harmless: returns False, never raises (market-close
        edge caller).
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    INSERT INTO strategy_revisions
                    (id, trade_date, source, stance, consensus_level, changed,
                     strategy_json, parent_revision_id, rationale, votes_json,
                     regime_snapshot_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record.get("trade_date"),
                        record.get("source"),
                        record.get("stance"),
                        record.get("consensus_level"),
                        1 if record.get("changed") else 0,
                        record["strategy_json"],
                        record.get("parent_revision_id"),
                        record.get("rationale"),
                        record.get("votes_json"),
                        record.get("regime_snapshot_id"),
                    ),
                )
                await conn.commit()
                logger.debug(
                    "strategy_revision_saved",
                    revision_id=record.get("id"),
                    trade_date=record.get("trade_date"),
                    stance=record.get("stance"),
                )
                return True
        except Exception as e:
            logger.error(
                "strategy_revision_save_failed",
                revision_id=record.get("id"),
                error=str(e),
            )
            return False

    async def get_strategy_revisions(self, limit: int = 30) -> list[dict[str, Any]]:
        """Strategy revisions, newest first (created_at DESC, rowid DESC
        tie-break so same-second inserts stay insertion-ordered)."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    """
                    SELECT * FROM strategy_revisions
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error("strategy_revisions_get_failed", error=str(e))
            return []

    async def get_strategy_revision(self, revision_id: str) -> Optional[dict[str, Any]]:
        """Single strategy revision by id, or None."""
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT * FROM strategy_revisions WHERE id = ?",
                    (revision_id,),
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(
                "strategy_revision_get_failed", revision_id=revision_id, error=str(e)
            )
            return None

    # -------------------------------------------
    # Regime FK Backfill (Phase2 Task 4)
    # -------------------------------------------

    async def backfill_regime_id(self, trade_date: str, regime_snapshot_id: str) -> None:
        """
        Backfill `regime_snapshot_id` onto the day's `daily_perf_snapshot`
        row AND every `agent_chat_decisions` row for that trade_date.

        (Phase2 Task 4: both FKs were left nullable by Phase1/Task2 since
        the regime snapshot is only computed AFTER the day's decisions and
        performance snapshot already exist — this is the tail step of
        services/trading/eod_orchestrator.py::run_eod_review, called once
        the regime_snapshot row itself has been saved.)

        Failure-harmless: any error is logged and swallowed (never raises)
        — this runs off the live market-close scheduler tick.

        Args:
            trade_date: "YYYY-MM-DD" to backfill.
            regime_snapshot_id: id of the regime_snapshot row to attach.
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "UPDATE daily_perf_snapshot SET regime_snapshot_id = ? "
                    "WHERE trade_date = ?",
                    (regime_snapshot_id, trade_date),
                )
                await conn.execute(
                    "UPDATE agent_chat_decisions SET regime_snapshot_id = ? "
                    "WHERE trade_date = ?",
                    (regime_snapshot_id, trade_date),
                )
                await conn.commit()
                logger.debug(
                    "regime_id_backfilled",
                    trade_date=trade_date,
                    regime_snapshot_id=regime_snapshot_id,
                )
        except Exception as e:
            logger.error(
                "regime_id_backfill_failed",
                trade_date=trade_date,
                error=str(e),
            )
            return

    async def backfill_market_context(
        self, trade_date: str, sentiment_json: str, flow_json: str
    ) -> None:
        """그날 모든 agent_chat_decisions의 예약 슬롯(market_sentiment/flow)에
        시장전체 심리·수급 JSON을 박제(EOD 백필 — regime_snapshot_id와 동일 패턴).
        Phase1이 write-time None으로 남긴 슬롯을 EOD가 채운다. 실패-무해."""
        await self.initialize()
        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    "UPDATE agent_chat_decisions "
                    "SET market_sentiment = ?, flow = ? WHERE trade_date = ?",
                    (sentiment_json, flow_json, trade_date),
                )
                await conn.commit()
        except Exception as e:
            logger.error("backfill_market_context_failed",
                         trade_date=trade_date, error=str(e))

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
