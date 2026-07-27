"""
Background Stock Scanner

Scans and analyzes all KOSPI/KOSDAQ stocks in background.
Features:
- Dynamic stock list loading via Kiwoom API (ka10099)
- Semaphore-controlled parallel analysis (3 concurrent slots)
- Progress tracking with ETA
- Result storage in SQLite
- Telegram notifications for progress
- Monthly reminder system
"""

import asyncio
import json
import aiosqlite
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Callable, Awaitable

from pydantic import BaseModel, Field

import structlog

from services.discovery.factors import (
    FlowRank,
    StockSnapshot,
    compute_strategy_scores,
    passes_quality_filter,
)

logger = structlog.get_logger()


# Database path
DB_PATH = Path(__file__).parent.parent.parent / "data" / "scanner_results.db"


class ScanStatus(str, Enum):
    """Background scan status"""
    IDLE = "idle"                # Not running
    RUNNING = "running"          # Currently scanning
    PAUSED = "paused"            # Paused by user
    COMPLETED = "completed"      # Completed
    FAILED = "failed"            # Failed with error


class ScanProgress(BaseModel):
    """Scan progress information"""
    status: ScanStatus = ScanStatus.IDLE
    total_stocks: int = 0
    completed: int = 0
    in_progress: int = 0
    failed: int = 0

    # Current stocks being analyzed
    current_stocks: List[str] = Field(default_factory=list)

    # Results summary
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    watch_count: int = 0
    avoid_count: int = 0

    # Timing
    started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_scan_date: Optional[datetime] = None

    # Error info
    last_error: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if self.total_stocks == 0:
            return 0.0
        return (self.completed / self.total_stocks) * 100


class ScanResult(BaseModel):
    """Individual stock scan result"""
    stk_cd: str
    stk_nm: str
    action: str  # BUY, SELL, HOLD, WATCH, AVOID
    signal: str
    confidence: float
    summary: str
    key_factors: List[str] = Field(default_factory=list)
    current_price: int = 0
    market_type: str = ""  # KOSPI, KOSDAQ
    scanned_at: datetime = Field(default_factory=datetime.now)


