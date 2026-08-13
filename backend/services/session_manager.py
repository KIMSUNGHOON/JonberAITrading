"""
Unified Session Manager Service

Provides centralized session management for Korean Stock analysis (Kiwoom).

Features:
- Single source of truth for all sessions
- Thread-safe with asyncio.Lock
- SQLite persistence for recovery after restart
- Automatic cleanup of expired sessions
- Market-type based filtering
- WebSocket integration support

Session Types:
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

# P5-1 (session-ssot): checkpoint GC hook needs the storage service's
# delete_checkpoints(). services/storage_service.py has zero intra-repo
# imports of its own (stdlib + aiosqlite + structlog only), so importing it
# here at module scope cannot form an import cycle back into this module.
from services.storage_service import get_storage_service

logger = structlog.get_logger()


# -------------------------------------------
# Configuration
# -------------------------------------------

MAX_CONCURRENT_ANALYSES = 3
COMPLETED_SESSION_TTL = timedelta(hours=1)
# P5-2 (session-ssot): grace period for the orphan-checkpoint sweep
# (SessionManager._sweep_orphan_checkpoints) -- a checkpoint whose owning
# session_id is missing from sessions.db or terminal is only reclaimed once
# its OWN last-write timestamp (checkpoints.created_at -- see
# storage_service.get_checkpoint_session_ids' docstring for why that column
# already tracks this with no schema change) is older than this window.
# Deliberately longer than COMPLETED_SESSION_TTL: a checkpoint is the
# graph's resume state, so this sweep is the more conservative of the two
# P5-2 backstops -- it must never race a legitimate resume that a
# transient failure (e.g. a delayed _on_terminal_transition retry, or a
# brief storage.db lock contention) merely delayed the SM-side row update
# for.
CHECKPOINT_ORPHAN_GRACE = timedelta(hours=24)
# P5-2 review fix: SQLite has a hard cap on host parameters per statement
# (999 pre-3.32.0, 32766 from 3.32.0 on). Both P5-2 sweeps below build a
# `session_id IN (...)` clause with one placeholder per candidate -- at the
# backlog scale these sweeps exist to reclaim (612MB/1GB, potentially many
# thousands of rows), an unbounded IN clause can exceed that cap, raise
# "too many SQL variables", and get swallowed by the sweep's own best-effort
# except -- turning "reclaim what's due" into a silent full no-op every
# cycle. Both `_sweep_terminal_session_rows` and `_sweep_orphan_checkpoints`
# chunk their IN-clause candidate lists to this size via `_chunked` below;
# each chunk executes and fails independently (see both methods'
# docstrings), so one oversized/unlucky batch can never block the rest.
_SWEEP_IN_CLAUSE_CHUNK_SIZE = 500
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
    KIWOOM = "kiwoom"    # Korean stocks (Kiwoom)


class SessionStatus(str, Enum):
    """Session lifecycle statuses."""
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


# P5-1 (session-ssot): statuses a session can never leave once entered --
# no code path resumes a COMPLETED/ERROR/CANCELLED session back to
# RUNNING/AWAITING_APPROVAL. Every transition INTO one of these is exactly
# the trigger for SessionManager._on_terminal_transition's checkpoint GC
# (AWAITING_APPROVAL is deliberately excluded: a resume still needs its
# checkpoint row).
_TERMINAL_STATUSES = {
    SessionStatus.COMPLETED,
    SessionStatus.ERROR,
    SessionStatus.CANCELLED,
}


@dataclass
class AnalysisSession:
    """
    Unified session data structure for all analysis types.

    This replaces the separate dicts in analysis.py, kr_stocks.py (and,
    before its 2026-08-01 removal, coin.py).
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
    # 코인 스택 제거(2026-08-01) 이후 신규로 채워지지 않는 휴면 필드다 --
    # SQLite 컬럼·스키마 정리는 Task 4(저장소 배선) 몫이라 여기서는 필드
    # 자체는 남긴다.
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

        Matches the format used by existing routes (analysis.py, kr_stocks.py,
        and — before its 2026-08-01 removal — coin.py).
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

        if self.market_type == MarketType.KIWOOM:
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


