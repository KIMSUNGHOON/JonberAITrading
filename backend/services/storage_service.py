"""
SQLite Storage Service for Session Persistence

Provides:
- Session state storage
- LangGraph checkpointing
- Cache management

No external server required - uses embedded SQLite database.
"""

import json
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
        self.db_path = db_path or DEFAULT_DB_PATH
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

                # Create indexes
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id)"
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

                await conn.commit()
                self._initialized = True
                logger.info("storage_initialized", db_path=str(self.db_path))
        except Exception as e:
            logger.error("storage_init_failed", error=str(e))
            raise

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
        Save or update a coin position.

        Args:
            position: Position data with keys:
                - market, currency, quantity, avg_entry_price,
                - stop_loss, take_profit, session_id

        Returns:
            True if saved successfully
        """
        await self.initialize()

        try:
            async with aiosqlite.connect(str(self.db_path)) as conn:
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
                        position["market"],
                        position["currency"],
                        position["quantity"],
                        position["avg_entry_price"],
                        position.get("stop_loss"),
                        position.get("take_profit"),
                        position.get("session_id"),
                        position["market"],
                        datetime.now(),
                        datetime.now(),
                    ),
                )
                await conn.commit()
                logger.debug("coin_position_saved", market=position["market"])
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
