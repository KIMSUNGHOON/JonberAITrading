"""
Unified Session Manager Service

Provides centralized session management for all analysis types (US Stock, Coin, Korean Stock).

Features:
- Single source of truth for all sessions
- Thread-safe with asyncio.Lock
- SQLite persistence for recovery after restart
- Automatic cleanup of expired sessions
- Market-type based filtering
- WebSocket integration support

Session Types:
- stock: US Stock analysis (analysis.py)
- coin: Cryptocurrency analysis (coin.py)
- kiwoom: Korean Stock analysis (kr_stocks.py)
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import aiosqlite

import structlog

logger = structlog.get_logger()


# -------------------------------------------
# Configuration
# -------------------------------------------

MAX_CONCURRENT_ANALYSES = 3
COMPLETED_SESSION_TTL = timedelta(hours=1)
DB_PATH = "data/sessions.db"
# Max buffered messages per WebSocket subscriber. On overflow the oldest is dropped
# (realtime favors the latest state), so a slow/dead socket cannot grow unbounded.
SUBSCRIBER_QUEUE_MAXSIZE = 256


class MarketType(str, Enum):
    """Supported market types."""
    STOCK = "stock"      # US stocks
    COIN = "coin"        # Cryptocurrency (Upbit)
    KIWOOM = "kiwoom"    # Korean stocks (Kiwoom)


class SessionStatus(str, Enum):
    """Session lifecycle statuses."""
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class AnalysisSession:
    """
    Unified session data structure for all analysis types.

    This replaces the separate dicts in analysis.py, coin.py, kr_stocks.py.
    """
    session_id: str
    market_type: MarketType
    ticker: str                          # AAPL, KRW-BTC, 005930
    display_name: str                    # Apple Inc, 비트코인, 삼성전자
    status: SessionStatus = SessionStatus.RUNNING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    last_node: Optional[str] = None

    # State data (stored as JSON in SQLite)
    state: Dict[str, Any] = field(default_factory=dict)

    # Additional metadata based on market type
    # For Korean stocks (kiwoom)
    stk_cd: Optional[str] = None
    stk_nm: Optional[str] = None
    # For coins
    market: Optional[str] = None
    korean_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "session_id": self.session_id,
            "market_type": self.market_type.value if isinstance(self.market_type, MarketType) else self.market_type,
            "ticker": self.ticker,
            "display_name": self.display_name,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "error": self.error,
            "last_node": self.last_node,
            "state": self.state,
            "stk_cd": self.stk_cd,
            "stk_nm": self.stk_nm,
            "market": self.market,
            "korean_name": self.korean_name,
        }

    def to_legacy_dict(self) -> Dict[str, Any]:
        """
        Convert to legacy format for backward compatibility.

        Matches the format used by existing routes (analysis.py, coin.py, kr_stocks.py).
        """
        base = {
            "session_id": self.session_id,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
            "state": self.state,
            "created_at": self.created_at,
            "error": self.error,
            "last_node": self.last_node,
        }

        if self.market_type == MarketType.STOCK:
            base["ticker"] = self.ticker
        elif self.market_type == MarketType.COIN:
            base["market"] = self.market or self.ticker
            base["korean_name"] = self.korean_name or self.display_name
        elif self.market_type == MarketType.KIWOOM:
            base["stk_cd"] = self.stk_cd or self.ticker
            base["stk_nm"] = self.stk_nm or self.display_name

        return base


# -------------------------------------------
# Stranded-session reconciliation (restart shape repair)
# -------------------------------------------
# TradeAction values that never carry execution risk — these skip the
# proposal-age staleness gate below (only BUY/SELL-ish actions are gated).
_NO_TRADE_ACTIONS = {"HOLD", "WATCH", "AVOID"}
# A trade proposal older than this, discovered mid-restart, is considered too
# stale to safely resume toward approval (market conditions may have moved).
_PROPOSAL_AGE_LIMIT = timedelta(hours=6)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO datetime string (or pass through a datetime) into an
    aware UTC datetime.

    Returns None if `value` is None or unparseable. Naive datetimes/strings
    (no tzinfo) are assumed to be UTC rather than raising on comparison.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class ReconcileReport:
    """Outcome of a single reconcile_stranded_sessions() pass."""
    flipped: List[str] = field(default_factory=list)
    errored: List[str] = field(default_factory=list)
    cancelled: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)


class SessionManager:
    """
    Unified session manager with SQLite persistence.

    Thread-safe session management for all analysis types.
    Replaces the distributed dict-based session storage.

    Usage:
        manager = await get_session_manager()
        session = await manager.create_session(
            session_id="uuid",
            market_type=MarketType.KIWOOM,
            ticker="005930",
            display_name="삼성전자"
        )
        await manager.update_status(session_id, SessionStatus.COMPLETED)
    """

    def __init__(self):
        self._sessions: Dict[str, AnalysisSession] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

        # Semaphore for concurrent analysis control
        self._analysis_semaphore: Optional[asyncio.Semaphore] = None
        # Atomic counter for active analyses (thread-safe alternative to semaphore._value)
        self._active_analysis_count: int = 0
        self._counter_lock = asyncio.Lock()

        # Subscribers for session updates (WebSocket integration)
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}

    async def initialize(self) -> None:
        """Initialize the session manager and SQLite database."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            # Ensure data directory exists
            import os
            os.makedirs("data", exist_ok=True)

            # Create SQLite table
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS analysis_sessions (
                        session_id TEXT PRIMARY KEY,
                        market_type TEXT NOT NULL,
                        ticker TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'running',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        error TEXT,
                        last_node TEXT,
                        state_json TEXT,
                        stk_cd TEXT,
                        stk_nm TEXT,
                        market TEXT,
                        korean_name TEXT
                    )
                """)

                # Create indexes for common queries
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_status
                    ON analysis_sessions(status)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_market_type
                    ON analysis_sessions(market_type)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_ticker
                    ON analysis_sessions(ticker)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_created_at
                    ON analysis_sessions(created_at DESC)
                """)

                await db.commit()

            # Load active sessions from SQLite (running and awaiting_approval)
            await self._load_active_sessions()

            # Repair the shape of any session an unclean restart stranded
            # mid-graph (running with no live task behind it, or awaiting
            # approval with a decision the HITL layer never got to act on).
            # Runs on the just-loaded sessions before anything else can see
            # them. NOTE: reconcile_stranded_sessions() does NOT acquire
            # self._lock itself — we are already holding it here, and
            # asyncio.Lock is not reentrant (re-acquiring would deadlock).
            reconcile_report = await self.reconcile_stranded_sessions()

            # Initialize semaphore
            self._analysis_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

            self._initialized = True
            logger.info(
                "session_manager_initialized",
                loaded_sessions=len(self._sessions),
                reconciled_flipped=len(reconcile_report.flipped),
                reconciled_errored=len(reconcile_report.errored),
                reconciled_cancelled=len(reconcile_report.cancelled),
            )

    async def _load_active_sessions(self) -> None:
        """Load active sessions from SQLite on startup."""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM analysis_sessions
                WHERE status IN ('running', 'awaiting_approval')
                ORDER BY created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()

                for row in rows:
                    session = self._row_to_session(row)
                    self._sessions[session.session_id] = session

    def _row_to_session(self, row: aiosqlite.Row) -> AnalysisSession:
        """Convert a SQLite row to AnalysisSession."""
        state = {}
        if row["state_json"]:
            try:
                state = json.loads(row["state_json"])
            except json.JSONDecodeError:
                pass

        # Parse datetime strings
        created_at = datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)
        updated_at = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(timezone.utc)

        return AnalysisSession(
            session_id=row["session_id"],
            market_type=MarketType(row["market_type"]),
            ticker=row["ticker"],
            display_name=row["display_name"],
            status=SessionStatus(row["status"]),
            created_at=created_at,
            updated_at=updated_at,
            error=row["error"],
            last_node=row["last_node"],
            state=state,
            stk_cd=row["stk_cd"],
            stk_nm=row["stk_nm"],
            market=row["market"],
            korean_name=row["korean_name"],
        )

    async def reconcile_stranded_sessions(
        self,
        *,
        now: Optional[datetime] = None,
        checkpoint_next: Optional[Callable[[str], Awaitable[Optional[tuple]]]] = None,
    ) -> ReconcileReport:
        """
        Repair the shape of sessions an unclean restart stranded mid-graph.

        A killed process can leave a session in a shape that no longer means
        what it says: RUNNING with no task actually running behind it (the
        classic "immortal zombie" that 404s on approve — nothing will ever
        move it out of RUNNING again), or AWAITING_APPROVAL with a decision
        already recorded in state but never acted on. This walks all loaded
        sessions once and flips each into a shape that is safe to resume
        or that fails closed.

        Rules (see specs/.../task-1-brief.md for the full shape table):
          - RUNNING + awaiting_approval flag + a trade_proposal in state:
            this is a graph parked at (or just before) the HITL interrupt.
              - BUY/SELL proposals older than 6h are considered stale
                (market may have moved) -> ERROR.
              - If `checkpoint_next` is supplied and does NOT report the
                graph's next node as an "approval" step, we can't trust
                that a resume would actually re-enter HITL -> ERROR.
              - Otherwise -> flip to AWAITING_APPROVAL (with a cleared
                approval_status so the next real decision isn't shadowed
                by a stale one from before restart).
          - RUNNING otherwise (no awaiting flag / no proposal) -> ERROR:
            there is no live task, so this session could never reach
            AWAITING_APPROVAL or COMPLETED on its own again.
          - AWAITING_APPROVAL with approval_status == "approved" but the
            awaiting_approval flag already cleared: an approval decision
            was recorded but we cannot tell whether execution happened
            before the process died -> ERROR (uncertain fill, never
            silently resumed).
          - AWAITING_APPROVAL with approval_status == "cancelled": the
            decision was recorded but the status mirror never caught up
            -> CANCELLED (pure shape correction, no new decision made).
          - Everything else (a normal, still-pending AWAITING_APPROVAL)
            is left as-is -> kept.

        A stale `auto_approve_at` deadline is always cleared regardless of
        branch: the in-process 60s grace-period injector that owned it is
        gone after a restart, so the deadline can never fire and must not
        be trusted by any UI reading it back.

        Locking: this method does NOT acquire self._lock. It is invoked by
        initialize() from inside its own `async with self._lock:` block, and
        self._lock (asyncio.Lock) is not reentrant, so acquiring it here
        would deadlock initialize() on every startup. Callers outside
        initialize() (tests, or a future manual admin trigger) call this
        directly without holding the lock; that's an accepted trade-off
        because this only ever runs once, at startup, before any
        concurrent session traffic exists.

        Args:
            now: Injectable "current time" for tests; defaults to
                datetime.now(timezone.utc).
            checkpoint_next: Injectable async lookup of
                `(session_id) -> Optional[tuple[str, ...]]` describing the
                graph checkpoint's pending next node(s) for that session.
                Production wiring (a real LangGraph checkpointer lookup) is
                not part of this task; None (the default) skips the check.

        Returns:
            ReconcileReport with the session_ids that were flipped to
            AWAITING_APPROVAL, errored, cancelled, or kept unchanged.
        """
        now = now or datetime.now(timezone.utc)
        rep = ReconcileReport()

        for sid, s in list(self._sessions.items()):
            st = s.state or {}
            awaiting = bool(st.get("awaiting_approval"))
            appr = st.get("approval_status")
            prop = st.get("trade_proposal") or None

            # A restart always invalidates any pending auto-approve deadline
            # (the injector task that would fire it is gone).
            changed_common = st.pop("auto_approve_at", None) is not None
            # I7: the FE operations board renders a live countdown off
            # auto_approve_at; silently popping it (above) would leave a
            # session that LOOKS like it's still awaiting a decision with no
            # explanation for why the countdown vanished. Do NOT re-arm it --
            # just annotate so the reasoning log honestly explains the
            # restart cleared it and a human must decide now.
            if changed_common:
                st.setdefault("reasoning_log", []).append(
                    "재시작으로 자율 승인 타이머 해제 — 수동 승인 필요"
                )

            if s.status == SessionStatus.RUNNING and awaiting and prop:
                action = str(prop.get("action") or "").upper()

                stale = False
                if action not in _NO_TRADE_ACTIONS:
                    created = (
                        _parse_dt(prop.get("created_at"))
                        or _parse_dt(s.created_at)
                        or now
                    )
                    stale = (now - created) > _PROPOSAL_AGE_LIMIT

                parked_ok = True
                if checkpoint_next is not None:
                    nxt = await checkpoint_next(sid)
                    parked_ok = bool(nxt) and "approval" in tuple(nxt)

                if stale or not parked_ok:
                    s.status = SessionStatus.ERROR
                    s.error = "서버 재시작으로 분석 중단 (제안 만료/체크포인트 불일치)"
                    rep.errored.append(sid)
                else:
                    s.status = SessionStatus.AWAITING_APPROVAL
                    st["approval_status"] = None  # new decision must overwrite, not be shadowed
                    rep.flipped.append(sid)

            elif s.status == SessionStatus.RUNNING:
                s.status = SessionStatus.ERROR
                s.error = "서버 재시작으로 분석 중단"
                rep.errored.append(sid)

            elif (
                s.status == SessionStatus.AWAITING_APPROVAL
                and not awaiting
                and appr == "approved"
            ):
                s.status = SessionStatus.ERROR
                s.error = "실행 중단 — 체결 확인 필요"
                rep.errored.append(sid)

            elif s.status == SessionStatus.AWAITING_APPROVAL and appr == "cancelled":
                s.status = SessionStatus.CANCELLED
                rep.cancelled.append(sid)

            else:
                rep.kept.append(sid)

            if sid in rep.flipped or sid in rep.errored or sid in rep.cancelled or changed_common:
                s.updated_at = now
                await self._save_session(s)

        logger.info(
            "session_reconcile_done",
            flipped=len(rep.flipped),
            errored=len(rep.errored),
            cancelled=len(rep.cancelled),
            kept=len(rep.kept),
        )
        return rep

    async def create_session(
        self,
        session_id: str,
        market_type: MarketType,
        ticker: str,
        display_name: str,
        **kwargs,
    ) -> AnalysisSession:
        """
        Create a new analysis session.

        Args:
            session_id: Unique session identifier
            market_type: Type of market (stock, coin, kiwoom)
            ticker: Stock/coin code
            display_name: Human-readable name
            **kwargs: Additional fields (stk_cd, stk_nm, market, korean_name)

        Returns:
            The created AnalysisSession
        """
        await self.initialize()

        session = AnalysisSession(
            session_id=session_id,
            market_type=market_type,
            ticker=ticker,
            display_name=display_name,
            stk_cd=kwargs.get("stk_cd"),
            stk_nm=kwargs.get("stk_nm"),
            market=kwargs.get("market"),
            korean_name=kwargs.get("korean_name"),
            state=kwargs.get("state", {}),
        )

        async with self._lock:
            self._sessions[session_id] = session

            # Persist to SQLite
            await self._save_session(session)

        logger.info(
            "session_created",
            session_id=session_id,
            market_type=market_type.value,
            ticker=ticker,
        )

        return session

    async def _save_session(self, session: AnalysisSession) -> None:
        """Save session to SQLite."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO analysis_sessions
                (session_id, market_type, ticker, display_name, status,
                 created_at, updated_at, error, last_node, state_json,
                 stk_cd, stk_nm, market, korean_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session.session_id,
                session.market_type.value if isinstance(session.market_type, MarketType) else session.market_type,
                session.ticker,
                session.display_name,
                session.status.value if isinstance(session.status, SessionStatus) else session.status,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                session.error,
                session.last_node,
                json.dumps(session.state, default=str),
                session.stk_cd,
                session.stk_nm,
                session.market,
                session.korean_name,
            ))
            await db.commit()

    async def get_session(self, session_id: str) -> Optional[AnalysisSession]:
        """Get session by ID."""
        await self.initialize()
        return self._sessions.get(session_id)

    async def get_session_dict(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session as legacy dict format for backward compatibility."""
        session = await self.get_session(session_id)
        return session.to_legacy_dict() if session else None

    async def update_status(
        self,
        session_id: str,
        status: SessionStatus,
        error: Optional[str] = None,
    ) -> None:
        """Update session status."""
        await self.initialize()

        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.status = status
                session.updated_at = datetime.now(timezone.utc)
                if error:
                    session.error = error

                await self._save_session(session)
                await self._notify_subscribers(session_id, {"type": "status", "status": status.value})

                logger.debug(
                    "session_status_updated",
                    session_id=session_id,
                    status=status.value,
                )

    async def update_state(
        self,
        session_id: str,
        state_updates: Dict[str, Any],
        last_node: Optional[str] = None,
    ) -> None:
        """Update session state."""
        await self.initialize()

        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]

                # Compute the reasoning-log delta BEFORE applying the update, so the
                # WS can stream only the newly-appended entries instead of re-diffing
                # the whole log.
                reasoning_delta = None
                if "reasoning_log" in state_updates:
                    old_log = session.state.get("reasoning_log") or []
                    new_log = state_updates.get("reasoning_log") or []
                    if isinstance(new_log, list) and len(new_log) >= len(old_log):
                        reasoning_delta = new_log[len(old_log):]

                session.state.update(state_updates)
                session.updated_at = datetime.now(timezone.utc)
                if last_node:
                    session.last_node = last_node

                await self._save_session(session)

                payload: Dict[str, Any] = {
                    "type": "state_update",
                    "updates": list(state_updates.keys()),
                }
                if last_node:
                    payload["last_node"] = last_node
                if reasoning_delta:
                    payload["reasoning_delta"] = reasoning_delta
                await self._notify_subscribers(session_id, payload)

    async def get_all_sessions(
        self,
        market_type: Optional[MarketType] = None,
        status: Optional[SessionStatus] = None,
    ) -> Dict[str, AnalysisSession]:
        """
        Get all sessions, optionally filtered.

        Args:
            market_type: Filter by market type
            status: Filter by status

        Returns:
            Dict of session_id -> AnalysisSession
        """
        await self.initialize()

        result = {}
        for session_id, session in self._sessions.items():
            if market_type and session.market_type != market_type:
                continue
            if status and session.status != status:
                continue
            result[session_id] = session

        return result

    async def get_sessions_dict(
        self,
        market_type: Optional[MarketType] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get all sessions as legacy dict format."""
        sessions = await self.get_all_sessions(market_type=market_type)
        return {sid: s.to_legacy_dict() for sid, s in sessions.items()}

    async def remove_session(self, session_id: str) -> bool:
        """Remove a session."""
        await self.initialize()

        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

                # Remove from SQLite
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM analysis_sessions WHERE session_id = ?",
                        (session_id,)
                    )
                    await db.commit()

                # Cleanup subscribers
                if session_id in self._subscribers:
                    del self._subscribers[session_id]

                logger.info("session_removed", session_id=session_id)
                return True

        return False

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up completed/expired sessions.

        Returns:
            Number of sessions removed
        """
        await self.initialize()

        now = datetime.now(timezone.utc)
        expired = []

        async with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.status in (SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.CANCELLED):
                    if now - session.created_at > COMPLETED_SESSION_TTL:
                        expired.append(session_id)

            for session_id in expired:
                del self._sessions[session_id]

            # Also clean from SQLite
            if expired:
                async with aiosqlite.connect(DB_PATH) as db:
                    placeholders = ",".join("?" * len(expired))
                    await db.execute(
                        f"DELETE FROM analysis_sessions WHERE session_id IN ({placeholders})",
                        expired
                    )
                    await db.commit()

        if expired:
            logger.info(
                "sessions_cleanup_completed",
                removed_count=len(expired),
                remaining_count=len(self._sessions),
            )

        return len(expired)

    # -------------------------------------------
    # Concurrency Control (Semaphore)
    # -------------------------------------------

    async def acquire_analysis_slot(self, timeout: float = 60.0) -> bool:
        """Acquire an analysis slot."""
        await self.initialize()

        try:
            await asyncio.wait_for(
                self._analysis_semaphore.acquire(),
                timeout=timeout
            )
            # Update atomic counter (thread-safe)
            async with self._counter_lock:
                self._active_analysis_count += 1

            logger.debug(
                "analysis_slot_acquired",
                available=self.get_available_slots(),
                active=self.get_active_analysis_count(),
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "analysis_slot_timeout",
                timeout=timeout,
            )
            return False

    async def release_analysis_slot_async(self) -> None:
        """Release an analysis slot (async version - preferred)."""
        if self._analysis_semaphore:
            self._analysis_semaphore.release()
            # Update atomic counter (thread-safe)
            async with self._counter_lock:
                self._active_analysis_count = max(0, self._active_analysis_count - 1)

            logger.debug(
                "analysis_slot_released",
                available=self.get_available_slots(),
                active=self.get_active_analysis_count(),
            )

    def release_analysis_slot(self) -> None:
        """Release an analysis slot (sync version for backward compatibility)."""
        if self._analysis_semaphore:
            self._analysis_semaphore.release()
            # Note: Counter update is not thread-safe in sync version
            # Use release_analysis_slot_async() for thread-safe operations
            self._active_analysis_count = max(0, self._active_analysis_count - 1)
            logger.debug(
                "analysis_slot_released",
                available=self.get_available_slots(),
            )

    def get_active_analysis_count(self) -> int:
        """Get number of active analyses (thread-safe)."""
        return self._active_analysis_count

    def get_available_slots(self) -> int:
        """Get number of available analysis slots (thread-safe)."""
        return MAX_CONCURRENT_ANALYSES - self._active_analysis_count

    # -------------------------------------------
    # Statistics
    # -------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """Get session manager statistics."""
        await self.initialize()

        session_counts = {
            "running": 0,
            "completed": 0,
            "error": 0,
            "awaiting_approval": 0,
            "cancelled": 0,
        }

        market_counts = {
            "stock": 0,
            "coin": 0,
            "kiwoom": 0,
        }

        for session in self._sessions.values():
            status_key = session.status.value if isinstance(session.status, SessionStatus) else session.status
            if status_key in session_counts:
                session_counts[status_key] += 1

            market_key = session.market_type.value if isinstance(session.market_type, MarketType) else session.market_type
            if market_key in market_counts:
                market_counts[market_key] += 1

        return {
            "max_concurrent": MAX_CONCURRENT_ANALYSES,
            "active_slots": self.get_active_analysis_count(),
            "available_slots": self.get_available_slots(),
            "total_sessions": len(self._sessions),
            "session_counts": session_counts,
            "market_counts": market_counts,
        }

    # -------------------------------------------
    # WebSocket Subscription Support
    # -------------------------------------------

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """Subscribe to session updates."""
        await self.initialize()

        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = set()
            self._subscribers[session_id].add(queue)

        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from session updates."""
        async with self._lock:
            if session_id in self._subscribers:
                self._subscribers[session_id].discard(queue)
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]

    async def _notify_subscribers(self, session_id: str, message: Dict[str, Any]) -> None:
        """Notify all subscribers of a session update.

        Queues are bounded; on overflow we drop the OLDEST buffered message and keep
        the newest (realtime favors the latest state) so a slow/dead socket cannot
        accumulate or lose the most recent update.
        """
        if session_id in self._subscribers:
            for queue in list(self._subscribers[session_id]):
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()  # drop oldest
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        queue.put_nowait(message)
                    except asyncio.QueueFull:
                        pass  # give up this one (should not happen after a drop)


# -------------------------------------------
# Singleton Instance
# -------------------------------------------

_session_manager: Optional[SessionManager] = None
_manager_lock = asyncio.Lock()


async def get_session_manager() -> SessionManager:
    """Get or create the session manager singleton."""
    global _session_manager

    if _session_manager is None:
        async with _manager_lock:
            if _session_manager is None:
                _session_manager = SessionManager()
                await _session_manager.initialize()

    return _session_manager


# -------------------------------------------
# Background Cleanup Task
# -------------------------------------------

async def run_session_cleanup_task() -> None:
    """
    Run periodic session cleanup.

    Should be started as a background task on server startup.
    """
    logger.info("session_cleanup_task_started", ttl_hours=COMPLETED_SESSION_TTL.total_seconds() / 3600)

    while True:
        try:
            manager = await get_session_manager()
            await manager.cleanup_expired_sessions()
        except Exception as e:
            logger.error("session_cleanup_error", error=str(e))

        await asyncio.sleep(300)  # Run every 5 minutes


# -------------------------------------------
# Best-effort Producer Mirrors
# -------------------------------------------
# Producers write the legacy per-market dicts FIRST (still the read path), then
# mirror to the SessionManager so its pub/sub notifies WebSocket subscribers.
# The mirror must never break the producer: any failure is logged and swallowed
# (the WS degrades to its poll fallback). No-ops for sessions not tracked in sm.


async def mirror_session_state(
    session_id: str,
    state_updates: Dict[str, Any],
    last_node: Optional[str] = None,
) -> None:
    """Best-effort state mirror (fires a state_update notification)."""
    try:
        manager = await get_session_manager()
        await manager.update_state(session_id, state_updates, last_node=last_node)
    except Exception as e:
        logger.warning(
            "sm_state_mirror_failed",
            session_id=session_id,
            error=str(e),
        )


async def mirror_session_status(
    session_id: str,
    status: "SessionStatus | str",
    error: Optional[str] = None,
) -> None:
    """Best-effort status mirror (fires a status notification)."""
    try:
        manager = await get_session_manager()
        st = status if isinstance(status, SessionStatus) else SessionStatus(status)
        await manager.update_status(session_id, st, error=error)
    except Exception as e:
        logger.warning(
            "sm_status_mirror_failed",
            session_id=session_id,
            error=str(e),
        )


async def mirror_session_removal(session_id: str) -> None:
    """Best-effort removal mirror (keeps sm from serving deleted sessions)."""
    try:
        manager = await get_session_manager()
        await manager.remove_session(session_id)
    except Exception as e:
        logger.warning(
            "sm_removal_mirror_failed",
            session_id=session_id,
            error=str(e),
        )


# -------------------------------------------
# Convenience Functions (Backward Compatibility)
# -------------------------------------------

async def register_session(
    session_id: str,
    market_type: str,
    ticker: str,
    display_name: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Register a new session (backward compatible wrapper).

    Matches the signature of analysis_limiter.register_session().
    """
    manager = await get_session_manager()

    # Convert string market_type to enum
    try:
        mt = MarketType(market_type)
    except ValueError:
        mt = MarketType.STOCK

    session = await manager.create_session(
        session_id=session_id,
        market_type=mt,
        ticker=ticker,
        display_name=display_name or ticker,
        **kwargs,
    )

    return session.to_legacy_dict()


async def update_session_status(
    session_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update session status (backward compatible wrapper)."""
    manager = await get_session_manager()

    try:
        st = SessionStatus(status)
    except ValueError:
        st = SessionStatus.RUNNING

    await manager.update_status(session_id, st, error)


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session (backward compatible wrapper)."""
    manager = await get_session_manager()
    return await manager.get_session_dict(session_id)


async def remove_session(session_id: str) -> None:
    """Remove session (backward compatible wrapper)."""
    manager = await get_session_manager()
    await manager.remove_session(session_id)


async def get_all_sessions() -> Dict[str, Dict[str, Any]]:
    """Get all sessions (backward compatible wrapper)."""
    manager = await get_session_manager()
    return await manager.get_sessions_dict()


async def get_sessions_by_market(market_type: str) -> Dict[str, Dict[str, Any]]:
    """Get sessions by market type."""
    manager = await get_session_manager()

    try:
        mt = MarketType(market_type)
    except ValueError:
        return {}

    return await manager.get_sessions_dict(market_type=mt)


async def acquire_analysis_slot(timeout: float = 60.0) -> bool:
    """Acquire analysis slot (backward compatible wrapper)."""
    manager = await get_session_manager()
    return await manager.acquire_analysis_slot(timeout)


def release_analysis_slot() -> None:
    """Release analysis slot (backward compatible wrapper)."""
    if _session_manager:
        _session_manager.release_analysis_slot()


def get_active_analysis_count() -> int:
    """Get active analysis count (backward compatible wrapper)."""
    if _session_manager:
        return _session_manager.get_active_analysis_count()
    return 0


def get_available_slots() -> int:
    """Get available slots (backward compatible wrapper)."""
    if _session_manager:
        return _session_manager.get_available_slots()
    return MAX_CONCURRENT_ANALYSES


async def get_analysis_stats() -> Dict[str, Any]:
    """Get analysis stats (backward compatible wrapper)."""
    manager = await get_session_manager()
    return await manager.get_stats()