def _chunked(items: List[str], size: int) -> List[List[str]]:
    """Split `items` into consecutive sub-lists of at most `size` each.

    P5-2 review fix: backs the IN-clause batching in
    `_sweep_terminal_session_rows`/`_sweep_orphan_checkpoints` (see
    `_SWEEP_IN_CLAUSE_CHUNK_SIZE`'s module comment). Order-preserving,
    no dedup -- a plain positional slice.
    """
    return [items[i : i + size] for i in range(0, len(items), size)]


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

        # P5-1 review fix: reconcile_stranded_sessions() runs with
        # fire_hooks=False below (it executes INSIDE the async with
        # self._lock: block, non-reentrantly, on behalf of this method --
        # see the NOTE at the call site) so its checkpoint-GC hooks can be
        # fired from out here, AFTER the lock is released, instead of
        # while it's held. Stays None if this call hits the early-return-
        # inside-the-lock race below (another caller already initialized).
        reconcile_report: Optional["ReconcileReport"] = None

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
            # P5-1 review fix: fire_hooks=False -- this call runs while
            # self._lock is held (by this very block, non-reentrantly).
            # The terminal-transition checkpoint-GC hooks it would
            # otherwise fire per-branch are fired below instead, AFTER the
            # lock is released.
            reconcile_report = await self.reconcile_stranded_sessions(fire_hooks=False)

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

        # P5-1 review fix: fire checkpoint GC hooks for reconcile's
        # terminal transitions AFTER self._lock is released above (never
        # while the SM lock is held -- storage.db I/O contending with a
        # live graph's checkpoint writes could otherwise stall every SM
        # reader/writer for up to its busy-timeout window). `errored` and
        # `cancelled` never overlap (each sid lands in exactly one
        # ReconcileReport list per reconcile pass), the union just avoids
        # assuming that invariant here too.
        if reconcile_report is not None:
            for sid in set(reconcile_report.errored) | set(reconcile_report.cancelled):
                await self._on_terminal_transition(sid)

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

        try:
            market_type = MarketType(row["market_type"])
        except ValueError:
            # 코인 스택 제거(2026-08-01) 이후 KIWOOM만 유효하다 -- 동결 이전에
            # 만들어진 "coin"/"stock" 행이 sessions.db에 남아 있으면 (드물지만
            # RUNNING/AWAITING_APPROVAL 상태로 재시작을 맞을 수 있다) 여기서
            # 예외를 던지는 대신 원본 문자열을 그대로 보존한다. 이 메서드는
            # _load_active_sessions()를 통해 **매 재시작마다** 호출되므로,
            # 여기서 죽으면 KIWOOM 세션까지 통째로 로드에 실패한다 -- 다른
            # 곳(to_dict/to_legacy_dict/시장 필터 비교)이 이미
            # isinstance(x, MarketType) 방어 패턴을 쓰고 있어 원본 문자열도
            # 안전하게 흘러간다(문자열 Enum 비교라 != 필터링도 그대로 동작).
            # 이 폴백은 조용하면 "세션이 운영 보드에서 소리 없이 사라졌다"로만
            # 보이므로, 진단 가능하도록 경고 로그를 남긴다.
            logger.warning(
                "session_row_market_type_unparsed",
                session_id=row["session_id"],
                raw=row["market_type"],
            )
            market_type = row["market_type"]

        return AnalysisSession(
            session_id=row["session_id"],
            market_type=market_type,
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
        fire_hooks: bool = True,
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
            fire_hooks: P5-1 review fix. When True (default -- the shape
                every direct caller, including tests, gets), each
                ERROR/CANCELLED direct-assignment branch below fires
                `_on_terminal_transition` for its own sid immediately, same
                as before. initialize() passes False, because it calls this
                method from INSIDE its own `async with self._lock:` block
                (see the locking note above) -- storage.db I/O must never
                run while self._lock is held (an SM-wide freeze risk if it
                contends with a live graph's checkpoint writes under
                SQLite's busy-timeout). With fire_hooks=False, initialize()
                is responsible for firing the hook itself, for every sid in
                the returned report's `errored`/`cancelled` lists, AFTER
                releasing the lock.

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
            # P5-1: set True at the exact branch below that appends this
            # sid to rep.errored/rep.cancelled -- an O(1) per-iteration flag
            # instead of the `sid in rep.errored or sid in rep.cancelled`
            # membership scan this replaced (that scan was O(n) against
            # lists that grow across iterations, i.e. O(n^2) overall).
            terminal_now = False

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
                    terminal_now = True

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
                    # Final-review fix (Minor 2, session-ssot): clear the
                    # awaiting flag alongside the status flip. Before this,
                    # `st["awaiting_approval"]` (True, per this branch's own
                    # `awaiting` guard above) survived the ERROR flip
                    # untouched, and /approval/pending's predicate
                    # (`state.get("awaiting_approval")` truthy -- see
                    # app/api/routes/approval.py::list_pending_approvals,
                    # deliberately status-blind, D3 semantics preserved
                    # here) would keep listing this now-terminal session as
                    # an actionable pending approval for up to
                    # COMPLETED_SESSION_TTL (~5min, self-healing once
                    # cleanup_expired_sessions reaps the row). Clearing the
                    # flag here closes that ghost window at the source
                    # instead of teaching every reader to also check status
                    # -- consumers that already do both (e.g. websocket.py's
                    # proposal-resend gate) are unaffected: the flag is now
                    # simply False, same net effect for them, one fewer
                    # stale-looking read for everyone else (e.g.
                    # /approval/pending, /approval/pending/{id}).
                    st["awaiting_approval"] = False
                    rep.errored.append(sid)
                    terminal_now = True
                else:
                    s.status = SessionStatus.AWAITING_APPROVAL
                    st["approval_status"] = None  # new decision must overwrite, not be shadowed
                    rep.flipped.append(sid)

            elif s.status == SessionStatus.RUNNING:
                s.status = SessionStatus.ERROR
                s.error = "서버 재시작으로 분석 중단"
                rep.errored.append(sid)
                terminal_now = True

            elif (
                s.status == SessionStatus.AWAITING_APPROVAL
                and not awaiting
                and appr == "approved"
            ):
                s.status = SessionStatus.ERROR
                s.error = "실행 중단 — 체결 확인 필요"
                rep.errored.append(sid)
                terminal_now = True

            elif s.status == SessionStatus.AWAITING_APPROVAL and appr == "cancelled":
                s.status = SessionStatus.CANCELLED
                rep.cancelled.append(sid)
                terminal_now = True

            else:
                rep.kept.append(sid)

            if sid in rep.flipped or terminal_now or changed_common:
                s.updated_at = now
                await self._save_session(s)

            # P5-1 (review fix): reconcile assigns terminal statuses
            # directly (bypassing update_status, which is where the hook
            # normally lives) across several branches above -- the analysis
            # ERROR/CANCELLED flips AND the discussion-kind CANCELLED
            # branch. `terminal_now` is set at the exact branch that made
            # THIS sid terminal this iteration (never for rep.flipped --
            # that's AWAITING_APPROVAL, a resumable session that must keep
            # its checkpoint). Gated on fire_hooks: initialize() calls this
            # method while self._lock is held and passes fire_hooks=False
            # so it can fire these itself after releasing the lock instead
            # (see initialize() and this method's fire_hooks docstring).
            if fire_hooks and terminal_now:
                await self._on_terminal_transition(sid)

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
            market_type: Type of market (kiwoom)
            ticker: Stock code
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
            market_type: Type of market (kiwoom)
            ticker: Stock code
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

    async def _on_terminal_transition(self, session_id: str) -> None:
        """
        Best-effort LangGraph checkpoint GC hook (P5-1, spec Sec.P5 rule 3).

        Fired whenever a session's status BECOMES COMPLETED/ERROR/CANCELLED.
        The checkpoints table (services/storage_service.py) is the graph's
        resume state -- a terminal session will never resume from it again,
        so its rows are pure leak once the session lands here. Never fired
        for AWAITING_APPROVAL (or any non-terminal status): a resume still
        needs that checkpoint.

        Best-effort by design: `delete_checkpoints` already swallows its own
        DB errors internally (returns False), but this also guards against
        get_storage_service() itself raising (e.g. mid-initialize). Any
        failure here must never turn an already-persisted status transition
        into a caller-visible error -- P5-2's periodic sweep is the
        backstop that reclaims whatever this call missed.

        Idempotent / kind-agnostic: calling this twice for the same
        session_id, or for a kind="discussion" session that never had any
        checkpoint rows, is simply a 0-row DELETE both times -- no dedup or
        kind check needed here.
        """
        try:
            storage = await get_storage_service()
            await storage.delete_checkpoints(session_id)
        except Exception as e:
            logger.warning(
                "checkpoint_gc_failed",
                session_id=session_id,
                error=str(e),
            )

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

        fire_gc = False
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

            fire_gc = status in _TERMINAL_STATUSES

        # P5-1 (review fix): fire the checkpoint GC hook only AFTER the
        # transition is durably persisted above AND self._lock is released
        # -- storage.db I/O must never run while the SM lock is held (an
        # SM-wide freeze risk if it contends with a live graph's checkpoint
        # writes under SQLite's busy-timeout). No race from deferring past
        # the lock: the session is already terminal in both memory and
        # SQLite by the time we get here, so nothing else can be racing to
        # resume it out from under this call.
        if fire_gc:
            await self._on_terminal_transition(session_id)

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

        removed = False
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
                removed = True

        if removed:
            # P5-1 (review fix): the session row (and any resume path to
            # it) is gone unconditionally at this point regardless of what
            # status it was removed in -- GC its checkpoint rows too, so
            # removal can never leave an orphan behind for a session_id
            # nothing can look up again. Fired AFTER self._lock is released
            # (never while held -- see update_status for the same rationale
            # spelled out in full); no race, the row is already gone from
            # both memory and SQLite by the time we get here.
            await self._on_terminal_transition(session_id)

        return removed

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

        # P5-1 (review fix): every id in `expired` was filtered to a
        # terminal status above (COMPLETED/ERROR/CANCELLED) before being
        # queued for deletion -- GC each one's checkpoint rows now that the
        # row itself is gone. Fired AFTER self._lock is released (never
        # while held -- see update_status for the full rationale); this was
        # the worst-case site for the lock-held-I/O risk, since it can do N
        # sequential DELETEs under a single lock acquisition.
        for session_id in expired:
            await self._on_terminal_transition(session_id)

        if expired:
            logger.info(
                "sessions_cleanup_completed",
                removed_count=len(expired),
                remaining_count=len(self._sessions),
            )

        return len(expired)

    # -------------------------------------------
    # P5-2: Orphan sweeps (progressive-leak backstop)
    # -------------------------------------------
    # cleanup_expired_sessions() above only ever walks self._sessions -- the
    # in-memory dict. _load_active_sessions() (called once, from
    # initialize()) only loads RUNNING/AWAITING_APPROVAL rows back into that
    # dict on startup, by design (a terminal session has nothing left to
    # resume). The consequence: a session that reaches COMPLETED/ERROR/
    # CANCELLED and then the process restarts (or the row was written by a
    # process that has since exited) is now a sessions.db row with NO
    # in-memory representative in the new process -- cleanup_expired_
    # sessions' walk can never see it, so it would sit in sessions.db
    # forever. This is spec Sec.1.1-6's root cause for the 612MB terminal-
    # row leak. The two sweeps below are independent, direct-SQL backstops
    # that do not depend on self._sessions at all:
    #   - _sweep_terminal_session_rows: reclaims the leaked sessions.db rows
    #     themselves (same COMPLETED_SESSION_TTL boundary as the in-memory
    #     walk above, applied via direct SQL instead).
    #   - _sweep_orphan_checkpoints: reclaims storage.db checkpoint rows
    #     P5-1's best-effort _on_terminal_transition hook missed (hook
    #     failure, or a terminal transition that happened before P5-1
    #     existed) -- keyed off checkpoints' OWN last-write time, not
    #     sessions.db, so it also covers a checkpoint whose session_id row
    #     was already reclaimed by the sweep just above (or was never
    #     created in sessions.db at all).
    # Both are called periodically (not every cycle) from
    # run_session_cleanup_task -- see that function's docstring for cadence
    # rationale.

    async def _sweep_terminal_session_rows(
        self,
        now: Optional[datetime] = None,
        chunk_size: int = _SWEEP_IN_CLAUSE_CHUNK_SIZE,
    ) -> List[str]:
        """
        Direct-SQL backstop for terminal sessions.db rows that
        cleanup_expired_sessions' in-memory walk can never reach (see the
        module comment above this method).

        Runs independently of self._sessions: SELECTs every row whose
        status is terminal, filters in Python against the SAME
        COMPLETED_SESSION_TTL *duration* cleanup_expired_sessions uses --
        but anchored on `updated_at` (per spec Sec.1.1-6), NOT the SAME
        COLUMN that method anchors on (cleanup_expired_sessions compares
        `now - session.created_at`, see its body above). This is a
        deliberate, more conservative divergence, not an inconsistency:
        `updated_at >= created_at` always holds, so anchoring on
        `updated_at` can only make a row survive at least as long as --
        often longer than -- cleanup_expired_sessions' own created_at
        -anchored check would keep it. That is exactly right for THIS
        sweep's job: a session that goes terminal long after creation must
        get its own fresh TTL window measured from when it actually became
        terminal, not from when it was first created.
        (cleanup_expired_sessions' `created_at` anchor is pre-existing
        behavior, unrelated to this task and left unchanged.)

        Filtering candidates in Python instead of pushing the timestamp
        comparison into SQL avoids relying on ISO-8601 string lexicographic
        ordering being exact for every stored `updated_at` value
        (datetime.isoformat() omits the microsecond field entirely when it
        is zero, which would otherwise make that row's string sort earlier
        than a same-instant value that does have microseconds) -- mirrors
        _parse_dt's existing tolerant-parsing role elsewhere in this
        module.

        The candidate DELETE is chunked to `chunk_size` (default
        `_SWEEP_IN_CLAUSE_CHUNK_SIZE`, see its module comment for why an
        unbounded `IN (...)` is unsafe at backlog scale). Each chunk
        commits and fails independently -- a batch that raises is logged
        and skipped; its rows are simply left in place for the next cycle
        (a DELETE that never ran is always a safe no-op), and
        `deleted_ids` only ever contains rows from batches that actually
        committed, so the checkpoint-GC firing below stays accurate even
        under a partial failure. `chunk_size` is a parameter (not baked in)
        so tests can inject a small value and exercise multi-batch/
        partial-failure behavior without inserting thousands of rows.

        Any session_id this deletes is also defensively dropped from
        self._sessions/self._dirty/self._subscribers. Normally none of
        the deleted rows ARE in memory (that is exactly why they leaked --
        nothing in this process is tracking them) but a row can in
        principle be deleted here in the same process that is concurrently
        running cleanup_expired_sessions' own in-memory-tracked TTL sweep
        for the identical session_id; guarding here means whichever runs
        second is simply a no-op instead of leaving a dangling in-memory
        entry pointed at a row that no longer exists in SQLite.

        Returns the list of deleted session_ids so the caller can fire
        _on_terminal_transition (checkpoint GC) for each -- ALWAYS after
        releasing self._lock (P5-1 lock-safety pattern: storage.db I/O must
        never run while the SM lock, which serializes the entire app-wide
        session SSOT, is held).

        Best-effort: any failure at the connection/SELECT level (including
        a corrupt/unreachable DB_PATH) is logged and swallowed; whatever
        `deleted_ids` had already accumulated from earlier successful
        batches (if any) before such a failure is still processed below --
        the next periodic cycle retries only what's left.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = now - COMPLETED_SESSION_TTL
        terminal_values = tuple(s.value for s in _TERMINAL_STATUSES)

        deleted_ids: List[str] = []
        try:
            placeholders = ",".join("?" * len(terminal_values))
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    f"""
                    SELECT session_id, updated_at FROM analysis_sessions
                    WHERE status IN ({placeholders})
                    """,
                    terminal_values,
                )
                rows = await cursor.fetchall()
                candidates = [
                    sid
                    for sid, updated_at_raw in rows
                    if (_parse_dt(updated_at_raw) or now) < cutoff
                ]

                for chunk in _chunked(candidates, chunk_size):
                    try:
                        del_placeholders = ",".join("?" * len(chunk))
                        await db.execute(
                            f"DELETE FROM analysis_sessions WHERE session_id IN ({del_placeholders})",
                            chunk,
                        )
                        await db.commit()
                        deleted_ids.extend(chunk)
                    except Exception as e:
                        logger.warning(
                            "terminal_row_sweep_batch_failed",
                            batch_size=len(chunk),
                            error=str(e),
                        )
        except Exception as e:
            logger.warning("terminal_row_sweep_failed", error=str(e))
            # Fall through with whatever `deleted_ids` accumulated before
            # this outer-level failure -- their checkpoint-GC firing below
            # must still happen for rows genuinely gone from SQLite.

        if not deleted_ids:
            return []

        async with self._lock:
            for sid in deleted_ids:
                self._sessions.pop(sid, None)
                self._dirty.discard(sid)
                self._subscribers.pop(sid, None)

        # P5-1 lock-safety pattern: fire only after self._lock is released.
        for sid in deleted_ids:
            await self._on_terminal_transition(sid)

        logger.info("terminal_row_sweep_deleted", count=len(deleted_ids))
        return deleted_ids

    async def _sweep_orphan_checkpoints(
        self,
        now: Optional[datetime] = None,
        chunk_size: int = _SWEEP_IN_CLAUSE_CHUNK_SIZE,
    ) -> int:
        """
        Direct-SQL backstop for storage.db checkpoint rows P5-1's
        best-effort `_on_terminal_transition` hook missed -- a delete that
        failed (storage.db locked, disk full, process died mid-call), or
        any terminal transition that happened before P5-1 existed.

        A checkpoint row's session_id is an orphan candidate when
        sessions.db shows it is either:
          (a) absent entirely (no analysis_sessions row -- SM never
              created it, or the row was already reclaimed, e.g. by
              _sweep_terminal_session_rows above or by remove_session), or
          (b) present but in a terminal status (COMPLETED/ERROR/CANCELLED).

        ABSOLUTE INVARIANT: a session_id whose analysis_sessions row is
        RUNNING or AWAITING_APPROVAL is NEVER reclaimed, unconditionally --
        checked via a fresh SQLite read (not self._sessions, which this
        process may not have loaded that session_id into at all, e.g. a
        session created and driven to completion entirely by a different
        process instance). The status lookup is chunked (see `chunk_size`
        below) to keep this invariant safe under batching: a session_id
        whose STATUS LOOKUP failed this cycle (its batch raised) is treated
        as UNRESOLVED, not as case (a) -- it is skipped entirely, never
        deleted, because among an unresolved batch's session_ids could be
        a genuinely live RUNNING/AWAITING_APPROVAL one that this sweep
        simply failed to observe. Only a batch that resolves successfully
        (whether it returns a row or zero rows for a given session_id) can
        ever conclude "absent" (case a) or "terminal" (case b).

        Grace period: CHECKPOINT_ORPHAN_GRACE (24h), measured from the
        checkpoint's OWN last-write timestamp (storage_service.
        get_checkpoint_session_ids' MAX(created_at) per session_id -- see
        that method's docstring for why checkpoints.created_at is already,
        with no schema change, an accurate "last touched" signal). Using
        the checkpoint's own activity timestamp -- not any sessions.db
        timestamp -- means the grace period holds even for case (a), where
        sessions.db has nothing to measure from at all. This was chosen
        over the "observed twice across sweep cycles" alternative the task
        brief floated (record an in-memory sighting on pass 1, delete only
        if still orphaned on pass 2): that alternative's state resets on
        every process restart, which would silently re-arm the grace period
        for every orphan on every deploy; MAX(created_at) is already
        durable in storage.db and needs no additional bookkeeping.
        A session_id whose last-write timestamp can't be parsed is treated
        as NOT past grace (skipped, conservative) rather than assumed
        eligible.

        The status-lookup `session_id IN (...)` clause is chunked to
        `chunk_size` (default `_SWEEP_IN_CLAUSE_CHUNK_SIZE`, see its
        module comment for why an unbounded IN clause is unsafe at
        backlog scale). Each chunk resolves independently -- a batch that
        raises is logged and its session_ids are recorded as unresolved
        (see the invariant note above) rather than aborting the whole
        sweep; a connection-level failure (e.g. DB_PATH itself unreachable,
        raised before any chunk executes) still short-circuits the entire
        sweep to 0, matching this method's original all-or-nothing
        connection-failure behavior. `chunk_size` is a parameter (not
        baked in) so tests can inject a small value and exercise
        multi-batch/partial-failure behavior without inserting thousands
        of rows.

        Best-effort throughout: any failure (listing checkpoints, looking
        up statuses, or an individual delete) is logged and swallowed --
        the next periodic cycle retries. A per-session_id delete failure
        does not abort the rest of the sweep.

        Returns the count of session_ids whose checkpoints were deleted.
        """
        now = now or datetime.now(timezone.utc)

        try:
            storage = await get_storage_service()
            checkpoint_rows = await storage.get_checkpoint_session_ids()
        except Exception as e:
            logger.warning("checkpoint_orphan_sweep_list_failed", error=str(e))
            return 0

        if not checkpoint_rows:
            return 0

        status_by_sid: Dict[str, str] = {}
        unresolved_sids: Set[str] = set()
        try:
            session_ids = [sid for sid, _ in checkpoint_rows]
            async with aiosqlite.connect(DB_PATH) as db:
                for chunk in _chunked(session_ids, chunk_size):
                    try:
                        placeholders = ",".join("?" * len(chunk))
                        cursor = await db.execute(
                            f"SELECT session_id, status FROM analysis_sessions WHERE session_id IN ({placeholders})",
                            chunk,
                        )
                        for sid, status in await cursor.fetchall():
                            status_by_sid[sid] = status
                    except Exception as e:
                        logger.warning(
                            "checkpoint_orphan_sweep_status_lookup_batch_failed",
                            batch_size=len(chunk),
                            error=str(e),
                        )
                        unresolved_sids.update(chunk)
        except Exception as e:
            logger.warning("checkpoint_orphan_sweep_status_lookup_failed", error=str(e))
            return 0

        deleted = 0
        for session_id, last_written_raw in checkpoint_rows:
            if session_id in unresolved_sids:
                continue  # status lookup failed this cycle -- conservative skip, retried next cycle

            status = status_by_sid.get(session_id)
            if status in (SessionStatus.RUNNING.value, SessionStatus.AWAITING_APPROVAL.value):
                continue  # absolute invariant -- never touch a live session's checkpoint

            last_written = _parse_dt(last_written_raw)
            if last_written is None:
                continue  # can't establish grace elapsed -- conservative skip
            if (now - last_written) < CHECKPOINT_ORPHAN_GRACE:
                continue  # within grace -- leave it even if orphaned/terminal

            try:
                await storage.delete_checkpoints(session_id)
                deleted += 1
            except Exception as e:
                logger.warning(
                    "checkpoint_orphan_sweep_delete_failed",
                    session_id=session_id,
                    error=str(e),
                )

        if deleted:
            logger.info("checkpoint_orphan_sweep_deleted", count=deleted)
        return deleted

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

# P5-2: cadence for the two orphan sweeps below, expressed as a multiple
# of run_session_cleanup_task's 300s (5min) cycle -- i.e. ~1 hour. Lower
# frequency than the per-cycle in-memory TTL walk in cleanup_expired_
# sessions() on purpose: _sweep_orphan_checkpoints aggregates over the
# ENTIRE checkpoints table (GROUP BY session_id -- no index makes that
# free), so running it every 5 minutes against a live server buys nothing.
# Both sweeps' own grace/TTL windows (CHECKPOINT_ORPHAN_GRACE=24h,
# COMPLETED_SESSION_TTL=1h) already bound how stale a leaked row can get
# before a pass reclaims it -- tightening the cadence below hourly would
# not meaningfully shrink a leak's practical lifetime, only add I/O.
_ORPHAN_SWEEP_CYCLE_INTERVAL = 12


async def run_session_cleanup_task() -> None:
    """
    Run periodic session cleanup.

    Should be started as a background task on server startup.

    P5-2: every _ORPHAN_SWEEP_CYCLE_INTERVAL-th cycle, also runs the two
    orphan-reclaim sweeps (_sweep_terminal_session_rows /
    _sweep_orphan_checkpoints) -- backstops for P5-1's best-effort
    checkpoint-GC hook and for terminal sessions.db rows a restart
    stranded outside cleanup_expired_sessions' in-memory-only TTL walk.
    See _ORPHAN_SWEEP_CYCLE_INTERVAL and the sweep methods' own docstrings
    for the full rationale.

    P5-2 review fix (starvation): `cycle` increments BEFORE the fallible
    `cleanup_expired_sessions()` call, and the orphan sweeps run in their
    OWN try/except -- not nested inside cleanup's. Previously `cycle` only
    advanced on a SUCCESSFUL cleanup_expired_sessions() call, AND the two
    sweeps were reached only if that same call succeeded on that exact
    iteration (they were downstream of it inside one try block). Under a
    PERSISTENT cleanup_expired_sessions failure (not just an occasional
    flaky one), those two facts compound: `cycle` would freeze forever at
    whatever value it last reached, and even if it hadn't, the sweep calls
    were unreachable code after the raised exception on every single
    iteration -- i.e. permanent sweep starvation, not merely a delayed
    cadence. Decoupling the two means the ~hourly sweep cadence tracks
    wall-clock loop iterations unconditionally, and a broken
    cleanup_expired_sessions can never block the sweeps' own (separately
    best-effort) attempt.
    """
    logger.info("session_cleanup_task_started", ttl_hours=COMPLETED_SESSION_TTL.total_seconds() / 3600)

    cycle = 0
    while True:
        cycle += 1
        try:
            manager = await get_session_manager()
            await manager.cleanup_expired_sessions()
        except Exception as e:
            logger.error("session_cleanup_error", error=str(e))

        if cycle % _ORPHAN_SWEEP_CYCLE_INTERVAL == 0:
            try:
                manager = await get_session_manager()
                await manager._sweep_terminal_session_rows()
                await manager._sweep_orphan_checkpoints()
            except Exception as e:
                logger.error("session_orphan_sweep_error", error=str(e))

        await asyncio.sleep(300)  # Run every 5 minutes


# -------------------------------------------
# Best-effort Producer Mirrors
# -------------------------------------------
# Final-review fix (Minor 4, session-ssot): the paragraph this replaces
# described a two-store world (a legacy per-market dict as "the read path"
# + these helpers mirroring into the SM for pub/sub) that P3-1/P4 already
# retired -- the SM (Store C) has been the SOLE session store and the sole
# read path for a while now; there is no legacy dict left to write "FIRST".
#
# Current callers of `mirror_session_status` (the one of these three with
# live call sites today) are the narrow set of best-effort error/
# cancellation paths that want a swallowed-failure write rather than the
# raise-on-failure write-through below: approval.py's cancel-zombie-
# tolerance branch and its generic decision-processing error handler, and
# kr_stocks/analysis.py's awaiting-writethrough fail-closed branch
# (best-effort ERROR landing after the write-through itself already
# failed; coin/analysis.py had the same call site before its 2026-08-01
# removal). `mirror_session_state` and `mirror_session_removal`
# currently have no callers -- kept as the swallowed-failure counterpart to
# `commit_session_state`/`commit_session_status` below for any future
# best-effort site; most producer code (e.g. the discussion coordinator's
# room lifecycle) writes the SM directly via `get_session_manager()` +
# `update_state`/`update_status` instead of going through these wrappers.
# Any failure here is logged and swallowed (the WS degrades to its poll
# fallback). No-ops for sessions not tracked in sm.


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

    # Convert string market_type to enum. 코인 스택 제거(2026-08-01) 이후
    # KIWOOM이 유일한 시장이라 인식 실패는 KIWOOM으로 갈음한다(이전에는
    # MarketType.STOCK으로 갈음했으나 그 멤버도 함께 제거됐다).
    try:
        mt = MarketType(market_type)
    except ValueError:
        mt = MarketType.KIWOOM

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