class BackgroundScanner:
    """
    Background stock scanner service.

    Features:
    - Dynamic stock list loading from Kiwoom API
    - Scans all stocks with semaphore-controlled concurrency
    - GPU-based dynamic concurrency adjustment
    - Optional LLM-based analysis (vs technical-only)
    - Stores results in SQLite database
    - Sends Telegram notifications
    - Supports pause/resume
    """

    MIN_CONCURRENT_SCANS = 1
    MAX_CONCURRENT_SCANS = 8  # Optimized for RTX 3090 24GB
    DEFAULT_CONCURRENT_SCANS = 3

    # Watch-list auto-promotion defaults. Auto-promote is OFF by default —
    # the scan pipeline previously dead-ended (results reached nowhere), but
    # turning promotion on unconditionally would silently start feeding the
    # autonomous watch monitor/queue-conversion path, so it stays an explicit
    # opt-in (mirrors the AUTONOMY_ENABLED fail-closed default elsewhere).
    DEFAULT_AUTO_PROMOTE_ENABLED = False
    DEFAULT_PROMOTE_CONFIDENCE_THRESHOLD = 0.7
    DEFAULT_PROMOTE_MAX_COUNT = 10

    def __init__(self):
        self._progress = ScanProgress()
        self._current_concurrency = self.DEFAULT_CONCURRENT_SCANS
        self._semaphore = asyncio.Semaphore(self._current_concurrency)
        self._running = False
        self._paused = False
        self._cancel_event = asyncio.Event()
        self._results: List[ScanResult] = []
        self._task: Optional[asyncio.Task] = None
        self._db_initialized = False
        self._use_llm = False  # Whether to use LLM for analysis
        self._gpu_monitor = None

        # FI-1: the notify_progress preference THIS scan was started with,
        # stashed off the start_scan() local so stop_scan() -- called much
        # later, often by a completely different caller (the coordinator's
        # timeout watchdog) that has no notify_progress argument of its own
        # -- can gate its own partial-completion Telegram notification on
        # it, same as every other notification point in this class already
        # does. Default True mirrors start_scan's own default; only ever
        # meaningfully read after start_scan has run (stop_scan's real work
        # is itself gated on self._running, which start_scan sets).
        self._notify_progress = True

        # Watch-list auto-promotion config (see start_scan args).
        self._auto_promote_enabled = self.DEFAULT_AUTO_PROMOTE_ENABLED
        self._promote_confidence_threshold = self.DEFAULT_PROMOTE_CONFIDENCE_THRESHOLD
        self._promote_max_count = self.DEFAULT_PROMOTE_MAX_COUNT

        # Scan mode (DS-2): "quick"/"llm" legacy behavior is unchanged and
        # keyed off `_use_llm` as before; "discovery" is a new collection
        # mode consumed by _scan_all_stocks' branch below. Defaults to
        # "quick" so any code that constructs BackgroundScanner() directly
        # (e.g. existing promotion tests) without going through start_scan
        # never accidentally trips the discovery-only promotion guard.
        self._mode = "quick"
        # True only when the most recent _load_stock_list() call fell back
        # to _get_fallback_stock_list() (get_all_stocks failure) — recorded
        # into scan_sessions.universe_fallback (DS-2).
        self._universe_fallback_used = False
        # T2: comma-joined market names (e.g. "KOSDAQ") that failed to load
        # on the most recent _load_stock_list() call while at least one
        # OTHER market succeeded — a real, partial universe that is still
        # promotion-eligible (unlike _universe_fallback_used's 15-name
        # hardcoded list). Recorded into scan_sessions.universe_partial.
        # Empty string means "no partial universe this run".
        self._universe_partial_markets = ""

        # SC-1: the scan_sessions.id of the currently in-flight scan (set by
        # start_scan, read by stop_scan so it can record a 'partial'
        # completion row for the session actually running — start_scan only
        # ever kept `session_id` as a local variable before this, so
        # stop_scan had no way to identify which row to update).
        self._current_session_id: Optional[str] = None

        # A1: 발굴 스캔 1회 동안 고정되는 유동성 임계값(원, ADTV 중앙값의
        # 최소 요구치). _scan_all_stocks_discovery 진입 시 1회만 산출된다 —
        # 종목마다 계좌를 조회하면 2,650회 API 호출이 되어버린다.
        self._discovery_min_adtv: Optional[float] = None

    async def _init_db(self):
        """Initialize SQLite database for storing scan results."""
        if self._db_initialized:
            return

        # Ensure data directory exists
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stk_cd TEXT NOT NULL,
                    stk_nm TEXT NOT NULL,
                    action TEXT NOT NULL,
                    signal TEXT,
                    confidence REAL,
                    summary TEXT,
                    key_factors TEXT,
                    current_price INTEGER,
                    market_type TEXT,
                    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    scan_session_id TEXT
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_stk_cd
                ON scan_results(stk_cd)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_action
                ON scan_results(action)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_session
                ON scan_results(scan_session_id)
            """)

            # Composite index for session + time sorting (frequently used query pattern)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_session_scanned
                ON scan_results(scan_session_id, scanned_at DESC)
            """)

            # Composite index for session + action filtering + time sorting
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_session_action_scanned
                ON scan_results(scan_session_id, action, scanned_at DESC)
            """)

            # Index for time-based sorting (global queries)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_results_scanned_at
                ON scan_results(scanned_at DESC)
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_sessions (
                    id TEXT PRIMARY KEY,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    total_stocks INTEGER,
                    completed INTEGER,
                    failed INTEGER,
                    buy_count INTEGER,
                    sell_count INTEGER,
                    hold_count INTEGER,
                    watch_count INTEGER,
                    avoid_count INTEGER,
                    status TEXT
                )
            """)

            # Index for getting latest session (critical for performance)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_sessions_started_at
                ON scan_sessions(started_at DESC)
            """)

            # Index for status filtering
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_sessions_status
                ON scan_sessions(status)
            """)

            # Discovery 수집 모드 스키마 확장 (DS-2): 이 DB 파일은 scanner.py
            # 자체 소유(storage.db와 분리)라 storage_service._ensure_columns와
            # 동일한 PRAGMA table_info 확인 후 ALTER 관례를 이 파일 안에서
            # 그대로 반복한다 — 전부 nullable, 기존 행은 NULL로 남는다.
            await self._ensure_columns(db, "scan_results", {"factor_json": "TEXT"})
            await self._ensure_columns(
                db,
                "scan_sessions",
                {
                    "universe_fallback": "INTEGER",
                    "scan_mode": "TEXT",
                    # T2: comma-joined market names that were missing from an
                    # otherwise-usable partial universe (NULL/'' when the
                    # session's universe was complete or a full fallback).
                    "universe_partial": "TEXT",
                },
            )

            await db.commit()

        self._db_initialized = True
        logger.info("scanner_db_initialized", path=str(DB_PATH))

    @staticmethod
    async def _ensure_columns(
        conn: "aiosqlite.Connection", table: str, cols: dict[str, str]
    ) -> None:
        """Add any of `cols` missing from `table` via ALTER TABLE ADD COLUMN.

        Ported from services/storage_service.py's `_ensure_columns` (same
        no-migration-mechanism situation — CREATE TABLE IF NOT EXISTS is a
        no-op against a table that already exists on disk, so a column added
        after the DB file was first created needs an explicit ALTER path).
        Every column added this way must be nullable.
        """
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, col_type in cols.items():
            if name not in existing:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                )

    async def _load_stock_list(self) -> List[tuple]:
        """
        Load full KOSPI/KOSDAQ stock list from Kiwoom API.

        T2 (발굴 유니버스 rate-limit 회복): `get_all_stocks` now returns
        (stocks, missing_markets) — one market failing (e.g. KOSDAQ still
        rate-limited after retries) no longer discards the market(s) that
        DID succeed. Three outcomes:
          - both markets fail (stocks empty) -> hardcoded 15-name fallback,
            `_universe_fallback_used = True` (promotion-suppressed, same as
            pre-T2 behavior).
          - one market missing but the other succeeded -> the real partial
            universe is used as-is, `_universe_fallback_used` stays False,
            and `_universe_partial_markets` records which market(s) were
            missing (promotion IS allowed — a partial real universe is not
            the same as the hardcoded fallback).
          - both markets succeed -> full universe, neither flag set.

        Returns:
            List of (stock_code, stock_name, market_type) tuples
        """
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        try:
            client = await get_shared_kiwoom_client_async()
            all_stocks, missing_markets = await client.get_all_stocks(
                include_kospi=True,
                include_kosdaq=True,
                exclude_warnings=True,
                exclude_etf_etn=True,  # DQ-1: ETN/스팩 유니버스 혼입 제외
            )
        except Exception as e:
            logger.error("stock_list_load_failed", error=str(e))
            # Fallback to hardcoded list if API fails
            self._universe_fallback_used = True
            return self._get_fallback_stock_list()

        if not all_stocks:
            # Both markets failed -- nothing real to work with.
            logger.error(
                "stock_list_load_failed",
                error="all_markets_failed",
                missing=missing_markets,
            )
            self._universe_fallback_used = True
            return self._get_fallback_stock_list()

        if missing_markets:
            # Partial but real universe -- promotion stays allowed.
            self._universe_partial_markets = ",".join(missing_markets)
            logger.warning(
                "universe_partial",
                missing=missing_markets,
                count=len(all_stocks),
            )

        stock_list = [
            (stock.code, stock.name, stock.market_name)
            for stock in all_stocks
        ]

        logger.info(
            "stock_list_loaded",
            total=len(stock_list),
        )

        return stock_list

    def _get_fallback_stock_list(self) -> List[tuple]:
        """Fallback stock list if API fails."""
        # Major KOSPI/KOSDAQ stocks
        return [
            ("005930", "삼성전자", "코스피"),
            ("000660", "SK하이닉스", "코스피"),
            ("035420", "NAVER", "코스피"),
            ("005380", "현대차", "코스피"),
            ("051910", "LG화학", "코스피"),
            ("006400", "삼성SDI", "코스피"),
            ("207940", "삼성바이오로직스", "코스피"),
            ("005490", "POSCO홀딩스", "코스피"),
            ("035720", "카카오", "코스피"),
            ("068270", "셀트리온", "코스피"),
            ("247540", "에코프로비엠", "코스닥"),
            ("086520", "에코프로", "코스닥"),
            ("041510", "에스엠", "코스닥"),
            ("035900", "JYP Ent.", "코스닥"),
            ("352820", "하이브", "코스닥"),
        ]

    async def start_scan(
        self,
        stock_list: Optional[List[tuple]] = None,
        notify_progress: bool = True,
        use_llm: bool = False,
        auto_gpu_scaling: bool = True,
        auto_promote_enabled: bool = DEFAULT_AUTO_PROMOTE_ENABLED,
        promote_confidence_threshold: float = DEFAULT_PROMOTE_CONFIDENCE_THRESHOLD,
        promote_max_count: int = DEFAULT_PROMOTE_MAX_COUNT,
        mode: str = "quick",
    ):
        """
        Start background scanning of all stocks.

        Args:
            stock_list: Optional custom list of (stk_cd, stk_nm, market_type) tuples
            notify_progress: Whether to send Telegram notifications
            use_llm: Use LLM for analysis (slower but more accurate). Ignored
                (forced False) when mode="discovery" — discovery collection
                is rule-only, never calls the LLM.
            auto_gpu_scaling: Automatically adjust concurrency based on GPU memory
            auto_promote_enabled: Auto-promote high-conviction BUY/WATCH results
                into the server watch-list on scan completion. OFF by default —
                must be explicitly enabled (see _promote_results_to_watch_list).
                Ignored when mode="discovery" — that pipeline's promotion is
                DS-4's job, never this legacy confidence-threshold path (see
                _promote_results_to_watch_list's mode guard).
            promote_confidence_threshold: Minimum confidence (0.0-1.0) a
                BUY/WATCH result must clear to be promoted.
            promote_max_count: Maximum number of results promoted per scan.
            mode: "quick" (default, legacy technical-indicator scan) /
                "llm" behavior is still selected via `use_llm` for backward
                compatibility — pass mode="discovery" to run the DS-2
                factor-collection pipeline (ka10001+ka10081 -> StockSnapshot
                -> quality filter -> compute_strategy_scores -> factor_json)
                instead of the legacy quick/llm analysis.
        """
        if self._running:
            logger.warning("scanner_already_running")
            return

        # Initialize database
        await self._init_db()

        # Track scan mode (DS-2) and LLM preference. Discovery never calls
        # the LLM regardless of what the caller passed for use_llm.
        self._mode = mode
        self._use_llm = False if mode == "discovery" else use_llm

        # FI-1: stop_scan() (called well after this method returns, often by
        # a caller -- e.g. the coordinator's timeout watchdog -- with no
        # notify_progress argument of its own) must know THIS scan's own
        # notify_progress preference to gate its own notification.
        self._notify_progress = notify_progress

        # Store watch-list auto-promotion preferences. For mode="discovery"
        # these are stored but never consulted — see
        # _promote_results_to_watch_list's unconditional mode guard.
        self._auto_promote_enabled = auto_promote_enabled
        self._promote_confidence_threshold = promote_confidence_threshold
        self._promote_max_count = promote_max_count

        # Initialize GPU monitor if using LLM with auto scaling
        if use_llm and auto_gpu_scaling:
            from services.gpu_monitor import get_gpu_monitor
            self._gpu_monitor = get_gpu_monitor()

            # Get initial optimal concurrency
            if await self._gpu_monitor.is_available():
                self._current_concurrency = await self._gpu_monitor.get_optimal_concurrency()
                self._semaphore = asyncio.Semaphore(self._current_concurrency)
                logger.info(
                    "gpu_based_concurrency",
                    concurrency=self._current_concurrency,
                )
            else:
                logger.info("gpu_not_available, using default concurrency")
        else:
            self._gpu_monitor = None

        # Load stock list if not provided (only _load_stock_list() calls can
        # set the fallback/partial flags — an explicitly supplied stock_list
        # never counts as a fallback or partial universe).
        self._universe_fallback_used = False
        self._universe_partial_markets = ""
        if stock_list is None:
            stock_list = await self._load_stock_list()

        # Generate session ID
        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        # SC-1: stop_scan needs this to record a 'partial' row for the
        # session it's actually stopping.
        self._current_session_id = session_id

        self._progress = ScanProgress(
            status=ScanStatus.RUNNING,
            total_stocks=len(stock_list),
            started_at=datetime.now(),
        )
        self._results = []
        self._running = True
        self._paused = False
        self._cancel_event.clear()

        logger.info(
            "background_scan_started",
            total_stocks=len(stock_list),
            session_id=session_id,
            use_llm=use_llm,
            concurrency=self._current_concurrency,
        )

        # Save session start (DS-2: scan_mode/universe_fallback metadata)
        scan_mode_label = "discovery" if mode == "discovery" else ("llm" if use_llm else "quick")
        await self._save_session_start(
            session_id,
            scan_mode=scan_mode_label,
            universe_fallback=self._universe_fallback_used,
            universe_partial=self._universe_partial_markets,
        )

        # Send Telegram notification
        analysis_mode = "LLM 기반 상세 분석" if use_llm else "기술적 지표 분석"
        estimated_time = len(stock_list) * (5 if use_llm else 2) // self._current_concurrency
        if notify_progress:
            await self._send_telegram_notification(
                f"🔍 *백그라운드 분석 시작*\n\n"
                f"총 {len(stock_list)}개 종목 분석 시작\n"
                f"분석 모드: {analysis_mode}\n"
                f"동시 처리: {self._current_concurrency}개\n"
                f"예상 소요 시간: {estimated_time}분"
            )

        # Start scan task
        self._task = asyncio.create_task(
            self._scan_all_stocks(stock_list, session_id, notify_progress)
        )

    async def _save_session_start(
        self,
        session_id: str,
        scan_mode: str = "quick",
        universe_fallback: bool = False,
        universe_partial: str = "",
    ):
        """Save scan session start to database."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO scan_sessions
                (id, started_at, total_stocks, status, scan_mode, universe_fallback, universe_partial)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                datetime.now(),
                self._progress.total_stocks,
                "running",
                scan_mode,
                1 if universe_fallback else 0,
                universe_partial or None,
            ))
            await db.commit()

    async def _save_session_complete(self, session_id: str):
        """Save scan session completion to database."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE scan_sessions SET
                    completed_at = ?,
                    completed = ?,
                    failed = ?,
                    buy_count = ?,
                    sell_count = ?,
                    hold_count = ?,
                    watch_count = ?,
                    avoid_count = ?,
                    status = ?
                WHERE id = ?
            """, (
                datetime.now(),
                self._progress.completed,
                self._progress.failed,
                self._progress.buy_count,
                self._progress.sell_count,
                self._progress.hold_count,
                self._progress.watch_count,
                self._progress.avoid_count,
                "completed",
                session_id,
            ))
            await db.commit()

    async def _save_session_partial(self, session_id: str):
        """SC-1: record a partial-completion scan session row.

        `stop_scan()` cancels `self._task` to interrupt an in-flight scan,
        which means `_scan_all_stocks` never reaches its own
        `_save_session_complete` call — the scan_sessions row was
        previously left stuck at status='running' forever (a permanent
        orphan once the process moved on), which made regime.py's and
        ranker.py's `status = 'completed'` gates silently return zero rows
        for a scan that may have gotten most of the way through the
        universe (real incident: 3700/4276 stocks saved, entirely
        unconsumed).

        Mirrors `_save_session_complete`'s exact UPDATE shape/value source
        (`self._progress.*` — the same counters the stop notification right
        below already surfaces as "완료: N/M") with status='partial'
        instead of 'completed'. `_save_session_complete` itself is
        untouched — a normal completion's row stays byte-identical.
        """
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE scan_sessions SET
                    completed_at = ?,
                    completed = ?,
                    failed = ?,
                    buy_count = ?,
                    sell_count = ?,
                    hold_count = ?,
                    watch_count = ?,
                    avoid_count = ?,
                    status = ?
                WHERE id = ?
            """, (
                datetime.now(),
                self._progress.completed,
                self._progress.failed,
                self._progress.buy_count,
                self._progress.sell_count,
                self._progress.hold_count,
                self._progress.watch_count,
                self._progress.avoid_count,
                "partial",
                session_id,
            ))
            await db.commit()

    async def _save_result_to_db(self, result: ScanResult, session_id: str):
        """Save individual scan result to database."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO scan_results
                (stk_cd, stk_nm, action, signal, confidence, summary,
                 key_factors, current_price, market_type, scanned_at, scan_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.stk_cd,
                result.stk_nm,
                result.action,
                result.signal,
                result.confidence,
                result.summary,
                ",".join(result.key_factors),
                result.current_price,
                result.market_type,
                result.scanned_at,
                session_id,
            ))
            await db.commit()

    async def _save_results_batch(self, results: List[ScanResult], session_id: str):
        """
        Save multiple scan results in a single transaction.

        This is much more efficient than saving individually:
        - Single DB connection instead of N connections
        - Single transaction instead of N commits
        - Uses executemany for batch insert

        Performance: ~100x faster for large batches

        Args:
            results: List of scan results to save
            session_id: Session ID to associate with results
        """
        if not results:
            return

        async with aiosqlite.connect(DB_PATH) as db:
            # Prepare data for batch insert
            data = [
                (
                    result.stk_cd,
                    result.stk_nm,
                    result.action,
                    result.signal,
                    result.confidence,
                    result.summary,
                    ",".join(result.key_factors),
                    result.current_price,
                    result.market_type,
                    result.scanned_at,
                    session_id,
                )
                for result in results
            ]

            await db.executemany("""
                INSERT INTO scan_results
                (stk_cd, stk_nm, action, signal, confidence, summary,
                 key_factors, current_price, market_type, scanned_at, scan_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            await db.commit()

            logger.debug(
                "batch_results_saved",
                count=len(results),
                session_id=session_id,
            )

    async def _scan_all_stocks(
        self,
        stocks: List[tuple],
        session_id: str,
        notify_progress: bool,
    ):
        """Scan all stocks with controlled concurrency using batched processing."""
        # Use larger batch size for LLM batch mode (combines requests into single LLM call)
        # For quick analysis, use smaller batches with concurrent individual analysis
        LLM_BATCH_SIZE = 10  # Number of stocks per LLM batch request
        QUICK_BATCH_SIZE = 50  # Process in smaller batches for memory management

        if self._mode == "discovery":
            await self._scan_all_stocks_discovery(stocks, session_id, notify_progress, QUICK_BATCH_SIZE)
        elif self._use_llm:
            await self._scan_all_stocks_llm_batch(stocks, session_id, notify_progress, LLM_BATCH_SIZE)
        else:
            await self._scan_all_stocks_quick(stocks, session_id, notify_progress, QUICK_BATCH_SIZE)

        # Mark complete
        self._progress.status = ScanStatus.COMPLETED
        self._progress.completed_at = datetime.now()
        self._progress.last_scan_date = datetime.now()
        self._running = False

        # Save session completion
        await self._save_session_complete(session_id)

        logger.info(
            "background_scan_completed",
            total=self._progress.total_stocks,
            completed=self._progress.completed,
            failed=self._progress.failed,
            session_id=session_id,
        )

        # Auto-promote high-conviction results into the server watch-list so
        # the discovery pipeline doesn't dead-end (opt-in; see docstring).
        await self._promote_results_to_watch_list(session_id)

        # Send completion notification
        if notify_progress:
            await self._send_scan_summary()

    async def _promote_results_to_watch_list(self, session_id: str) -> int:
        """Promote high-conviction scan results into the server watch-list.

        ROOT: scan results previously flowed nowhere — a completed scan sat in
        `self._results`/SQLite with no consumer, so agent-chat's 5-minute
        watch monitor and queue-conversion never picked up discovered names.
        This closes that dead-end by pushing the top BUY/WATCH results (by
        confidence) into `ExecutionCoordinator.add_to_watch_list`, the same
        sink the WATCH-decision graph node and the `/trading/watch-list/add`
        route use.

        Gated by `_auto_promote_enabled` (default False, set via
        `start_scan`) — auto-promotion must be explicitly turned on so a scan
        never silently starts feeding the autonomous pipeline.

        Only BUY/WATCH actions clearing `_promote_confidence_threshold` are
        candidates; AVOID/SELL/HOLD are never promoted. Candidates already
        present in the watch list (by ticker) are skipped so they don't
        consume a promotion slot or get duplicated; the remaining candidates
        are ranked by confidence and capped at `_promote_max_count`.

        Returns the number of results promoted (0 if disabled/none qualify).
        """
        if self._mode == "discovery":
            # Discovery-collected rows are action='WATCH' fixed with a
            # non-ranking placeholder confidence (real ranking/promotion is
            # DS-4's job: regime-weighted composite + LLM suitability gate).
            # This legacy confidence-threshold promotion must never fire for
            # them, regardless of _auto_promote_enabled.
            return 0

        if not self._auto_promote_enabled:
            return 0

        candidates = [
            r for r in self._results
            if r.action in ("BUY", "WATCH")
            and r.confidence >= self._promote_confidence_threshold
        ]
        if not candidates:
            return 0

        # Highest-confidence first so max_count keeps the strongest names
        # when there are more qualifying candidates than promotion slots.
        candidates.sort(key=lambda r: r.confidence, reverse=True)

        try:
            from app.dependencies import get_trading_coordinator

            coordinator = await get_trading_coordinator()
        except Exception as e:
            logger.warning("watch_list_promotion_coordinator_unavailable", error=str(e))
            return 0

        existing_tickers = {w.ticker for w in coordinator.get_watch_list()}

        promoted = 0
        for result in candidates:
            if promoted >= self._promote_max_count:
                break
            if result.stk_cd in existing_tickers:
                continue  # already watched — dedup, don't double-add

            try:
                coordinator.add_to_watch_list(
                    session_id=session_id,
                    ticker=result.stk_cd,
                    stock_name=result.stk_nm,
                    signal=result.signal,
                    confidence=result.confidence,
                    current_price=result.current_price,
                    analysis_summary=result.summary,
                    key_factors=result.key_factors,
                )
            except Exception as e:
                logger.warning(
                    "watch_list_promotion_failed",
                    stk_cd=result.stk_cd,
                    error=str(e),
                )
                continue

            existing_tickers.add(result.stk_cd)
            promoted += 1

        logger.info(
            "scan_results_promoted_to_watch_list",
            promoted=promoted,
            candidates=len(candidates),
            session_id=session_id,
            threshold=self._promote_confidence_threshold,
            max_count=self._promote_max_count,
        )
        return promoted

    async def _scan_all_stocks_quick(
        self,
        stocks: List[tuple],
        session_id: str,
        notify_progress: bool,
        batch_size: int,
    ):
        """Quick analysis mode - concurrent individual stock analysis."""
        for batch_start in range(0, len(stocks), batch_size):
            # Check for cancellation at batch level
            if self._cancel_event.is_set():
                logger.info("scan_cancelled_at_batch", batch_start=batch_start)
                break

            # Wait while paused
            while self._paused:
                await asyncio.sleep(1)
                if self._cancel_event.is_set():
                    break

            if self._cancel_event.is_set():
                break

            batch = stocks[batch_start:batch_start + batch_size]
            tasks = []

            for stock_data in batch:
                # Handle both 2-tuple and 3-tuple formats
                if len(stock_data) >= 3:
                    stk_cd, stk_nm, market_type = stock_data[0], stock_data[1], stock_data[2]
                else:
                    stk_cd, stk_nm = stock_data[0], stock_data[1]
                    market_type = ""

                task = asyncio.create_task(
                    self._scan_stock(stk_cd, stk_nm, market_type)
                )
                tasks.append(task)

            # Wait for batch to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect valid results for batch save
            valid_results: List[ScanResult] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("scan_task_failed", error=str(result))
                    self._progress.failed += 1
                elif result:
                    valid_results.append(result)
                    self._results.append(result)
                    self._update_action_count(result.action)

            # Batch save all valid results (N+1 optimization)
            if valid_results:
                await self._save_results_batch(valid_results, session_id)

            logger.debug(
                "batch_completed",
                batch_start=batch_start,
                batch_size=len(batch),
                total_completed=self._progress.completed,
            )

    async def _build_flow_map(self, client) -> dict:
        """ka10131(기관/외인 순매수 랭킹)을 시장별(KOSPI="001"/KOSDAQ="101")
        딱 1콜씩 선조회해 스캔 전체가 공유하는 FlowRank dict[ticker]를 만든다.

        스펙 요구: "스캔당 시장별 1콜, 종목별 재호출 절대 금지" — 이 메서드는
        `_scan_all_stocks_discovery` 시작 시 정확히 한 번만 호출되고, 결과
        dict는 모든 종목의 `compute_strategy_scores` 호출에 재사용된다.
        get_inst_foreign_flow 자체가 실패-무해(예외/빈 응답 시 None) 계약이라
        여기서도 방어적으로만 감싼다 — 조회 실패는 해당 시장 종목들의 flow
        성분이 0으로 수렴할 뿐, 스캔 자체를 절대 막지 않는다.
        """
        flow_map: dict = {}
        for mrkt_tp in ("001", "101"):
            try:
                rows = await client.get_inst_foreign_flow(mrkt_tp=mrkt_tp)
            except Exception as e:
                logger.warning("discovery_flow_fetch_failed", mrkt_tp=mrkt_tp, error=str(e))
                rows = None
            if not rows:
                continue
            for idx, row in enumerate(rows, start=1):
                ticker = row.get("stk_cd", "")
                if not ticker:
                    continue
                flow_map[ticker] = FlowRank(
                    ticker=ticker,
                    orgn_net_amt=row.get("orgn_net_amt", 0.0),
                    frgnr_net_amt=row.get("frgnr_net_amt", 0.0),
                    orgn_cont_days=row.get("orgn_cont_days", 0),
                    frgnr_cont_days=row.get("frgnr_cont_days", 0),
                    rank=idx,
                )
        return flow_map

    async def _fetch_discovery_snapshot(
        self,
        stk_cd: str,
        stk_nm: str,
        client,
    ) -> StockSnapshot:
        """ka10001+ka10081을 병렬 수집해 StockSnapshot을 만든다.

        둘 중 하나라도 예외를 던지거나 현재가를 숫자로 파싱할 수 없으면 그
        예외를 그대로 전파한다 — 호출자(`_scan_stock_discovery`)가 이를
        "수집 실패=행 드롭"으로 취급한다(가짜 HOLD 저장 금지, discovery
        모드 한정 — quick/llm 경로는 무변경).
        """
        stock_info_task = client.get_stock_info(stk_cd)
        chart_df_task = client.get_daily_chart_df(stk_cd)

        stock_info, chart_df = await asyncio.gather(
            stock_info_task, chart_df_task, return_exceptions=True
        )

        if isinstance(stock_info, Exception):
            raise stock_info
        if isinstance(chart_df, Exception):
            raise chart_df

        # 가격 파싱 불가(예: 예상 밖 타입)도 수집 실패로 취급 — 아래
        # float() 캐스팅이 실패하면 ValueError/TypeError가 호출자까지
        # 그대로 전파돼 드롭된다.
        price = float(stock_info.cur_prc)
        # ka10001 mrkt_tot_amt 단위=억원 (라이브 실측 2026-07-18: 005930
        # -> 14,908,010억 ≈ 1,490조). 팩터 엔진 필터는 원 단위 비교라 환산.
        market_cap = (
            float(stock_info.mrkt_tot_amt) * 100_000_000
            if stock_info.mrkt_tot_amt is not None
            else 0.0
        )
        per = float(stock_info.per) if stock_info.per is not None else 0.0
        pbr = float(stock_info.pbr) if stock_info.pbr is not None else 0.0
        volume = float(stock_info.acml_vol) if stock_info.acml_vol is not None else 0.0

        return StockSnapshot(
            ticker=stk_cd,
            name=stk_nm,
            price=price,
            market_cap=market_cap,
            per=per,
            pbr=pbr,
            volume=volume,
            chart_df=chart_df,
        )

    @staticmethod
    def _classify_breadth_direction(chart_df) -> str:
        """discovery breadth 판정: chart_df 마지막 2개 종가를 비교해
        advance(마지막 close > 직전 close)/decline(<)/flat(==거나 판정
        불가·데이터 부족)을 반환한다. 호출자가 이를 세션 buy/sell/hold_count
        에 매핑 — regime.py가 소비하는 breadth_ratio가 이제 처음으로
        유의미해진다(DS-2 리뷰픽스, 스펙 §3).
        """
        try:
            closes = chart_df["close"]
            if len(closes) < 2:
                return "flat"
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
        except Exception:
            return "flat"
        if last != last or prev != prev:  # NaN 체크 (pandas import 없이)
            return "flat"
        if last > prev:
            return "advance"
        if last < prev:
            return "decline"
        return "flat"

    async def _scan_stock_discovery(
        self,
        stk_cd: str,
        stk_nm: str,
        market_type: str,
        flow_map: dict,
        client,
    ) -> Optional[tuple]:
        """단일 종목 discovery 수집 (semaphore-controlled concurrency, quick
        모드의 `_scan_stock`과 동일한 동시성 정책 재사용 — rate limiter
        무변경 요구).

        수집 자체가 실패(예외/가격 파싱 불가)하면 None을 반환해 호출자가
        행을 드롭하게 한다. 수집은 성공했지만 품질 필터를 통과하지 못한
        종목은 (ScanResult, factor_json, breadth_direction) 3튜플을
        반환하되 factor_json에 skip_reason만 담는다(스코어 계산은 필터
        통과 종목에 한정 — DS-1 리뷰 이월: 필터→스코어 순서 엄수, len<60
        ma_alignment 가변 분모 함정 방어선).

        breadth_direction(advance/decline/flat, chart_df 마지막 2개 종가로
        판정)은 품질 필터 통과 여부와 무관하게(차트만 수집됐으면) 계산돼
        호출자가 세션 buy/sell/hold_count(=regime.py가 소비하는 breadth)에
        반영한다 — DS-2 리뷰픽스: scan_results 행의 action='WATCH' 고정은
        무변경(행 수준 의미 무변경, 세션 집계만 유의미화).
        """
        async with self._semaphore:
            self._progress.in_progress += 1
            self._progress.current_stocks.append(stk_cd)

            try:
                snap = await self._fetch_discovery_snapshot(stk_cd, stk_nm, client)
                breadth_direction = self._classify_breadth_direction(snap.chart_df)
                passed, reason = passes_quality_filter(
                    snap, min_adtv=self._discovery_min_adtv
                )

                if passed:
                    flow = flow_map.get(stk_cd)
                    scores = compute_strategy_scores(snap, flow)
                    atoms = scores["_atoms"]
                    strategy_scores = {k: v for k, v in scores.items() if k != "_atoms"}

                    # US 신호 T5: AI밸류체인 종목 + 당일 캐시 신호 존재 시만
                    # 소량 넛지(≤0.05). off/결측/비-AI밸류체인 -> 0.0.
                    # never-raise: 실패는 로그만 남기고 0.0 유지.
                    _us_bonus = 0.0
                    try:
                        from services.discovery.ai_valuechain import is_ai_valuechain, valuechain_signal_type
                        from services.trading.us_market_data import get_cached_us_ai_signal, get_subsignal
                        if is_ai_valuechain(stk_cd):
                            _us = await get_cached_us_ai_signal()
                            _sub = get_subsignal(_us, valuechain_signal_type(stk_cd))
                            if _sub is not None and _sub.get("signal") is not None:
                                _us_bonus = max(0.0, float(_sub.get("signal") or 0.0)) * 0.05
                    except Exception as e:
                        logger.warning("us_crossmarket_bonus_failed", stk_cd=stk_cd, error=str(e))

                    from services.discovery.liquidity import adtv_median

                    _adtv = adtv_median(snap.chart_df)

                    factor_json = {
                        "quality_filter_passed": True,
                        "skip_reason": None,
                        # flow_present 발원지 -- ka10131 수급 랭킹에 이
                        # 종목이 존재했는지(flow_map.get(stk_cd) is not
                        # None) 그대로. ranker._effective_weights가 이
                        # 플래그로 flow_present=False일 때 flow 가중을 0으로
                        # 세팅한다(재분배 없음 -- 구 DQ-2 재정규화는
                        # 2026-07-27 유동성 인지 아크에서 폐기됨, 경위는
                        # ranker._effective_weights docstring 참조. 없는 구
                        # 스캔은 raw flow==0.0 프록시로 폴백 -- ranker.py 쪽
                        # 하위호환).
                        "flow_present": flow is not None,
                        "scores": strategy_scores,
                        "atoms": atoms,
                        "close_price": snap.price,
                        "market_cap": snap.market_cap,
                        # US 신호 T5: AI밸류체인 종목 + 당일 캐시 신호 존재 시만
                        # ranker.rank_candidates가 composite에 소량 가산.
                        "us_crossmarket_bonus": _us_bonus,
                        # 유동성 인지 아크: 사이징 캡(C1)과 토론 프롬프트(C2)가
                        # 이 값을 소비한다. None이면 소비자가 캡/문구를 생략한다.
                        "adtv20_med": _adtv,
                    }
                    summary = f"{stk_nm}: 발굴 수집 완료(품질필터 통과)"
                else:
                    factor_json = {
                        "quality_filter_passed": False,
                        "skip_reason": reason,
                    }
                    summary = f"{stk_nm}: 발굴 수집 완료(품질필터 탈락: {reason})"

                # action='WATCH' 고정 + confidence는 composite가 아니다 —
                # 레짐 가중 랭킹·판정은 DS-4 전용(스펙 §5).
                result = ScanResult(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    action="WATCH",
                    signal="discovery",
                    confidence=0.0,
                    summary=summary,
                    key_factors=[],
                    current_price=int(snap.price),
                    market_type=market_type,
                )

                self._progress.completed += 1
                self._update_eta()

                return result, factor_json, breadth_direction

            except Exception as e:
                logger.warning("discovery_stock_collection_failed", stk_cd=stk_cd, error=str(e))
                self._progress.last_error = f"{stk_cd}: {str(e)}"
                return None

            finally:
                self._progress.in_progress -= 1
                if stk_cd in self._progress.current_stocks:
                    self._progress.current_stocks.remove(stk_cd)

    async def _save_discovery_results_batch(
        self,
        pairs: List[tuple],
        session_id: str,
    ):
        """discovery 모드 결과를 factor_json과 함께 배치 저장한다.

        기존 `_save_results_batch`/`_save_result_to_db`(quick/llm 공용)는
        건드리지 않는다 — 그 INSERT문은 factor_json 컬럼을 아예 언급하지
        않으므로 스키마에 컬럼이 추가돼도 그 두 메서드의 동작은
        byte-무변경이다.
        """
        if not pairs:
            return

        async with aiosqlite.connect(DB_PATH) as db:
            data = [
                (
                    result.stk_cd,
                    result.stk_nm,
                    result.action,
                    result.signal,
                    result.confidence,
                    result.summary,
                    ",".join(result.key_factors),
                    result.current_price,
                    result.market_type,
                    result.scanned_at,
                    session_id,
                    json.dumps(factor_json, ensure_ascii=False),
                )
                for result, factor_json in pairs
            ]

            await db.executemany("""
                INSERT INTO scan_results
                (stk_cd, stk_nm, action, signal, confidence, summary,
                 key_factors, current_price, market_type, scanned_at, scan_session_id,
                 factor_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            await db.commit()

            logger.debug(
                "discovery_batch_results_saved",
                count=len(pairs),
                session_id=session_id,
            )

    async def _resolve_min_adtv(self) -> float:
        """A1: 계좌 평가액 기반 유동성 임계값(원). 조회 실패 시 설정 폴백
        (fail-closed — 게이트를 끄는 대신 보수적 상수로 대체한다).

        min_adtv = max(equity * 0.04 / 1%, 10억) — 포지션(계좌의 4%)이 일평균
        거래대금의 1%를 넘지 않게 하는 최소 ADTV(required_min_adtv가 하드플로어
        10억과의 max를 처리). 계좌가 커지면 임계값도 자동으로 올라간다.

        0.04는 현재 포지션 배분 정책(계좌 대비 %) 하드코딩 — 별도 설정 항목이
        아직 없어 상수로 둔다.

        **상한 클램프(최종 리뷰 Blocking2)**: 계좌 평가액은 상류 파싱 사고에
        취약하다 — 이 저장소에 `mrkt_tot_amt` 억원 단위 오분류, `ka10131
        _parse_float` 이중부호 크래시 전례가 있다. equity가 100배로 잘못
        들어오면 min_adtv가 100배가 되어 2,650종 전량이 배제되는 폭주가
        일어난다(그리고 EOD 창에서만 드러난다). 폴백의 5배(기본 100억)를
        상한으로 둔다 — 정상 계좌 성장은 이 안에 들어오고, 자릿수 사고만
        잘린다. 폴백 자체도 하드플로어(10억) 미만으로는 못 내려간다.
        """
        from app.config import settings
        from app.dependencies import get_trading_coordinator
        from services.discovery.liquidity import HARD_FLOOR_ADTV, required_min_adtv

        # 폴백 하한 보호: 설정이 하드플로어보다 낮게 잡혀도 게이트가 그
        # 아래로는 내려가지 않는다(HARD_FLOOR_ADTV 계약).
        fallback = max(
            float(getattr(settings, "DISCOVERY_MIN_ADTV_FALLBACK", 2_000_000_000.0)),
            HARD_FLOOR_ADTV,
        )
        ceiling = fallback * 5.0
        try:
            coordinator = await get_trading_coordinator()
            equity = float(coordinator._state.account.total_equity)
            if equity <= 0:
                raise ValueError("equity<=0")
            resolved = required_min_adtv(equity * 0.04)
            if resolved > ceiling:
                logger.warning(
                    "discovery_min_adtv_clamped",
                    equity=equity, resolved=resolved, ceiling=ceiling,
                )
                return ceiling
            return resolved
        except Exception as e:
            logger.warning(
                "discovery_min_adtv_fallback", error=str(e), fallback=fallback
            )
            return fallback

    async def _scan_all_stocks_discovery(
        self,
        stocks: List[tuple],
        session_id: str,
        notify_progress: bool,
        batch_size: int,
    ):
        """Discovery 수집 모드 (DS-2): 종목당 ka10001+ka10081 -> StockSnapshot
        -> 품질 필터 -> compute_strategy_scores -> factor_json 저장.

        ka10131(기관/외인 순매수)은 이 메서드 진입 시 시장별 1콜씩만
        선조회해(`_build_flow_map`) 전체 스캔이 재사용한다. LLM 호출 없음
        (룰 전용). 기존 자동 승격 배관은 `_promote_results_to_watch_list`
        자체의 mode 가드로 비활성 — 이 메서드는 그 호출부를 건드리지 않는다.

        세션 buy/sell/hold_count는 종목별 advance/decline/flat breadth
        판정(`_classify_breadth_direction`)으로 집계된다 — action='WATCH'
        고정인 행 자체의 의미는 무변경(DS-2 리뷰픽스: 세션 집계만 유의미화).

        A1: 유동성 임계값(`_discovery_min_adtv`)은 이 메서드 진입 시 계좌
        평가액 기준으로 정확히 한 번만 산출돼 스캔 전체(종목 수천 개)가
        재사용한다 — 종목마다 계좌를 조회하지 않는다.

        킬스위치(`DISCOVERY_LIQUIDITY_GATE_ENABLED`, 설계 §6): off면
        `_discovery_min_adtv=None` — `factors.passes_quality_filter`의 기존
        하위호환 스킵 분기(`min_adtv is None`)로 수렴해 A1 게이트만 무효화된다.
        A2/A3 스코어 수식과 B(가중 재정규화 폐기)는 그대로 유지된다.
        """
        from app.config import settings as _settings

        if not getattr(_settings, "DISCOVERY_LIQUIDITY_GATE_ENABLED", True):
            self._discovery_min_adtv = None
            # 게이트가 꺼진 채 도는 스캔은 조용히 지나가면 안 된다 — 승격
            # 분포가 이전과 달라지는 이유가 로그에 남아야 한다.
            logger.warning("discovery_liquidity_gate_disabled")
        else:
            self._discovery_min_adtv = await self._resolve_min_adtv()
            logger.info(
                "discovery_min_adtv_resolved", min_adtv=self._discovery_min_adtv
            )

        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async

        client = await get_shared_kiwoom_client_async()
        flow_map = await self._build_flow_map(client)

        for batch_start in range(0, len(stocks), batch_size):
            if self._cancel_event.is_set():
                logger.info("scan_cancelled_at_batch", batch_start=batch_start)
                break

            while self._paused:
                await asyncio.sleep(1)
                if self._cancel_event.is_set():
                    break

            if self._cancel_event.is_set():
                break

            batch = stocks[batch_start:batch_start + batch_size]
            tasks = []

            for stock_data in batch:
                if len(stock_data) >= 3:
                    stk_cd, stk_nm, market_type = stock_data[0], stock_data[1], stock_data[2]
                else:
                    stk_cd, stk_nm = stock_data[0], stock_data[1]
                    market_type = ""

                tasks.append(asyncio.create_task(
                    self._scan_stock_discovery(stk_cd, stk_nm, market_type, flow_map, client)
                ))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            valid_pairs: List[tuple] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("discovery_scan_task_failed", error=str(result))
                    self._progress.failed += 1
                elif result is None:
                    self._progress.failed += 1
                else:
                    scan_result, factor_json, breadth_direction = result
                    valid_pairs.append((scan_result, factor_json))
                    self._results.append(scan_result)
                    self._update_breadth_count(breadth_direction)

            if valid_pairs:
                await self._save_discovery_results_batch(valid_pairs, session_id)

            logger.debug(
                "discovery_batch_completed",
                batch_start=batch_start,
                batch_size=len(batch),
                total_completed=self._progress.completed,
            )

    async def _scan_all_stocks_llm_batch(
        self,
        stocks: List[tuple],
        session_id: str,
        notify_progress: bool,
        batch_size: int,
    ):
        """
        LLM batch analysis mode - combines multiple stocks into single LLM requests.

        This is more efficient for GPU utilization as it reduces LLM call overhead
        and allows the model to process multiple analyses in one inference pass.
        """
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.technical_indicators import TechnicalIndicators

        for batch_start in range(0, len(stocks), batch_size):
            # Check for cancellation at batch level
            if self._cancel_event.is_set():
                logger.info("scan_cancelled_at_batch", batch_start=batch_start)
                break

            # Wait while paused
            while self._paused:
                await asyncio.sleep(1)
                if self._cancel_event.is_set():
                    break

            if self._cancel_event.is_set():
                break

            # GPU-based dynamic batch size and concurrency adjustment
            if self._gpu_monitor:
                # Check if we should throttle (critical memory or overheating)
                if await self._gpu_monitor.should_throttle():
                    logger.warning("gpu_throttle_active, waiting 5s")
                    await asyncio.sleep(5)

                # Get optimal concurrency
                new_concurrency = await self._gpu_monitor.get_optimal_concurrency()
                if new_concurrency != self._current_concurrency:
                    logger.info(
                        "gpu_concurrency_adjusted",
                        old=self._current_concurrency,
                        new=new_concurrency,
                    )
                    self._current_concurrency = new_concurrency

                # Get optimal batch size based on available memory
                batch_size = await self._gpu_monitor.get_optimal_batch_size(
                    default=batch_size
                )

            batch = stocks[batch_start:batch_start + batch_size]

            # Collect data for all stocks in batch IN PARALLEL
            stocks_data = await self._collect_batch_data_parallel(batch)

            # Run batch LLM analysis if we have data
            if stocks_data:
                results = await self._run_batch_llm_analysis(stocks_data)

                # Save results in batch (optimized - single DB transaction)
                await self._save_results_batch(results, session_id)

                # Update in-memory tracking
                for result in results:
                    self._results.append(result)
                    self._update_action_count(result.action)
                    self._progress.completed += 1
                    self._update_eta()

            logger.debug(
                "llm_batch_completed",
                batch_start=batch_start,
                batch_size=len(batch),
                processed=len(stocks_data),
                total_completed=self._progress.completed,
            )

    async def _collect_batch_data_parallel(
        self,
        batch: List[tuple],
        max_concurrent_fetch: int = 10,
    ) -> List[tuple]:
        """
        Collect stock data for a batch in parallel.

        This significantly improves performance by fetching data for
        multiple stocks concurrently instead of sequentially.

        Performance:
        - Sequential: ~2-3 seconds for 10 stocks (200-300ms each)
        - Parallel: ~300-500ms for 10 stocks (limited by slowest)

        Args:
            batch: List of (stk_cd, stk_nm, market_type) tuples
            max_concurrent_fetch: Maximum concurrent API calls (default: 10)

        Returns:
            List of (stk_cd, stk_nm, market_type, price, change, volume, tech_summary) tuples
        """
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.technical_indicators import TechnicalIndicators

        client = await get_shared_kiwoom_client_async()
        stocks_data = []
        fetch_semaphore = asyncio.Semaphore(max_concurrent_fetch)

        async def fetch_single_stock(stock_data: tuple) -> Optional[tuple]:
            """Fetch data for a single stock with rate limiting."""
            # Handle both 2-tuple and 3-tuple formats
            if len(stock_data) >= 3:
                stk_cd, stk_nm, market_type = stock_data[0], stock_data[1], stock_data[2]
            else:
                stk_cd, stk_nm = stock_data[0], stock_data[1]
                market_type = ""

            async with fetch_semaphore:  # Rate limit concurrent API calls
                try:
                    self._progress.current_stocks.append(stk_cd)
                    self._progress.in_progress += 1

                    # Fetch stock info and chart data in parallel
                    stock_info_task = client.get_stock_info(stk_cd)
                    chart_df_task = client.get_daily_chart_df(stk_cd)

                    stock_info, chart_df = await asyncio.gather(
                        stock_info_task,
                        chart_df_task,
                        return_exceptions=True,
                    )

                    # Handle exceptions
                    if isinstance(stock_info, Exception):
                        raise stock_info
                    if isinstance(chart_df, Exception):
                        chart_df = None

                    current_price = stock_info.cur_prc
                    prdy_ctrt = stock_info.prdy_ctrt if hasattr(stock_info, "prdy_ctrt") else 0
                    # StockBasicInfo has no `trd_qty` attribute — that name
                    # was always dead (hasattr always False -> always 0).
                    # The real accumulated-volume field is `acml_vol`.
                    trd_qty = stock_info.acml_vol if hasattr(stock_info, "acml_vol") else 0

                    # Calculate technical indicators
                    tech_summary = "데이터 부족"
                    if chart_df is not None and len(chart_df) >= 20:
                        try:
                            tech = TechnicalIndicators(chart_df)
                            indicators = tech.calculate_all()
                            signals = indicators.get("signals", [])
                            tech_summary = self._build_tech_summary(indicators, signals)
                        except Exception as e:
                            logger.warning("tech_indicators_failed", stk_cd=stk_cd, error=str(e))

                    return (stk_cd, stk_nm, market_type, current_price, prdy_ctrt, trd_qty, tech_summary)

                except Exception as e:
                    logger.warning("stock_data_fetch_failed", stk_cd=stk_cd, error=str(e))
                    self._progress.failed += 1
                    return None

                finally:
                    if stk_cd in self._progress.current_stocks:
                        self._progress.current_stocks.remove(stk_cd)
                    self._progress.in_progress -= 1

        # Fetch all stocks in batch in parallel
        tasks = [fetch_single_stock(stock) for stock in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful results
        for result in results:
            if result is not None and not isinstance(result, Exception):
                stocks_data.append(result)

        logger.debug(
            "batch_data_collected_parallel",
            batch_size=len(batch),
            success_count=len(stocks_data),
        )

        return stocks_data

    async def _scan_stock(
        self,
        stk_cd: str,
        stk_nm: str,
        market_type: str,
    ) -> Optional[ScanResult]:
        """
        Scan a single stock with semaphore control.

        Note: Does NOT save to database - caller should batch save results
        for better performance (N+1 optimization).
        """
        async with self._semaphore:
            self._progress.in_progress += 1
            self._progress.current_stocks.append(stk_cd)

            try:
                # Choose analysis method based on use_llm flag
                if self._use_llm:
                    result = await self._run_llm_analysis(stk_cd, stk_nm, market_type)
                else:
                    result = await self._run_quick_analysis(stk_cd, stk_nm, market_type)

                self._progress.completed += 1
                self._update_eta()

                return result

            except Exception as e:
                logger.error(
                    "stock_scan_failed",
                    stk_cd=stk_cd,
                    error=str(e),
                )
                self._progress.last_error = f"{stk_cd}: {str(e)}"
                return None

            finally:
                self._progress.in_progress -= 1
                if stk_cd in self._progress.current_stocks:
                    self._progress.current_stocks.remove(stk_cd)

    async def _run_quick_analysis(
        self,
        stk_cd: str,
        stk_nm: str,
        market_type: str = "",
    ) -> ScanResult:
        """
        Run a quick analysis on a stock.

        This is a lightweight version that focuses on key indicators.
        """
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.technical_indicators import TechnicalIndicators

        try:
            # Get Kiwoom client
            client = await get_shared_kiwoom_client_async()

            # Get stock info and chart data
            stock_info = await client.get_stock_info(stk_cd)
            chart_df = await client.get_daily_chart_df(stk_cd)

            current_price = stock_info.cur_prc

            # Calculate technical indicators
            if len(chart_df) >= 20:
                tech = TechnicalIndicators(chart_df)
                indicators = tech.calculate_all()
                signals = indicators.get("signals", [])
            else:
                signals = []

            # Determine action based on indicators
            action, confidence = self._determine_action_from_signals(
                signals,
                stock_info,
            )

            # Build summary
            signal_descriptions = [s.get("description", "") for s in signals[:3]]
            summary = ", ".join(signal_descriptions) if signal_descriptions else "특이 시그널 없음"

            return ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action=action,
                signal=action.lower(),
                confidence=confidence,
                summary=f"{stk_nm}: {summary}",
                key_factors=signal_descriptions,
                current_price=current_price,
                market_type=market_type,
            )

        except Exception as e:
            logger.warning("quick_analysis_failed", stk_cd=stk_cd, error=str(e))
            # Return default result on error
            return ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action="HOLD",
                signal="hold",
                confidence=0.5,
                summary=f"분석 실패: {str(e)}",
                key_factors=[],
                current_price=0,
                market_type=market_type,
            )

    async def _run_llm_analysis(
        self,
        stk_cd: str,
        stk_nm: str,
        market_type: str = "",
    ) -> ScanResult:
        """
        Run LLM-based analysis on a stock.

        This is a more comprehensive analysis using LLM for deeper insights.
        Requires GPU and takes longer but provides more accurate recommendations.
        """
        from app.core.kiwoom_singleton import get_shared_kiwoom_client_async
        from services.technical_indicators import TechnicalIndicators
        from agents.llm_provider import get_llm_provider
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            # Get Kiwoom client
            client = await get_shared_kiwoom_client_async()

            # Get stock info and chart data
            stock_info = await client.get_stock_info(stk_cd)
            chart_df = await client.get_daily_chart_df(stk_cd)

            current_price = stock_info.cur_prc

            # Calculate technical indicators
            tech_summary = ""
            signals = []
            if len(chart_df) >= 20:
                tech = TechnicalIndicators(chart_df)
                indicators = tech.calculate_all()
                signals = indicators.get("signals", [])
                tech_summary = self._build_tech_summary(indicators, signals)

            # Build LLM prompt for analysis
            prompt = f"""한국 주식 종목 분석을 요청합니다.

종목 정보:
- 종목코드: {stk_cd}
- 종목명: {stk_nm}
- 시장: {market_type}
- 현재가: {current_price:,}원
- 전일대비: {stock_info.prdy_ctrt:.2f}%
- 거래량: {stock_info.trd_qty:,}주

기술적 분석 요약:
{tech_summary}

위 정보를 바탕으로 다음 형식으로 분석 결과를 제공해주세요:

ACTION: [BUY/SELL/HOLD/WATCH/AVOID 중 하나]
CONFIDENCE: [0.0~1.0 사이 숫자]
SUMMARY: [한 줄 요약]
KEY_FACTORS: [주요 판단 근거 3가지, 쉼표로 구분]

응답은 위 형식만 포함해주세요."""

            # Call LLM using LangChain messages
            llm = get_llm_provider()
            messages = [
                SystemMessage(content="당신은 한국 주식 시장 전문 분석가입니다."),
                HumanMessage(content=prompt),
            ]
            response = await llm.generate(messages, task="scanner")

            # Parse LLM response
            action, confidence, summary, key_factors = self._parse_llm_response(
                response, stk_nm
            )

            return ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action=action,
                signal=action.lower(),
                confidence=confidence,
                summary=summary,
                key_factors=key_factors,
                current_price=current_price,
                market_type=market_type,
            )

        except Exception as e:
            logger.warning("llm_analysis_failed", stk_cd=stk_cd, error=str(e))
            # Fallback to quick analysis on LLM failure
            return await self._run_quick_analysis(stk_cd, stk_nm, market_type)

    async def _run_batch_llm_analysis(
        self,
        stocks_data: List[tuple],  # [(stk_cd, stk_nm, market_type, stock_info, tech_summary), ...]
    ) -> List[ScanResult]:
        """
        Run LLM-based analysis on multiple stocks in a single batch.

        This is more efficient for GPU utilization as it combines multiple
        analysis requests into a single LLM call.
        """
        from agents.llm_provider import get_llm_provider
        from langchain_core.messages import HumanMessage, SystemMessage

        if not stocks_data:
            return []

        # Build batch prompt
        stocks_info = []
        for i, (stk_cd, stk_nm, market_type, current_price, prdy_ctrt, trd_qty, tech_summary) in enumerate(stocks_data):
            stocks_info.append(f"""
[종목 {i+1}]
- 종목코드: {stk_cd}
- 종목명: {stk_nm}
- 시장: {market_type}
- 현재가: {current_price:,}원
- 전일대비: {prdy_ctrt:.2f}%
- 거래량: {trd_qty:,}주
- 기술적 분석: {tech_summary}
""")

        batch_prompt = f"""다음 {len(stocks_data)}개 한국 주식 종목을 분석해주세요.

{chr(10).join(stocks_info)}

각 종목에 대해 다음 형식으로 분석 결과를 제공해주세요:

[종목 1]
ACTION: [BUY/SELL/HOLD/WATCH/AVOID]
CONFIDENCE: [0.0~1.0]
SUMMARY: [한 줄 요약]
KEY_FACTORS: [주요 판단 근거, 쉼표 구분]

[종목 2]
...

모든 종목에 대해 위 형식으로 응답해주세요."""

        try:
            # Call LLM with batch prompt using LangChain messages
            llm = get_llm_provider()
            messages = [
                SystemMessage(content="당신은 한국 주식 시장 전문 분석가입니다. 주어진 기술적 지표와 시장 데이터를 기반으로 종목을 분석합니다."),
                HumanMessage(content=batch_prompt),
            ]
            response = await llm.generate(messages, task="scanner")

            # Parse batch response
            results = self._parse_batch_llm_response(response, stocks_data)
            return results

        except Exception as e:
            logger.warning("batch_llm_analysis_failed", error=str(e))
            # Return default results on failure
            return [
                ScanResult(
                    stk_cd=stk_cd,
                    stk_nm=stk_nm,
                    action="HOLD",
                    signal="hold",
                    confidence=0.5,
                    summary=f"배치 분석 실패: {str(e)}",
                    key_factors=[],
                    current_price=current_price,
                    market_type=market_type,
                )
                for stk_cd, stk_nm, market_type, current_price, _, _, _ in stocks_data
            ]

    def _parse_batch_llm_response(
        self,
        response: str,
        stocks_data: List[tuple],
    ) -> List[ScanResult]:
        """Parse batch LLM response to extract results for each stock."""
        results = []

        # Split response by stock markers
        import re
        stock_sections = re.split(r'\[종목\s*\d+\]', response)
        stock_sections = [s.strip() for s in stock_sections if s.strip()]

        for i, (stk_cd, stk_nm, market_type, current_price, _, _, _) in enumerate(stocks_data):
            if i < len(stock_sections):
                action, confidence, summary, key_factors = self._parse_llm_response(
                    stock_sections[i], stk_nm
                )
            else:
                # Default if parsing failed
                action, confidence, summary, key_factors = "HOLD", 0.5, f"{stk_nm} 분석", []

            results.append(ScanResult(
                stk_cd=stk_cd,
                stk_nm=stk_nm,
                action=action,
                signal=action.lower(),
                confidence=confidence,
                summary=summary,
                key_factors=key_factors,
                current_price=current_price,
                market_type=market_type,
            ))

        return results

    def _build_tech_summary(self, indicators: dict, signals: List[dict]) -> str:
        """Build technical indicators summary for LLM prompt."""
        lines = []

        # RSI
        if "rsi" in indicators:
            rsi = indicators["rsi"]
            status = "과매수" if rsi > 70 else "과매도" if rsi < 30 else "중립"
            lines.append(f"- RSI: {rsi:.1f} ({status})")

        # MACD
        if "macd" in indicators and "macd_signal" in indicators:
            macd = indicators["macd"]
            signal = indicators["macd_signal"]
            status = "상승 추세" if macd > signal else "하락 추세"
            lines.append(f"- MACD: {macd:.2f} ({status})")

        # Moving Averages
        if "sma_20" in indicators and "sma_50" in indicators:
            sma20 = indicators["sma_20"]
            sma50 = indicators["sma_50"]
            status = "골든크로스 가능" if sma20 > sma50 else "데드크로스 경고"
            lines.append(f"- MA20/MA50: {status}")

        # Signals
        if signals:
            signal_desc = ", ".join([s.get("description", "") for s in signals[:5]])
            lines.append(f"- 감지된 시그널: {signal_desc}")

        return "\n".join(lines) if lines else "기술적 지표 데이터 부족"

    def _parse_llm_response(
        self,
        response: str,
        stk_nm: str,
    ) -> tuple:
        """Parse LLM response to extract action, confidence, summary, and key factors."""
        action = "HOLD"
        confidence = 0.5
        summary = f"{stk_nm} 분석 완료"
        key_factors = []

        try:
            lines = response.strip().split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("ACTION:"):
                    parsed_action = line.replace("ACTION:", "").strip().upper()
                    if parsed_action in ("BUY", "SELL", "HOLD", "WATCH", "AVOID"):
                        action = parsed_action
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.replace("CONFIDENCE:", "").strip())
                        confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        pass
                elif line.startswith("SUMMARY:"):
                    summary = line.replace("SUMMARY:", "").strip()
                elif line.startswith("KEY_FACTORS:"):
                    factors_str = line.replace("KEY_FACTORS:", "").strip()
                    key_factors = [f.strip() for f in factors_str.split(",") if f.strip()]
        except Exception as e:
            logger.warning("llm_response_parse_error", error=str(e))

        return action, confidence, summary, key_factors

    def _determine_action_from_signals(
        self,
        signals: List[dict],
        stock_info,
    ) -> tuple:
        """Determine action from technical signals."""
        buy_signals = 0
        sell_signals = 0

        for signal in signals:
            signal_type = signal.get("type", "")
            if signal_type in ("bullish", "oversold", "golden_cross"):
                buy_signals += 1
            elif signal_type in ("bearish", "overbought", "death_cross"):
                sell_signals += 1

        # Check price change
        price_change = stock_info.prdy_ctrt if hasattr(stock_info, "prdy_ctrt") else 0

        # Determine action
        if buy_signals >= 3:
            return "BUY", 0.8
        elif sell_signals >= 3:
            return "AVOID", 0.8
        elif buy_signals >= 2:
            return "WATCH", 0.7
        elif sell_signals >= 2:
            return "AVOID", 0.7
        elif buy_signals > sell_signals:
            return "WATCH", 0.6
        elif sell_signals > buy_signals:
            return "AVOID", 0.6
        else:
            return "HOLD", 0.5

    def _update_action_count(self, action: str):
        """Update action count in progress."""
        action_map = {
            "BUY": "buy_count",
            "SELL": "sell_count",
            "HOLD": "hold_count",
            "WATCH": "watch_count",
            "AVOID": "avoid_count",
            "ADD": "buy_count",
            "REDUCE": "sell_count",
        }
        attr = action_map.get(action, "hold_count")
        setattr(self._progress, attr, getattr(self._progress, attr) + 1)

    def _update_breadth_count(self, direction: str):
        """Discovery 모드 전용 세션 카운트 (DS-2 리뷰픽스): chart_df 마지막
        2개 종가로 판정한 일간 등락 방향(advance/decline/flat)을
        buy/sell/hold_count에 매핑한다. scan_results 행의 action='WATCH'
        고정(행 수준 의미 무변경)과는 별개로, regime.py가 소비하는 세션
        집계(breadth)만 advance/decline로 유의미화한다 — quick/llm 모드의
        `_update_action_count`는 무변경."""
        direction_map = {
            "advance": "buy_count",
            "decline": "sell_count",
            "flat": "hold_count",
        }
        attr = direction_map.get(direction, "hold_count")
        setattr(self._progress, attr, getattr(self._progress, attr) + 1)

    def _update_eta(self):
        """Update estimated completion time."""
        if self._progress.completed > 0:
            elapsed = (datetime.now() - self._progress.started_at).total_seconds()
            rate = self._progress.completed / elapsed
            remaining = self._progress.total_stocks - self._progress.completed
            eta_seconds = remaining / rate if rate > 0 else 0
            self._progress.estimated_completion = datetime.now() + timedelta(seconds=eta_seconds)

    async def pause_scan(self):
        """Pause the background scan."""
        if self._running and not self._paused:
            self._paused = True
            self._progress.status = ScanStatus.PAUSED
            logger.info("background_scan_paused")

            await self._send_telegram_notification(
                f"⏸ *백그라운드 분석 일시 중지*\n\n"
                f"진행률: {self._progress.completed}/{self._progress.total_stocks}"
            )

    async def resume_scan(self):
        """Resume the background scan."""
        if self._running and self._paused:
            self._paused = False
            self._progress.status = ScanStatus.RUNNING
            logger.info("background_scan_resumed")

            await self._send_telegram_notification(
                f"▶️ *백그라운드 분석 재개*\n\n"
                f"남은 종목: {self._progress.total_stocks - self._progress.completed}개"
            )

    async def stop_scan(self, reason: str = "manual"):
        """Stop the background scan.

        Args:
            reason: "manual" (default) -- an FE-initiated stop (POST
                /scanner/stop) -- suppresses the partial-completion Telegram
                notification below unconditionally; a user who just clicked
                Stop doesn't need a message telling them a scan they just
                stopped, stopped. "timeout" -- the coordinator's
                `_run_discovery_scan` watchdog cleanup -- instead follows the
                same `self._notify_progress` gate every other notification
                point in this class already uses (start_scan's own start
                notification, `_scan_all_stocks`' completion notification),
                so an EOD discovery scan started with `notify_progress=False`
                never fires a stop notification the caller explicitly opted
                out of.

                FI-1: prior to this, the partial notification below fired
                unconditionally regardless of `notify_progress` or which
                caller triggered the stop -- a 4276-stock EOD scan
                (notify_progress=False) that hit its watchdog timeout still
                sent a Telegram "분석 중지" message every time, and the FE's
                own manual Stop button re-notified the user of an action
                they had just taken themselves.

        `_save_session_partial` below (the SC-1 DB persistence fix) is NOT
        gated by `reason` or `notify_progress` -- it must always run so
        regime.py/ranker.py's breadth accounting reflects reality regardless
        of how or why the scan was stopped.
        """
        if self._running:
            self._cancel_event.set()
            self._progress.status = ScanStatus.IDLE
            self._running = False
            self._paused = False

            # SC-1: record the partial-completion row BEFORE cancelling the
            # task -- _task.cancel() interrupts _scan_all_stocks before it
            # can ever reach its own _save_session_complete, which used to
            # leave the DB row orphaned at status='running' forever (see
            # _save_session_partial's docstring). No-op if no scan session
            # was ever started (self._current_session_id unset). Best-effort
            # -- a failure here must not block the cancel/notify below.
            if self._current_session_id:
                try:
                    await self._save_session_partial(self._current_session_id)
                except Exception as e:
                    logger.warning(
                        "scan_partial_session_save_failed",
                        session_id=self._current_session_id,
                        error=str(e),
                    )

            if self._task:
                self._task.cancel()

            logger.info("background_scan_stopped", reason=reason)

            # SC-3: the stop above always corresponds to a partial-completion
            # session (a normal completion clears self._running BEFORE
            # reaching _save_session_complete -- see _scan_all_stocks -- so
            # stop_scan() is a guaranteed no-op via the `if self._running:`
            # guard once a scan has already finished on its own). Today's
            # incident: this Telegram message showed only "분석 중지" +
            # "완료: 3700/4276" with no indication that breadth was still
            # reflected and only promotion was withheld, which read as a
            # total abandonment rather than a partial-completion. Surface
            # the same N/M/percent explicitly in both the log and (if the
            # notification isn't gated off below) the notification text.
            completed = self._progress.completed
            total = self._progress.total_stocks
            coverage_pct = (completed / total * 100) if total else 0.0
            partial_note = (
                f"부분 완주 {completed}/{total}({coverage_pct:.1f}%) — "
                f"breadth 반영, 승격 보류"
            )

            logger.info(
                partial_note,
                session_id=self._current_session_id,
                completed=completed,
                total=total,
                coverage_pct=round(coverage_pct, 1),
            )

            # FI-1: a manual stop never notifies (the caller already knows);
            # any other reason (currently just "timeout") still follows this
            # scan's own notify_progress preference.
            if reason != "manual" and self._notify_progress:
                await self._send_telegram_notification(
                    f"⏹ *백그라운드 분석 중지*\n\n"
                    f"분석 완료: {completed}/{total}\n"
                    f"{partial_note}"
                )

    async def reconcile_orphan_scan_sessions(self) -> int:
        """FI-1: mark leftover status='running' scan_sessions rows 'aborted'.

        A process that dies (crash, forced kill) while a scan is in flight
        never reaches stop_scan()/_save_session_partial, nor
        _scan_all_stocks'/_save_session_complete -- its scan_sessions row is
        left at status='running' forever once the process is gone (the same
        underlying orphan failure mode `_save_session_partial`'s docstring
        describes for stop_scan, but for a process that never got to call
        stop_scan at all -- e.g. today's 20260720153027 incident). 'aborted'
        is deliberately its own status, distinct from 'partial' (a
        stop_scan-recorded partial completion -- real breadth was saved)
        and 'completed'/'failed' -- and outside the
        `status IN ('completed', 'partial')` gates regime.py/ranker.py use
        to consume scan results (SC-1), so an aborted row is never mistaken
        for consumable breadth.

        MUST be called at process startup BEFORE any scan starts in THIS
        process (see app.main's lifespan) -- at that point this process can
        never have a genuinely in-flight 'running' row of its own, so every
        'running' row found here is guaranteed to be a leftover from a
        previous process.

        Best-effort / never-raises -- e.g. the DB file may not exist yet if
        no scan has ever run. The caller also wraps this in its own
        try/except for startup-safety logging, but this method swallows its
        own errors too and reports 0 reconciled rather than propagating.

        Returns:
            Number of rows reconciled (0 if none were orphaned, or on any
            internal failure).
        """
        try:
            await self._init_db()
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "UPDATE scan_sessions SET status = 'aborted' WHERE status = 'running'"
                )
                await db.commit()
                return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        except Exception as e:
            logger.warning("scan_orphan_reconcile_failed", error=str(e))
            return 0

    def get_progress(self) -> ScanProgress:
        """Get current scan progress."""
        return self._progress

    @property
    def is_running(self) -> bool:
        """DS-5 review fix: public mirror of the internal `_running` flag.

        `start_scan()` itself gates on this flag and silently no-ops when a
        scan (of ANY mode -- manual or discovery) is already in flight
        (`if self._running: ... return`, above). Callers that need to know
        BEFORE calling `start_scan()` whether it would actually start a new
        scan -- as opposed to `get_progress().status == RUNNING`, which stays
        RUNNING for the no-op'd caller's own already-running scan too and so
        cannot distinguish "my scan is running" from "someone else's scan is
        running and mine never started" -- should check this property first.
        """
        return self._running

    def get_results(self, action_filter: Optional[str] = None) -> List[ScanResult]:
        """
        Get scan results with optional action filter.

        Args:
            action_filter: Filter by action (BUY, SELL, HOLD, WATCH, AVOID)
        """
        if action_filter:
            return [r for r in self._results if r.action == action_filter.upper()]
        return self._results

    async def _get_latest_session_id(self) -> Optional[str]:
        """
        Get the latest session ID efficiently.

        Uses the idx_scan_sessions_started_at index for O(1) lookup.

        Returns:
            Latest session ID or None if no sessions exist
        """
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM scan_sessions ORDER BY started_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_latest_adtv(self, stk_cd: str) -> Optional[float]:
        """T6(유동성 인지 사이징 캡) 폴백: 이 종목의 가장 최근 scan_results.
        factor_json에 저장된 adtv20_med(원, T3가 씀 — scanner.py의 발굴 수집
        루프 참조).

        `portfolio_agent._resolve_adtv`가 진입 직전 라이브 재계산에 실패했을
        때만 쓰인다. 승격(EOD) 당시 값이라 며칠 지난 값일 수 있지만, 캡이
        완전히 꺼지는(fail-open) 것보다는 낫다 — 리뷰 Important2(a): 애초
        `discovery_candidates`/`WatchedStock`에는 factor_json 저장 경로가
        없어(Task 6 조사) 폴백이 불가능하다고 판단했었으나, 실제로는
        `scan_results`(이 테이블, stk_cd 인덱스 idx_scan_results_stk_cd 有)에
        T3가 이미 저장하고 있었다.

        `AND factor_json IS NOT NULL` 필수(T8 재리뷰 봉합): `scan_results`에는
        discovery 외에 quick/LLM 스캔 writer(`_save_result_to_db`/
        `_save_results_batch`)도 있는데, 이쪽은 factor_json을 아예 채우지
        않아 NULL로 남는다. 필터 없이 `ORDER BY scanned_at DESC LIMIT 1`만
        쓰면, EOD discovery 스캔 다음날 아침 일반 스윕이 같은 종목에 NULL
        factor_json 행을 더 최신으로 얹는 순간 이 폴백이 조용히 무력화된다.

        never-raise: 조회/파싱 실패는 전부 None(호출자가 fail-open으로
        처리)."""
        try:
            await self._init_db()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT factor_json FROM scan_results WHERE stk_cd = ? "
                    "AND factor_json IS NOT NULL ORDER BY scanned_at DESC LIMIT 1",
                    (stk_cd,),
                ) as cursor:
                    row = await cursor.fetchone()
        except Exception as e:
            logger.warning("scan_results_adtv_lookup_failed", stk_cd=stk_cd, error=str(e))
            return None

        if not row or not row[0]:
            return None
        try:
            factor_json = json.loads(row[0])
            adtv = factor_json.get("adtv20_med")
            return float(adtv) if adtv is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    async def get_results_from_db(
        self,
        action_filter: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[ScanResult]:
        """
        Get scan results from database.

        Optimized query uses composite indexes:
        - idx_scan_results_session_action_scanned for filtered queries
        - idx_scan_results_session_scanned for unfiltered queries

        Args:
            action_filter: Filter by action
            session_id: Filter by scan session (None = latest session)
            limit: Maximum results to return
            offset: Offset for pagination
        """
        await self._init_db()

        # Resolve session_id upfront to avoid subquery in main SELECT
        target_session = session_id or await self._get_latest_session_id()
        if not target_session:
            return []

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            # Build optimized query (uses composite indexes)
            if action_filter:
                # Uses idx_scan_results_session_action_scanned
                query = """
                    SELECT * FROM scan_results
                    WHERE scan_session_id = ? AND action = ?
                    ORDER BY scanned_at DESC
                    LIMIT ? OFFSET ?
                """
                params = [target_session, action_filter.upper(), limit, offset]
            else:
                # Uses idx_scan_results_session_scanned
                query = """
                    SELECT * FROM scan_results
                    WHERE scan_session_id = ?
                    ORDER BY scanned_at DESC
                    LIMIT ? OFFSET ?
                """
                params = [target_session, limit, offset]

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            results = []
            for row in rows:
                results.append(ScanResult(
                    stk_cd=row["stk_cd"],
                    stk_nm=row["stk_nm"],
                    action=row["action"],
                    signal=row["signal"] or "",
                    confidence=row["confidence"] or 0.5,
                    summary=row["summary"] or "",
                    key_factors=row["key_factors"].split(",") if row["key_factors"] else [],
                    current_price=row["current_price"] or 0,
                    market_type=row["market_type"] or "",
                    scanned_at=datetime.fromisoformat(row["scanned_at"]) if row["scanned_at"] else datetime.now(),
                ))

            return results

    async def get_result_counts_from_db(
        self,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        Get action counts from database.

        Optimized to avoid subquery in main query.
        Uses idx_scan_results_session for filtering.

        Args:
            session_id: Filter by scan session (None = latest session)
        """
        await self._init_db()

        # Resolve session_id upfront to avoid subquery
        target_session = session_id or await self._get_latest_session_id()

        counts = {
            "buy_count": 0,
            "sell_count": 0,
            "hold_count": 0,
            "watch_count": 0,
            "avoid_count": 0,
            "total": 0,
        }

        if not target_session:
            return counts

        async with aiosqlite.connect(DB_PATH) as db:
            # Optimized query with direct session_id parameter
            query = """
                SELECT action, COUNT(*) as count
                FROM scan_results
                WHERE scan_session_id = ?
                GROUP BY action
            """

            async with db.execute(query, [target_session]) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                action = row[0]
                count = row[1]
                counts["total"] += count

                if action == "BUY":
                    counts["buy_count"] = count
                elif action == "SELL":
                    counts["sell_count"] = count
                elif action == "HOLD":
                    counts["hold_count"] = count
                elif action == "WATCH":
                    counts["watch_count"] = count
                elif action == "AVOID":
                    counts["avoid_count"] = count

            return counts

    async def get_scan_sessions(self, limit: int = 10) -> List[dict]:
        """Get recent scan sessions."""
        await self._init_db()

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT * FROM scan_sessions
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()

            return [dict(row) for row in rows]

    async def _send_telegram_notification(self, message: str):
        """Send Telegram notification."""
        try:
            from services.telegram import get_telegram_notifier
            telegram = await get_telegram_notifier()
            if telegram.is_ready:
                await telegram.send_message(message)
        except Exception as e:
            logger.warning("telegram_notification_failed", error=str(e))

    async def _send_scan_summary(self):
        """Send scan completion summary via Telegram."""
        duration = (self._progress.completed_at - self._progress.started_at).total_seconds() / 60

        message = f"""
✅ *백그라운드 분석 완료*

📊 *분석 결과*
• 총 분석: {self._progress.total_stocks}개
• 완료: {self._progress.completed}개
• 실패: {self._progress.failed}개

📈 *추천 분포*
• 매수(BUY): {self._progress.buy_count}개
• 매도(SELL): {self._progress.sell_count}개
• 보유(HOLD): {self._progress.hold_count}개
• 관망(WATCH): {self._progress.watch_count}개
• 회피(AVOID): {self._progress.avoid_count}개

⏱ 소요 시간: {duration:.1f}분

_결과는 Scanner Results 탭에서 확인하세요_
"""
        await self._send_telegram_notification(message.strip())

    async def check_monthly_reminder(self):
        """Check if monthly reminder is needed."""
        if self._progress.last_scan_date:
            days_since_scan = (datetime.now() - self._progress.last_scan_date).days
            if days_since_scan >= 30:
                await self._send_telegram_notification(
                    f"⏰ *분석 리마인더*\n\n"
                    f"마지막 전체 분석이 {days_since_scan}일 전입니다.\n"
                    f"전체 종목 분석을 권장합니다.\n\n"
                    f"_/scan 명령으로 분석 시작_"
                )
                return True
        return False


# Singleton instance
_scanner_instance: Optional[BackgroundScanner] = None


async def get_background_scanner() -> BackgroundScanner:
    """Get or create the background scanner singleton."""
    global _scanner_instance

    if _scanner_instance is None:
        _scanner_instance = BackgroundScanner()

    return _scanner_instance
