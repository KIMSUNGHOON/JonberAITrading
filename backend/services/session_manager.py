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

# P4-1 (session-SSOT): the SessionManager store is about to gain a second
# producer (P4-2's agent-chat discussion sessions) sharing the exact same
# `analysis_sessions` table. `kind` distinguishes the two so market-wide
# scans (ticker dedup, /operations, /pending, autonomy rearm) keep seeing
# ONLY the analysis-pipeline sessions they were built for -- a discussion
# session must never be absorbed as a dedup "duplicate" of a real analysis
# run, nor show up as a ghost card on the operations board. Every existing
# session (and every caller that doesn't pass `kind` explicitly) defaults to
# this value, so today's behavior is byte-identical after this change.
KIND_ANALYSIS = "analysis"
# P4-5: the discussion producer's kind value (services/agent_chat/
# coordinator.py's _register_sm_discussion writes kind="discussion" as a
# literal today) -- named here too so reconcile_stranded_sessions'
# kind-aware branch has a single source of truth instead of a second
# hardcoded literal.
KIND_DISCUSSION = "discussion"

# state_updates keys that can hide an "invisible interrupt" (P1 spec Sec.P1) if
# their SQLite write is delayed -- a session parked awaiting approval that a
# restart-time reload wouldn't see yet. update_state() flushes synchronously
# whenever a state_update touches one of these; every other key is debounced
# (see _FLUSH_DEBOUNCE_SECONDS, P2-1).
_CRITICAL_STATE_KEYS = {"awaiting_approval", "trade_proposal", "approval_status", "auto_approve_at"}
# Debounce window for non-critical state_update flushes (P2-1).
_FLUSH_DEBOUNCE_SECONDS = 1.0


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
    # P4-1: which producer this session belongs to -- "analysis" (default,
    # today's only value) vs. e.g. a future "discussion" kind. Global scans
    # filter on this so non-analysis producers sharing this store can never
    # pollute analysis-only consumers.
    kind: str = KIND_ANALYSIS
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
            "kind": self.kind,
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

        # P2-1: debounced-flush bookkeeping for update_state's non-critical
        # path. _dirty holds session_ids with an in-memory update that has
        # not yet been written to SQLite; _flush_task is the single
        # in-flight debounce timer (never more than one at a time).
        self._dirty: Set[str] = set()
        self._flush_task: Optional[asyncio.Task] = None

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
                        korean_name TEXT,
                        kind TEXT NOT NULL DEFAULT 'analysis'
                    )
                """)

                # P4-1: this project has no migration mechanism -- a column
                # added to the schema after a DB file was first created only
                # ever appears on that file via this ALTER path (see
                # _ensure_columns; ported from services/storage_service.py's
                # helper of the same name/pattern). Kept nullable here even
                # though the CREATE TABLE above defaults new rows to
                # 'analysis' -- SQLite ADD COLUMN cannot backfill existing
                # rows with a caller-supplied default via this helper, so old
                # rows land NULL and _row_to_session() falls back to
                # KIND_ANALYSIS when reading them back.
                await self._ensure_columns(db, "analysis_sessions", {"kind": "TEXT"})

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
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_kind
                    ON analysis_sessions(kind)
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

    @staticmethod
    async def _ensure_columns(
        db: "aiosqlite.Connection", table: str, cols: Dict[str, str]
    ) -> None:
        """Add any of `cols` missing from `table` via ALTER TABLE ADD COLUMN.

        Ported from services/storage_service.py's `_ensure_columns` (same
        name, same contract) -- this project has no migration mechanism, so
        a column added to the schema after a DB file was first created only
        ever appears on that file via this ALTER path on the next
        initialize(). Every column added this way must be nullable (no
        DEFAULT/NOT NULL requirement), since SQLite's ADD COLUMN cannot
        backfill existing rows with anything but a constant.
        """
        cursor = await db.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, col_type in cols.items():
            if name not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

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
            kind=row["kind"] or KIND_ANALYSIS,
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

        Rules (see specs/.../task-1-brief.md for the full shape table). All
        rules below apply to kind="analysis" sessions only (P4-5); a
        kind="discussion" session is handled by its own, separate rule
        first (see the dedicated branch in the loop below): any
        non-terminal status -> CANCELLED with an explicit state marker,
        since a discussion's ChatRoom lives only in-process and nothing
        survives a restart to resume it.
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

            if s.kind == KIND_DISCUSSION:
                # P4-5 (session-ssot): discussion rows never carry a
                # trade_proposal/awaiting_approval HITL shape -- none of the
                # analysis-only branches below (awaiting-flip, 6h staleness,
                # checkpoint verification, approved-mismatch) apply to them,
                # so they get their own, much simpler rule instead of
                # falling into the generic "RUNNING, no proposal" -> ERROR
                # branch (which used to mislabel a stranded discussion with
                # an analysis-flavored reason, "서버 재시작으로 분석 중단",
                # even though it's harmless -- P4-1's kind filters already
                # keep it out of every analysis-only consumer).
                #
                # A discussion's ChatRoom lives only in-process
                # (coordinator._active_rooms); nothing survives a restart to
                # resume it, so any non-terminal row found here (RUNNING is
                # the expected shape; AWAITING_APPROVAL/ERROR should never
                # happen -- _register_sm_discussion's status map only ever
                # writes RUNNING/COMPLETED/CANCELLED) unconditionally
                # resolves to CANCELLED with an explicit marker -- never
                # ERROR (that vocabulary means "an analysis proposal HITL is
                # stuck", which is not this).
                #
                # Seam for P5-1: like every other branch in this loop, this
                # assigns s.status/state directly rather than going through
                # update_status/update_state -- when P5-1 adds lifecycle
                # hooks on those methods, this branch is in scope for
                # whatever shim/replay it needs to cover reconcile's direct
                # writes too.
                if s.status in (
                    SessionStatus.COMPLETED,
                    SessionStatus.CANCELLED,
                    SessionStatus.ERROR,
                ):
                    rep.kept.append(sid)
                else:
                    if s.status != SessionStatus.RUNNING:
                        logger.warning(
                            "discussion_reconcile_unexpected_status",
                            session_id=sid,
                            status=s.status.value,
                        )
                    s.status = SessionStatus.CANCELLED
                    st["cancelled_reason"] = "재시작으로 토론 중단"
                    st["sub_status"] = "cancelled"
                    rep.cancelled.append(sid)

            elif s.status == SessionStatus.RUNNING and awaiting and prop:
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
        kind: str = KIND_ANALYSIS,
        **kwargs,
    ) -> AnalysisSession:
        """
        Create a new analysis session.

        Args:
            session_id: Unique session identifier
            market_type: Type of market (stock, coin, kiwoom)
            ticker: Stock/coin code
            display_name: Human-readable name
            kind: Session producer kind (P4-1) -- defaults to "analysis" so
                every existing caller is unaffected.
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
            kind=kind,
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

    async def create_session_if_no_active(
        self,
        session_id: str,
        market_type: MarketType,
        ticker: str,
        display_name: str,
        kind: str = KIND_ANALYSIS,
        **kwargs,
    ) -> tuple[Optional[AnalysisSession], Optional[AnalysisSession]]:
        """
        Atomically reserve a session_id for (market_type, ticker) iff no
        other session for that same pair is currently RUNNING or
        AWAITING_APPROVAL.

        This collapses the check-then-create race that a separate
        "is there an active session for this ticker?" read followed by a
        plain create_session() call would have: two callers racing to open
        analysis on the same ticker could otherwise both observe "no active
        session" and both create one. Holding self._lock across the check
        AND the create closes that window.

        Args:
            session_id: Unique session identifier for the NEW session (only
                used if no active session for the ticker exists).
            market_type: Type of market (stock, coin, kiwoom)
            ticker: Stock/coin code
            display_name: Human-readable name
            kind: Session producer kind (P4-1) -- defaults to "analysis".
                The active-collision check below only ever compares
                candidates of the SAME kind, so a reservation for one kind
                (e.g. a future "discussion" producer) can never collide with
                -- or be blocked by -- an active session of a different kind
                for the same (market_type, ticker).
            **kwargs: Additional fields (stk_cd, stk_nm, market, korean_name, state)

        Returns:
            (created, existing) -- exactly one is None. `created` is the
            newly reserved AnalysisSession when no collision was found;
            `existing` is the already-active session blocking the
            reservation otherwise.
        """
        await self.initialize()

        async with self._lock:
            for candidate in self._sessions.values():
                if candidate.market_type != market_type:
                    continue
                if candidate.kind != kind:
                    continue
                candidate_ticker = candidate.stk_cd or candidate.market or candidate.ticker
                if candidate_ticker != ticker:
                    continue
                if candidate.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL):
                    return None, candidate

            # NOTE: do NOT call self.create_session() here -- it re-acquires
            # self._lock (not reentrant) and would deadlock. Construct and
            # persist the session directly instead (mirrors create_session's
            # body).
            session = AnalysisSession(
                session_id=session_id,
                market_type=market_type,
                ticker=ticker,
                display_name=display_name,
                kind=kind,
                stk_cd=kwargs.get("stk_cd"),
                stk_nm=kwargs.get("stk_nm"),
                market=kwargs.get("market"),
                korean_name=kwargs.get("korean_name"),
                state=kwargs.get("state", {}),
            )
            self._sessions[session_id] = session
            await self._save_session(session)

        logger.info(
            "session_reserved",
            session_id=session_id,
            market_type=market_type.value,
            ticker=ticker,
        )

        return session, None

    async def _save_session(self, session: AnalysisSession) -> None:
        """Save session to SQLite."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO analysis_sessions
                (session_id, market_type, ticker, display_name, status,
                 created_at, updated_at, error, last_node, state_json,
                 stk_cd, stk_nm, market, korean_name, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                session.kind,
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
        """
        Update session status. Always flushed to SQLite immediately (never
        debounced) -- a status transition is exactly the kind of change the
        P1 "invisible interrupt" guard exists for.

        Raises:
            KeyError: session_id is not tracked by this SessionManager
                (fail-loud -- P2-1 retired the previous silent no-op).
        """
        await self.initialize()

        async with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"session {session_id} not tracked by SessionManager")

            session = self._sessions[session_id]
            session.status = status
            session.updated_at = datetime.now(timezone.utc)
            if error:
                session.error = error

            self._dirty.discard(session_id)
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
        """
        Update session state.

        SQLite write policy (P2-1): if `state_updates` touches any key in
        _CRITICAL_STATE_KEYS, this flushes to SQLite synchronously before
        returning -- those keys are how an "invisible interrupt" (P1 spec
        Sec.P1) could otherwise hide. Everything else (reasoning-log entries,
        stage/progress chatter) is coalesced instead: the session is marked
        dirty and a single debounced flush task (per-manager, ~1s) writes
        every dirty session once and clears the set, so a burst of
        non-critical updates costs one SQLite write instead of N.

        Durability trade-off: a process crash inside the debounce window
        loses at most the last ~1s of non-critical state. This is accepted
        by design -- the next critical-key update or status transition
        flushes synchronously anyway, so THAT is the durability point that
        actually matters, not every reasoning-log line.

        Pub/sub notification is never debounced: both the critical and
        non-critical paths call _notify_subscribers immediately after the
        in-memory update, so WebSocket subscribers see live-latency updates
        regardless of the SQLite write policy.

        Raises:
            KeyError: session_id is not tracked by this SessionManager
                (fail-loud -- P2-1 retired the previous silent no-op).
        """
        await self.initialize()

        async with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"session {session_id} not tracked by SessionManager")

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

            if set(state_updates.keys()) & _CRITICAL_STATE_KEYS:
                self._dirty.discard(session_id)
                await self._save_session(session)
            else:
                self._dirty.add(session_id)
                self._schedule_dirty_flush()

            payload: Dict[str, Any] = {
                "type": "state_update",
                "updates": list(state_updates.keys()),
            }
            if last_node:
                payload["last_node"] = last_node
            if reasoning_delta:
                payload["reasoning_delta"] = reasoning_delta
            await self._notify_subscribers(session_id, payload)

    def _schedule_dirty_flush(self) -> None:
        """
        Arm the debounced flush task if one is not already pending.

        Must be called while holding self._lock (update_state's caller
        already does). Safe to call from inside the lock even though the
        task itself also acquires self._lock: create_task() only schedules
        the coroutine, it does not start running it -- by the time
        _flush_dirty_after_delay actually reaches its `async with
        self._lock:`, this call's own `async with self._lock:` block (in
        update_state) has long since exited and released it (the task
        sleeps _FLUSH_DEBOUNCE_SECONDS first).
        """
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._flush_dirty_after_delay())

    async def _flush_dirty_after_delay(self) -> None:
        """Debounced SQLite flush for update_state's non-critical path.

        If cancelled (e.g. by a caller tearing the manager down) or if the
        process exits during the sleep, the pending writes are simply lost
        -- accepted per update_state's durability trade-off docstring.
        """
        await asyncio.sleep(_FLUSH_DEBOUNCE_SECONDS)
        async with self._lock:
            dirty_ids = list(self._dirty)
            self._dirty.clear()
            for sid in dirty_ids:
                session = self._sessions.get(sid)
                if session is not None:
                    await self._save_session(session)

    async def get_all_sessions(
        self,
        market_type: Optional[MarketType] = None,
        status: Optional[SessionStatus] = None,
        kind: Optional[str] = None,
    ) -> Dict[str, AnalysisSession]:
        """
        Get all sessions, optionally filtered.

        Args:
            market_type: Filter by market type
            status: Filter by status
            kind: Filter by session producer kind (P4-1). None (default) is
                unfiltered -- every existing caller that doesn't pass this
                keeps seeing every kind, preserving current behavior.

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
            if kind and session.kind != kind:
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
                # P2-1: a debounced flush must not resurrect/overwrite a
                # session that was removed before its 1s window fired.
                self._dirty.discard(session_id)

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
                # P2-1: same reasoning as remove_session -- don't let a
                # debounced flush write back an expired-and-deleted session.
                self._dirty.discard(session_id)

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
# Write-through Commits (Awaiting-critical Transitions)
# -------------------------------------------
# Unlike the mirror_* helpers above, these RAISE on any failure — including
# the session not being tracked by the SessionManager at all. Reserved for
# transitions where a swallowed failure would create an "invisible interrupt"
# (P1, spec §P1): a session parked awaiting approval that no read surface can
# see, because C-only reads mean the SessionManager IS the read path. Callers
# are expected to fail closed (see kr_stocks/analysis.py
# _finalize_awaiting_transition and app/api/routes/approval.py).


async def commit_session_status(
    session_id: str,
    status: "SessionStatus",
    *,
    error: Optional[str] = None,
) -> None:
    """
    Write-through variant of mirror_session_status for awaiting-critical
    transitions (P1, spec §P1): raises on ANY failure — including the session
    not being tracked — instead of swallowing. Callers fail closed.
    """
    manager = await get_session_manager()
    if await manager.get_session(session_id) is None:
        raise KeyError(f"session {session_id} not tracked by SessionManager")
    await manager.update_status(session_id, status, error=error)


async def commit_session_state(
    session_id: str,
    state_updates: Dict[str, Any],
    *,
    last_node: Optional[str] = None,
) -> None:
    """Write-through variant of mirror_session_state — raises on failure."""
    manager = await get_session_manager()
    if await manager.get_session(session_id) is None:
        raise KeyError(f"session {session_id} not tracked by SessionManager")
    await manager.update_state(session_id, state_updates, last_node=last_node)


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
