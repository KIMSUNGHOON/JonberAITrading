"""
Execution Coordinator

Orchestrates the trading workflow:
Analysis → Approval → Portfolio → Order → Monitor
"""

import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, date
from typing import Optional, List, Callable, Awaitable

from .models import (
    TradingMode,
    TradingState,
    AccountInfo,
    ManagedPosition,
    OrderRequest,
    OrderResult,
    OrderType,
    AllocationPlan,
    TradingAlert,
    AlertType,
    RiskParameters,
    PositionStatus,
    OrderSide,
    StopLossMode,
    ActivityType,
    ActivityLog,
    QueueStatus,
    QueuedTrade,
    AgentStatus,
    WatchedStock,
    WatchStatus,
)
from .portfolio_agent import PortfolioAgent
from .order_agent import OrderAgent, KiwoomRateLimiter
from .risk_monitor import RiskMonitor
from .market_hours import MarketType, get_market_hours_service, is_krx_open_cached
from .strategy import TradingStrategy
from .strategy_apply import apply_strategy_to_risk_params
from .pending_order_tracker import PendingOrderTracker, TrackedOrder
from .position_registration import register_fill_as_position, mirror_sell_to_position_manager
from .reconciler import reconcile
from .trade_log import record_trade_fill, record_kr_realized_pnl, wait_for_pending_trade_fill_writes
from .cadence import compute_watch_ttl
from .eod_snapshot import write_daily_snapshot
from .eod_orchestrator import run_eod_review
from .strategy_orchestrator import run_strategy_consensus
from .ledger_reconcile import reconcile_trade_ledger
from .eod_digest import _build_strategy_section, _build_discovery_section
from services.storage_service import get_storage_service
from app.config import get_settings
from services.background_scanner.scanner import ScanStatus, get_background_scanner
from services.discovery.orchestrator import run_discovery_pipeline

logger = logging.getLogger(__name__)


# DS-5: discovery EOD-chain scan-trigger wait, behind the DISCOVERY_ENABLED
# kill switch (app/config.py). SC-2 (docs/superpowers/specs/
# 2026-07-20-scan-reliability-design.md §2) made the wait dynamic — the old
# static 90-minute cap was a structural undercount (4276 stocks x 2 calls x
# 0.7s rate-limiter interval = ~99.8 theoretical minutes, before any safety
# margin, so a full-universe scan could exceed it on the API-call count
# alone). `_DISCOVERY_SCAN_TIMEOUT_SECONDS` below is now the FLOOR (never
# time out faster than the old cap, even for a tiny universe) and also the
# FALLBACK used when the universe size can't be read (see
# `_compute_discovery_scan_timeout_seconds`). Poll interval mirrors the
# brief's "실코드 수단이 폴링이면 5s 간격" instruction — BackgroundScanner
# exposes no completion event/future to await directly, only ScanStatus via
# the existing get_progress() (the same public surface
# app/api/routes/scanner.py's own status polling already uses).
# 자율 ADD가 유동성 천장에 막혀 0주가 됐을 때의 OrderResult.status.
# `None`(= 코디네이터 원장에 포지션 없음)과 반드시 구별돼야 한다 — 호출자
# (PositionManager._execute_add_position)가 None을 원장 불일치로 해석해
# 🚨 desync 통지를 보내기 때문이다. 유동성 차단은 원장 문제가 아니다.
ORDER_STATUS_REJECTED_LIQUIDITY_CAP = "rejected_liquidity_cap"

_DISCOVERY_SCAN_TIMEOUT_SECONDS = 5400.0
_DISCOVERY_SCAN_POLL_INTERVAL_SECONDS = 5.0

# SC-2 dynamic-timeout tuning constants — all from spec §2 SC-2, kept
# separate (not folded into one magic expression) so each has its own
# rationale on record:
#   - PER_STOCK: theoretical per-ticker API cost. Discovery collection makes
#     2 calls/stock (ka10001 + ka10081), both funneled through
#     rate_limiter.py's single shared 0.7s-interval query bucket -> 1.4s/
#     stock theoretical (measured ~1.46s live, ~4% overhead). Rounded up to
#     1.5s as the baseline the spec anchors the formula on.
#   - SAFETY_FACTOR: +30% margin over the theoretical estimate for network
#     jitter/retries so the timeout isn't shaving the estimate too close.
#   - BUFFER: fixed +600s (10 min) added after the per-stock estimate for
#     scan startup overhead and tail latency on the last few stocks.
#   - CAP: 4h hard ceiling — the close-to-open window is ~17.5h, so even the
#     largest plausible universe can't stall the EOD chain behind this call
#     indefinitely (spec §4 risk table).
_DISCOVERY_SCAN_TIMEOUT_PER_STOCK_SECONDS = 1.5
_DISCOVERY_SCAN_TIMEOUT_SAFETY_FACTOR = 1.3
_DISCOVERY_SCAN_TIMEOUT_BUFFER_SECONDS = 600.0
_DISCOVERY_SCAN_TIMEOUT_CAP_SECONDS = 14400.0


def _compute_discovery_scan_timeout_seconds(universe: Optional[int]) -> float:
    """SC-2: universe-proportional discovery scan timeout.

    ``timeout = clamp(universe * 1.5 * 1.3 + 600, floor=_DISCOVERY_SCAN_
    TIMEOUT_SECONDS(5400), cap=_DISCOVERY_SCAN_TIMEOUT_CAP_SECONDS(14400))``
    (spec §2 SC-2, verbatim). `universe` is expected to be the scanner's own
    `get_progress().total_stocks`, read right after the post-start_scan
    RUNNING confirmation (see `_run_discovery_scan`) — by that point
    `BackgroundScanner.start_scan()` has already synchronously populated
    `total_stocks = len(stock_list)` on `self._progress` before returning
    (scanner.py — set well before the scan task itself is created), so no
    extra poll/wait for it is needed.

    Falls back to the static floor/cap-independent `_DISCOVERY_SCAN_
    TIMEOUT_SECONDS` when `universe` couldn't be read (None or <= 0) — same
    behavior as the pre-SC-2 fixed timeout for that case.
    """
    if not universe or universe <= 0:
        fallback = _DISCOVERY_SCAN_TIMEOUT_SECONDS
        logger.info(
            "[Coordinator] discovery_scan_timeout_computed universe=%r "
            "raw_seconds=None clamped_seconds=%s (fallback: universe "
            "unavailable)",
            universe,
            fallback,
        )
        return fallback

    raw_seconds = (
        universe
        * _DISCOVERY_SCAN_TIMEOUT_PER_STOCK_SECONDS
        * _DISCOVERY_SCAN_TIMEOUT_SAFETY_FACTOR
        + _DISCOVERY_SCAN_TIMEOUT_BUFFER_SECONDS
    )
    clamped_seconds = max(
        _DISCOVERY_SCAN_TIMEOUT_SECONDS,
        min(_DISCOVERY_SCAN_TIMEOUT_CAP_SECONDS, int(raw_seconds)),
    )
    logger.info(
        "[Coordinator] discovery_scan_timeout_computed universe=%s "
        "raw_seconds=%.1f clamped_seconds=%s",
        universe,
        raw_seconds,
        clamped_seconds,
    )
    return float(clamped_seconds)


# Actions that grow exposure map to a BUY order; everything else reduces it and
# maps to SELL. An ADD mis-mapped to SELL reverses an autonomous add-to-position
# into a liquidation — audit finding A1 (2026-07-12). Mirrors the gate's
# POSITION_INCREASING_ACTIONS so side and cap logic stay in agreement.
_BUY_SIDE_ACTIONS = {"BUY", "ADD"}


def _order_side_for_action(action: str) -> OrderSide:
    """Resolve the order side for a trade action.

    BUY/ADD increase exposure → BUY side. SELL/REDUCE decrease it → SELL side.
    """
    return OrderSide.BUY if action in _BUY_SIDE_ACTIONS else OrderSide.SELL


class ExecutionCoordinator:
    """
    Central coordinator for the auto-trading system.

    Orchestrates:
    1. Trade approval → Portfolio allocation
    2. Portfolio allocation → Order execution
    3. Order execution → Risk monitoring

    Provides unified interface for:
    - Starting/stopping auto-trading
    - Handling approved trades
    - Managing alerts and user actions
    """

    def __init__(
        self,
        kiwoom_client=None,
        redis_client=None,
        risk_params: Optional[RiskParameters] = None,
    ):
        """
        Initialize Execution Coordinator.

        Args:
            kiwoom_client: Kiwoom API client
            redis_client: Redis client for rate limiting
            risk_params: Risk parameters
        """
        self.risk_params = risk_params or RiskParameters()

        # Initialize agents
        self.portfolio_agent = PortfolioAgent(self.risk_params)
        self.order_agent = OrderAgent(
            kiwoom_client=kiwoom_client,
            rate_limiter=KiwoomRateLimiter(redis_client),
        )
        self.risk_monitor = RiskMonitor(
            risk_params=self.risk_params,
            price_fetcher=self._get_current_price,
            alert_sender=self._on_alert,
            order_executor=self._execute_order_from_monitor,
            price_sink=self._on_price_update,
        )

        # State
        self._state = TradingState(risk_params=self.risk_params)
        self._kiwoom = kiwoom_client

        # Market hours service
        self._market_hours = get_market_hours_service()

        # Callbacks
        self._alert_callback: Optional[Callable[[TradingAlert], Awaitable[None]]] = None
        self._state_callback: Optional[Callable[[TradingState], Awaitable[None]]] = None

        # Strategy
        self._strategy: Optional[TradingStrategy] = None

        # Open-queue scheduler (R5-P1): auto-process the queue on the KRX
        # closed→open transition while the system is already running.
        self._market_was_open = False
        self._queue_scheduler_task: Optional[asyncio.Task] = None
        self._queue_scheduler_interval = 30.0

        # Watch-list price refresh loop (monitoring-cadence-tuning arc, MAIN
        # BODY): WatchedStock.current_price for ACTIVE entries was only ever
        # refreshed at start() and on each trade approval (via
        # _refresh_account_info -> _reprice_positions), never periodically —
        # entry-candidate prices went stale for the whole session. Same
        # lifecycle shape as _queue_scheduler_task above.
        self._watch_refresh_task: Optional[asyncio.Task] = None

        # E2-2: market-gate last-known state for _refresh_watch_prices, for
        # the transition-only log helper below (None = not yet observed
        # this process). Same no-op-cycle pattern as E2-1 (agent_chat
        # coordinator/position_manager) and RiskMonitor's E2-2 gate. Does
        # NOT touch the queue scheduler / close-edge / fill-polling /
        # reconciler loops below (out of scope for this gate).
        self._market_gate_closed: Optional[bool] = None
        # Re-entrancy guard: process_trade_queue is now reachable from start(),
        # the scheduler, and manual API calls — concurrent runs would double-
        # execute PENDING/PROCESSING trades (review #6).
        self._processing_queue = False

        # Automatic persistence is only active within a session (start→stop), so
        # a coordinator built in a unit test does not write to the shared DB. The
        # explicit _persist_state/_restore_state helpers ignore this flag.
        self._persistence_active = False

        # Daily trade count — 이 카운트가 속한 달력일(in-memory). 자정을 넘겨
        # 계속 도는 프로세스는 `_state.daily_trades_count` 하나만으로는 그게
        # 어제 몫인지 알 길이 없어 상한이 나날이 좁아지다 결국 매매가 전부
        # 막힌다(2026-08-04 라이브 사고). `_maybe_reset_daily_trades()`가 읽기/
        # 증가/영속 앞에서 이 값과 오늘을 매번 비교해 lazily 되돌린다 —
        # `agents/llm/router.py`의 `_maybe_reset_day()`(OpenRouter 일일 예산)와
        # 동일 패턴.
        self._daily_count_day: date = date.today()

        # 체결 통지 태스크 강참조. create_task 결과를 붙들지 않으면 GC가
        # 태스크를 수거해 통지가 조용히 사라진다.
        self._notify_tasks: set = set()

        # F3 (audit 2026-07-13): a BUY that didn't (fully) fill at placement
        # time previously vanished from tracking — the coordinator only
        # registered a position on the filled portion, so any broker-side
        # post-fill went unwatched by every defense engine. Tracks the
        # remainder and reconciles it against ka10076 on the scheduler tick.
        self.fill_tracker = PendingOrderTracker()

        # F3 t6: counts scheduler ticks so the broker-local reconciler runs
        # every 2nd tick (60s at the default 30s interval) instead of every
        # tick — it does a full get_account_balance() call plus per-ticker
        # PositionManager lookups, heavier than the fill-tracker poll.
        self._reconcile_tick_count = 0

        # S-2 review fix (dual-engine concurrent defensive-exit race): two
        # independent monitoring engines — RiskMonitor (1s tick, via
        # `_execute_order_from_monitor`) and PositionManager (30s tick, via
        # `_execute_close_position` -> `_close_position`) — can each detect
        # the SAME breached stop and race to close the SAME position. Both
        # read `_state.positions` for the CURRENT quantity, then `await` an
        # order submission; if the second engine's read happens before the
        # first engine's fill has been reconciled back into `_state.positions`
        # (`_apply_sell_fill`), it still sees the pre-fill quantity and
        # submits a SECOND full-size SELL — a real double-liquidation (the
        # paper broker fills unconditionally, with no holdings check).
        #
        # Ticker-scoped in-flight guard, not an asyncio.Lock: a Lock would
        # deadlock the moment `_reduce_position` delegates to
        # `_close_position` for the SAME ticker within the SAME call stack
        # (re-entrant acquire), and "lock across an await" invites exactly
        # the kind of subtle cross-coroutine ordering bugs this fix exists to
        # eliminate. A plain `set` needs none of that: on a single-threaded
        # asyncio event loop, a membership check followed immediately by an
        # add — with NO `await` in between — cannot be interleaved by any
        # other coroutine, so `_acquire_defensive_exit_guard` is atomic by
        # construction without any explicit synchronization primitive.
        self._defensive_exit_inflight: set = set()

    def _acquire_defensive_exit_guard(self, ticker: str) -> bool:
        """Atomically claim `ticker` for an in-flight defensive SELL exit.

        MUST be called with no `await` between the membership check and the
        `.add()` below — that adjacency (not a lock) is what makes this
        atomic on the single-threaded event loop. Returns True (guard
        acquired, caller may proceed to place the order) if `ticker` was not
        already in flight, or False (caller must skip as a no-op) if another
        SELL execution already owns this ticker's exit right now.

        Pure `set` membership/insert — no I/O, no exception vector — so a
        SELL order can never be blocked by a failure IN the guard itself,
        only by a genuine concurrent in-flight exit for the same ticker.
        """
        if ticker in self._defensive_exit_inflight:
            logger.warning(
                f"[Coordinator] defensive_exit_skipped_inflight: {ticker} "
                f"already has a SELL exit in flight — skipping duplicate "
                f"(first execution owns this exit; a failed first attempt "
                f"is naturally retried on the next monitor tick)"
            )
            return False
        self._defensive_exit_inflight.add(ticker)
        return True

    def _release_defensive_exit_guard(self, ticker: str) -> None:
        """Release `ticker`'s in-flight defensive-exit claim. Always called
        from a `finally` block by the acquiring call site so a raised
        exception during order placement can never leave a ticker
        permanently stuck as "in flight" (a `.discard()` on a missing key is
        a no-op, so this is also safe to call defensively)."""
        self._defensive_exit_inflight.discard(ticker)

    # -------------------------------------------
    # Activity Logging
    # -------------------------------------------

    def _log_activity(
        self,
        activity_type: ActivityType,
        message: str,
        agent: str = "system",
        ticker: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        """Log an activity to the state's activity log."""
        activity = ActivityLog(
            activity_type=activity_type,
            agent=agent,
            ticker=ticker,
            message=message,
            details=details,
        )
        # Keep only last 100 activities
        self._state.activity_log.append(activity)
        if len(self._state.activity_log) > 100:
            self._state.activity_log = self._state.activity_log[-100:]

        logger.info(f"[{agent.upper()}] {message}")

    def get_activity_log(self, limit: int = 50) -> List[ActivityLog]:
        """Get recent activity log entries."""
        return self._state.activity_log[-limit:]

    # -------------------------------------------
    # Lifecycle
    # -------------------------------------------

    async def start(self, drain_queue: bool = True, boot_resume: bool = False):
        """Start the auto-trading system.

        Args:
            drain_queue: 장이 열려 있고 큐가 비어 있지 않을 때 즉시
                process_trade_queue()를 돌릴지. 수동 /trading/start는
                True(기존 동작)이고, **부팅 자동 재개만 False**를 넘긴다 —
                QueuedTrade에 만료가 없고 process_trade_queue에 신선도
                검사가 없어서, 사람이 앞에 없는 장중 재시작이 몇 시간 묵은
                가격으로 주문을 낼 수 있다. 방어(손절/익절)는 이 값과
                무관하게 즉시 살아난다.
            boot_resume: 이 시작이 부팅 자동 재개인지. 활동 로그를 수동
                시작과 구별하기 위한 표식일 뿐 동작을 바꾸지 않는다.
        """
        logger.info("[Coordinator] Starting auto-trading system")

        # Fetch initial account info
        await self._refresh_account_info()

        # Restore restart-critical state (positions+stops, queue, daily count)
        # BEFORE the monitor starts so recovered stops are watched immediately.
        await self._restore_state()

        # Phase3: restore the active strategy from its revision pointer.
        # Independent of _restore_state (its own try/except) — a strategy
        # restore failure must never block the state restore above.
        await self._restore_strategy()

        # Update state — persist 활성화보다 **앞**이어야 한다. 순서가
        # 반대면 그 사이에 트리거된 persist가 직전 mode(보통 STOPPED)를
        # 저장하고, 다음 부팅의 자동 방어 복원이 그 값을 보고 재개를
        # 건너뛴다(2026-07-29 재시작 안전).
        self._state.mode = TradingMode.ACTIVE
        self._state.started_at = datetime.now()

        # Activate persistence BEFORE the startup queue drain below, so trades
        # executed at open are persisted — otherwise a crash before the next
        # persist re-executes them and loses their stop defense (review #3).
        self._persistence_active = True

        # Start risk monitor
        await self.risk_monitor.start()

        # 재시작 안전(2026-07-30): 방어(risk_monitor)가 실제로 켜진 뒤에야
        # mode=active를 디스크에 남긴다 -- 그 전에 두면 risk_monitor.start()
        # 실패 시 "방어는 안 켜졌는데 블롭은 active"인 거짓 기록이 남는다.
        # 이 persist가 없으면(REGRESSION, 라이브에서 실측: 장 마감 중
        # POST /trading/start 후 블롭 mode가 계속 null) mutation 훅
        # (_schedule_persist)이나 stop/pause/resume의 persist만으로는 부족하다
        # -- 장중 뮤테이션이 하나도 없으면 이 시작을 기록할 다른 경로가 없어서,
        # 다음 재시작의 resume_if_persisted()가 영원히 건너뛴다.
        # _persistence_active는 이미 True, _restore_state()도 이미 끝난
        # 뒤라 메모리 스냅샷이 실제 내용이다 -- 부분 쓰기(_persist_fields)가
        # 아니라 전체 _persist_state()가 맞다. never-raise라 start()를 깰
        # 수 없다.
        await self._persist_state()

        self._log_activity(
            ActivityType.SYSTEM_START,
            (
                f"Auto-trading system {'auto-resumed after restart' if boot_resume else 'started'}. "
                f"Account: ₩{self._state.account.total_equity:,.0f}"
            ),
            details={
                "account": self._state.account.model_dump(),
                "boot_resume": boot_resume,
            },
        )

        await self._notify_state_change()

        # Process any pending trades in queue (if market is open)
        market_session = self._market_hours.get_market_session(MarketType.KRX)
        if drain_queue and market_session.is_open and self.get_trade_queue():
            logger.info("[Coordinator] Processing pending trade queue after start")
            await self.process_trade_queue()
        elif not drain_queue:
            logger.info(
                "[Coordinator] Boot resume — skipping startup queue drain "
                "(stale-price guard)"
            )

        # Seed the scheduler's edge state and start watching for the KRX
        # closed→open transition so a queue built overnight processes at open.
        self._market_was_open = market_session.is_open
        if self._queue_scheduler_task is None or self._queue_scheduler_task.done():
            self._queue_scheduler_task = asyncio.create_task(
                self._queue_scheduler_loop()
            )

        # Start the periodic watch-list price refresh loop (same idempotent
        # guard shape as the queue scheduler above).
        if self._watch_refresh_task is None or self._watch_refresh_task.done():
            self._watch_refresh_task = asyncio.create_task(
                self._watch_refresh_loop()
            )

    async def resume_if_persisted(self) -> bool:
        """부팅 시 호출 — 마지막으로 저장된 mode가 active/paused면 방어를
        되살린다. 실제로 재개했으면 True, no-op이면 False.

        복원 기계 자체는 start() 안의 _restore_state()가 이미 갖고 있다.
        이 메서드가 하는 일은 "되살려도 되는가"의 판단뿐이다.

        규칙:
          active → start(drain_queue=False)
          paused → start(drain_queue=False) 후 pause() — pause는 감시를
                   유지하므로 손절은 살고 신규 진입만 잠긴다
          stopped / mode 필드 없음 / 블롭 없음 → 아무것도 안 함

        mode 필드가 없는 블롭(이 기능 이전에 저장된 것)에서 재개하지 않는
        것은 의도다 — 추측해서 되살리는 것보다 안전하다. 배포 후 첫 수동
        start()가 mode를 기록하고, 그 다음 재시작부터 자동으로 동작한다.

        예외는 삼키지 않는다. 호출자(app.main._boot_auto_resume)가 잡아서
        로그와 Telegram에 남긴다 — 방어를 못 켠 것은 조용히 넘어갈 일이
        아니다.
        """
        from services.storage_service import get_storage_service

        storage = await get_storage_service()
        blob = await storage.get_app_setting(self._STATE_KEY)
        if not blob:
            logger.info("[Coordinator] Boot resume: no persisted state")
            return False

        data = json.loads(blob) or {}
        mode = data.get("mode")
        if mode not in (TradingMode.ACTIVE.value, TradingMode.PAUSED.value):
            logger.info(f"[Coordinator] Boot resume skipped (mode={mode!r})")
            # RECOMMENDATION 8 (2026-07-29): this no-op is correct and stays
            # correct -- a blob without a valid mode should never guess its
            # way into resuming. But it lands the operator in exactly the
            # pre-branch hole (positions with no defense) with only an info
            # log, and it fires on THIS branch's very first deploy (no blob
            # has a "mode" field yet). If positions are sitting in the same
            # blob we just parsed, say so on the phone.
            await self._alert_defense_not_armed(data)
            return False

        logger.info(f"[Coordinator] Boot resume: restoring mode={mode}")
        await self.start(drain_queue=False, boot_resume=True)
        if mode == TradingMode.PAUSED.value:
            await self.pause("restart resume")
        return True

    async def _alert_defense_not_armed(self, data: dict) -> None:
        """RECOMMENDATION 8 (2026-07-29): resume_if_persisted()이 재개를
        건너뛰었는데 같은 블롭에 보유 포지션이 남아 있으면, 방어가 꺼진 채
        부팅됐다는 사실을 알린다. Best-effort — 알림 실패가 부팅을 막지
        않는다."""
        positions = data.get("positions") or []
        if not positions:
            return
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_system_status(
                    "error",
                    f"부팅 자동 방어 복원 건너뜀 — 보유 포지션 {len(positions)}건이 "
                    f"무방비 상태입니다. 수동으로 POST /api/trading/start 를 "
                    f"실행하세요.",
                )
        except Exception as e:
            logger.error(f"[Coordinator] Failed to alert unarmed defense: {e}")

    async def stop(self):
        """Stop the auto-trading system."""
        logger.info("[Coordinator] Stopping auto-trading system")

        await self.risk_monitor.stop()
        self._state.mode = TradingMode.STOPPED

        # Stop the open-queue scheduler.
        if self._queue_scheduler_task is not None:
            self._queue_scheduler_task.cancel()
            self._queue_scheduler_task = None

        # Stop the watch-list price refresh loop.
        if self._watch_refresh_task is not None:
            self._watch_refresh_task.cancel()
            self._watch_refresh_task = None

        # Persist mode on shutdown -- unconditional (IMPORTANT 3, 2026-07-29).
        # A stop() on a coordinator that never start()ed in THIS process
        # (e.g. the very first API call after a fresh boot being
        # /trading/stop) must still write mode=stopped, or a stale
        # mode=active left over from a previous session survives in the
        # blob and the next boot's resume_if_persisted() arms trading the
        # operator explicitly switched off.
        #
        # 단, 전체 스냅샷(_persist_state)은 _persistence_active가 True일
        # 때만 부른다 -- False면 이 프로세스는 _restore_state()를 돈 적이
        # 없어서 메모리 상 positions/trade_queue/watch_list가 블롭의 실제
        # 내용이 아니라 전부 빈 기본값이고, 그대로 직렬화하면 진짜 데이터를
        # 지워 버린다(REGRESSION, 2026-07-29 리뷰). mode만은 여전히
        # 영속돼야 하므로 그 경우엔 `_persist_fields()`로 mode 키만
        # read-modify-write한다. 둘 다 never-raise라 셧다운을 깨지 않는다.
        if self._persistence_active:
            await self._persist_state()
        else:
            await self._persist_fields(mode=self._mode_value())
        self._persistence_active = False

        self._log_activity(
            ActivityType.SYSTEM_STOP,
            "Auto-trading system stopped",
        )

        await self._notify_state_change()

    async def pause(self, reason: str = "Manual pause"):
        """Pause auto-trading."""
        await self.risk_monitor.pause(reason)
        self._state.mode = TradingMode.PAUSED

        self._log_activity(
            ActivityType.SYSTEM_PAUSE,
            f"Trading paused: {reason}",
            details={"reason": reason},
        )

        await self._notify_state_change()

        # IMPORTANT 3 (2026-07-29): persist mode immediately, don't wait for
        # some unrelated mutator to happen to fire a persist. Otherwise:
        # operator pauses at 10:00 to stop new entries -> process dies at
        # 10:05 with no intervening persist -> blob still says "active" ->
        # boot resume calls start(drain_queue=False), NOT pause() ->
        # autonomous new entries unlock against the operator's explicit
        # intent on a live account.
        #
        # `_persistence_active`가 False(이 프로세스에서 start()를 거친 적
        # 없음)면 전체 `_persist_state()` 대신 mode 키만 갱신한다 -- 이유는
        # stop()의 동일 분기 주석 참고(REGRESSION, 2026-07-29 리뷰). 둘 다
        # never-raise.
        if self._persistence_active:
            await self._persist_state()
        else:
            await self._persist_fields(mode=self._mode_value())

    async def resume(self):
        """Resume auto-trading."""
        await self.risk_monitor.resume()
        self._state.mode = TradingMode.ACTIVE

        self._log_activity(
            ActivityType.SYSTEM_RESUME,
            "Trading resumed",
        )

        await self._notify_state_change()

        # IMPORTANT 3 (2026-07-29): same reasoning as pause() above -- mode
        # must be durable the moment it changes, not only when some other
        # mutator happens to persist. Placed before the queue drain below so
        # the mode is on disk even if process_trade_queue hangs or fails.
        #
        # `_persistence_active`가 False면 mode 키만 갱신한다 -- stop()의
        # 동일 분기 주석 참고(REGRESSION, 2026-07-29 리뷰). 둘 다 never-raise.
        if self._persistence_active:
            await self._persist_state()
        else:
            await self._persist_fields(mode=self._mode_value())

        # Process any pending trades in queue (if market is open)
        market_session = self._market_hours.get_market_session(MarketType.KRX)
        if market_session.is_open and self.get_trade_queue():
            logger.info("[Coordinator] Processing pending trade queue after resume")
            await self.process_trade_queue()

    # -------------------------------------------
    # Trade Execution Flow
    # -------------------------------------------

    async def on_trade_approved(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        action: str,  # "BUY" or "SELL"
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        risk_score: int,
        quantity_override: Optional[int] = None,
        autonomous: bool = False,
        queue_id: Optional[str] = None,
    ) -> AllocationPlan:
        """
        Handle an approved trade from the analysis system.

        autonomous=True marks trades originated by an autonomy engine (R3):
        if such a trade gets QUEUED, the queue processor re-checks the shared
        autonomy gate before executing it — a mode flip to HITL or a tripped
        limit between queueing and execution must win.

        Args:
            session_id: Analysis session ID
            ticker: Stock ticker
            stock_name: Stock name
            action: BUY or SELL
            entry_price: Proposed entry price
            stop_loss: Stop-loss price
            take_profit: Take-profit price
            risk_score: Risk score from analysis (1-10)
            quantity_override: Optional manual quantity override
            queue_id: The originating QueuedTrade.id, when this call comes
                from `_process_trade_queue_inner` (F3) — threaded onto any
                fill-tracker registration below so a later post-fill can
                annotate the queue entry it came from.

        Returns:
            AllocationPlan with execution details
        """
        self._log_activity(
            ActivityType.TRADE_APPROVED,
            f"Trade approved: {action} {stock_name or ticker} @ ₩{entry_price:,.0f} (risk: {risk_score})",
            agent="system",
            ticker=ticker,
            details={
                "session_id": session_id,
                "action": action,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
            },
        )

        # Update portfolio agent status with trade details
        self._update_agent_status(
            "portfolio",
            AgentStatus.WORKING,
            task=f"Calculating allocation for {action} {stock_name or ticker}",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
            },
        )

        # Check market hours (KRX for Korean stocks)
        market_session = self._market_hours.get_market_session(MarketType.KRX)

        # Determine if we should queue the trade
        should_queue = False
        queue_reason = ""

        if not market_session.is_open:
            should_queue = True
            queue_reason = f"Market closed: {market_session.message}"
        elif self._state.mode == TradingMode.STOPPED:
            should_queue = True
            queue_reason = "Trading system not started - trade will execute when started"
        elif self._state.mode == TradingMode.PAUSED:
            should_queue = True
            queue_reason = "Trading paused - trade will execute when resumed"

        # Queue trade if needed
        if should_queue:
            queued_trade = self.add_to_queue(
                session_id=session_id,
                ticker=ticker,
                stock_name=stock_name,
                action=action,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_score=risk_score,
                reason=queue_reason,
                autonomous=autonomous,
                quantity=quantity_override,
            )

            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=_order_side_for_action(action),
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=f"Trade queued: {queue_reason} (Queue ID: {queued_trade.id})",
            )

        # Check daily trade limit
        self._maybe_reset_daily_trades()
        if self._state.daily_trades_count >= self.risk_params.max_daily_trades:
            rationale = f"Daily trade limit reached ({self._state.daily_trades_count}/{self.risk_params.max_daily_trades})"
            self._log_activity(
                ActivityType.TRADE_REJECTED,
                rationale,
                agent="system",
                ticker=ticker,
            )
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=_order_side_for_action(action),
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        # Refresh account info
        await self._refresh_account_info()

        # Calculate allocation
        side = _order_side_for_action(action)

        # C1(유동성 인지): 주문 직전 ADTV 재계산 — 발굴(EOD)~진입(수일 후) 사이
        # 유동성이 바뀔 수 있어 최신 일봉으로 다시 구한다. BUY에서만 의미
        # 있다(SELL은 _calculate_max_position_value를 타지 않는다).
        # never-raise: 실패하면 None -> apply_liquidity_cap이 캡
        # 미적용(fail-open)으로 처리한다.
        adtv = None
        if side == OrderSide.BUY:
            adtv = await self.portfolio_agent._resolve_adtv(ticker)

        allocation = self.portfolio_agent.calculate_allocation(
            account=self._state.account,
            ticker=ticker,
            stock_name=stock_name,
            side=side,
            entry_price=entry_price,
            risk_score=risk_score,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_positions=self._state.positions,
            adtv=adtv,
        )

        # H2: quantity_override를 allocation 캡(calculate_allocation이 산정한 R-사이징/
        # min_cash/max_stock 상한 = allocation.quantity)으로 클램프한다. override가
        # 캡을 통째 덮어써 캡을 우회하지 못하게 — override≤캡이면 그대로, 초과면 캡.
        if quantity_override and quantity_override > 0:
            capped = min(quantity_override, allocation.quantity)
            allocation.quantity = capped
            allocation.estimated_amount = capped * entry_price
            allocation.rationale += (
                f" (quantity override {quantity_override} clamped to {capped})"
                if capped < quantity_override
                else f" (quantity override: {quantity_override})"
            )

        # Log allocation decision
        self._log_activity(
            ActivityType.ALLOCATION_CALCULATED,
            f"Allocation: {allocation.quantity} shares @ ₩{entry_price:,.0f} = ₩{allocation.estimated_amount:,.0f} ({allocation.position_pct:.1f}%)",
            agent="portfolio",
            ticker=ticker,
            details={
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "estimated_amount": allocation.estimated_amount,
                "position_pct": allocation.position_pct,
                "rationale": allocation.rationale,
            },
        )

        # Update portfolio agent with allocation result
        self._update_agent_status(
            "portfolio",
            AgentStatus.IDLE,
            action=f"Allocated {allocation.quantity} shares",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_score": risk_score,
                "estimated_amount": allocation.estimated_amount,
                "position_pct": allocation.position_pct,
            },
            last_result={
                "success": allocation.quantity > 0,
                "message": allocation.rationale,
                "quantity": allocation.quantity,
                "estimated_amount": allocation.estimated_amount,
            },
        )
        self._complete_agent_task("portfolio", success=allocation.quantity > 0)

        if allocation.quantity <= 0:
            self._log_activity(
                ActivityType.TRADE_REJECTED,
                f"Allocation rejected: {allocation.rationale}",
                agent="portfolio",
                ticker=ticker,
            )
            return allocation

        # Execute rebalancing orders first
        #
        # E1-4: a rebalance order is a SYSTEM-computed SELL of an UNRELATED
        # position (`portfolio_agent._check_rebalancing_needed` decided it, to
        # free up room for the trade that WAS approved) — the human approved
        # the PRIMARY trade, not trimming a different position. That makes it
        # the same category as a defensive stop-loss/take-profit trigger
        # (`_execute_order_from_monitor`) or an autonomous full close
        # (PositionManager._execute_close_position, R5-P0 A2): it must pass
        # the shared autonomy gate UNCONDITIONALLY, regardless of whether
        # THIS trade's own `autonomous` flag is set. A denial skips only that
        # one rebalance item and logs it — the primary order below still
        # proceeds (mirrors A2's "skip, don't abort" shape), and the fill is
        # then reconciled through the same `_apply_sell_fill`/
        # `_register_unfilled_sell` choke points every other SELL site uses
        # (previously this loop only placed the order and never recorded the
        # ledger row or decremented the local position for it at all).
        from services.autonomy import check_autonomy

        for rebalance_order in allocation.rebalance_orders:
            # N1 review fix (survival discipline, 6th SELL entry point): this
            # rebalance-sell loop is a SIXTH source of SELL orders for a
            # ticker — an UNRELATED position trimmed to free room for the
            # trade actually approved — and can race a defensive exit
            # (RiskMonitor/PositionManager) for the SAME ticker exactly like
            # the other 5 guarded SELL sites (`_execute_order_from_monitor`/
            # `_close_position`/`_reduce_position`/`on_trade_approved`'s own
            # SELL/REDUCE main path below/`handle_alert_action`'s
            # EXECUTE_STOP_LOSS/EXECUTE_TAKE_PROFIT) — see `_close_position`'s
            # docstring for the full dual-engine race rationale. Acquired
            # BEFORE the `await check_autonomy` below (not after) so the
            # in-flight claim closes the race window from the earliest
            # possible point, same as `_execute_order_from_monitor`'s
            # acquire-then-gate-check ordering. Guard-denied: skip ONLY this
            # rebalance item (the loop continues to the next rebalance order,
            # and the primary approved order below still proceeds untouched)
            # — the other engine's exit already owns this ticker's exit.
            if not self._acquire_defensive_exit_guard(rebalance_order.ticker):
                logger.warning(
                    f"[Coordinator] rebalance_sell_skipped_inflight: "
                    f"{rebalance_order.ticker} already has a SELL exit in "
                    f"flight — skipping this rebalance order (primary trade "
                    f"unaffected)"
                )
                self._log_activity(
                    ActivityType.TRADE_REJECTED,
                    f"Rebalance order skipped — defensive exit already in "
                    f"flight for {rebalance_order.ticker}",
                    agent="system",
                    ticker=rebalance_order.ticker,
                )
                continue

            try:
                gate = await check_autonomy(
                    "kiwoom",
                    action="SELL",
                    quantity=rebalance_order.quantity,
                    entry_price=rebalance_order.price,
                )
                if not gate.allowed:
                    logger.warning(
                        f"[Coordinator] Rebalance sell blocked by gate: "
                        f"{rebalance_order.ticker} check={gate.check} reason={gate.reason}"
                    )
                    self._log_activity(
                        ActivityType.TRADE_REJECTED,
                        f"Rebalance order blocked by autonomy gate: {rebalance_order.ticker} "
                        f"({gate.reason})",
                        agent="system",
                        ticker=rebalance_order.ticker,
                    )
                    continue

                # NOTE (pre-existing bug, fixed in passing): OrderRequest has
                # `use_enum_values=True`, so `.side` is already a plain str
                # ("sell") by validation time, not an OrderSide member — the old
                # `.side.value` here raised AttributeError the moment this line
                # actually ran (every other `.side` use in this file already
                # compares against the plain string, e.g. line ~2411
                # `order.side == "sell"`).
                self._log_activity(
                    ActivityType.ORDER_PLACED,
                    f"Rebalance order: {rebalance_order.side} {rebalance_order.quantity} shares",
                    agent="order",
                    ticker=rebalance_order.ticker,
                )
                # Capture the position BEFORE the fill reconciles it (matches
                # _execute_order_from_monitor's pattern) — _apply_sell_fill may
                # reduce/remove it from _state.positions, but
                # _register_unfilled_sell only needs stock_name/
                # analysis_session_id/risk_score off the (still-valid) reference.
                rebalance_position = next(
                    (p for p in self._state.positions if p.ticker == rebalance_order.ticker),
                    None,
                )
                rebalance_result = await self._execute_order(rebalance_order)
                self._apply_sell_fill(
                    rebalance_order.ticker,
                    rebalance_result.filled_quantity,
                    order=rebalance_order,
                    result=rebalance_result,
                )
                # A partial/unfilled remainder still has broker-side exposure —
                # track it the same way every other SELL site does (E1-1/E1-3).
                self._register_unfilled_sell(
                    rebalance_order.ticker, rebalance_position, rebalance_order, rebalance_result
                )
            finally:
                self._release_defensive_exit_guard(rebalance_order.ticker)

        # Execute main order
        order = OrderRequest(
            ticker=ticker,
            stock_name=stock_name,
            side=side,
            quantity=allocation.quantity,
            price=entry_price,
            # S-3 (survival discipline): a SELL/REDUCE decision reaching this
            # entry point (e.g. an agent-chat discussion outcome) is a
            # liquidation, same category as the other defensive-exit sites
            # (_close_position/_reduce_position/_execute_order_from_monitor)
            # — submit MARKET so it reports the true fill in a gap/crash.
            # BUY/ADD stays LIMIT (global invariant, unaffected by `side`
            # since it's only SELL here).
            order_type=OrderType.MARKET if side == OrderSide.SELL else OrderType.LIMIT,
            session_id=session_id,
            reason=f"Trade approval (risk: {risk_score})",
        )

        # U3 (사이징 계보, 2026-08-05): 이 지점이 계보(allocation.sizing_
        # lineage)와 그 계보가 귀속될 decision_id(order.session_id ==
        # agent-chat 경로에서 agent_chat_decisions.id)가 함께 갖춰지는
        # 유일한 자리다. 주문이 실제로 체결되는지와 무관하게(사이징 계산
        # 자체는 체결 전에 이미 끝났다) 여기서 즉시 기록한다. 매칭되는
        # 행이 없으면(수동 승인 등 agent-chat 기원이 아닌 경로) 조용히
        # no-op — update_decision_label과 같은 관례. 저장 실패가 주문
        # 경로를 절대 끊지 않도록 이 호출 자체도 try/except로 감싼다
        # (StorageService 메서드 내부 가드와 별개의 방어선).
        if allocation.sizing_lineage:
            try:
                storage = await get_storage_service()
                await storage.update_decision_sizing_lineage(
                    order.session_id, allocation.sizing_lineage
                )
            except Exception as e:
                logger.warning(
                    f"[Coordinator] sizing lineage 저장 실패 "
                    f"(주문 경로에는 영향 없음): {e}"
                )

        self._log_activity(
            ActivityType.ORDER_PLACED,
            f"Order placed: {action} {allocation.quantity} {stock_name or ticker} @ ₩{entry_price:,.0f}",
            agent="order",
            ticker=ticker,
            details={
                "side": action,
                "quantity": allocation.quantity,
                "price": entry_price,
            },
        )

        # Update order agent status
        self._update_agent_status(
            "order",
            AgentStatus.WORKING,
            task=f"Executing {action} {allocation.quantity} {stock_name or ticker}",
            processing_stock=ticker,
            processing_stock_name=stock_name,
            trade_details={
                "action": action,
                "quantity": allocation.quantity,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "estimated_amount": allocation.estimated_amount,
            },
        )

        # S-2 review fix: on_trade_approved is a THIRD source of SELL orders
        # for `ticker` (e.g. a watch-list agent-chat SELL/REDUCE decision) —
        # it can race a RiskMonitor/PositionManager defensive exit on the
        # SAME ticker exactly like the dual-engine race `_close_position`/
        # `_reduce_position`/`_execute_order_from_monitor` guard against (see
        # `_close_position`'s docstring). Guard just the order-placement +
        # fill-reconciliation window below — BUY orders never touch this
        # guard (`is_sell_main` gates it), matching every other site's
        # "BUY/ADD paths stay untouched" contract.
        is_sell_main = side == OrderSide.SELL
        if is_sell_main and not self._acquire_defensive_exit_guard(ticker):
            rationale = (
                f"Defensive exit already in flight for {ticker} — skipped to "
                f"avoid a duplicate SELL"
            )
            self._log_activity(
                ActivityType.TRADE_REJECTED,
                rationale,
                agent="system",
                ticker=ticker,
            )
            return AllocationPlan(
                ticker=ticker,
                stock_name=stock_name,
                side=side,
                quantity=0,
                entry_price=entry_price,
                estimated_amount=0,
                position_pct=0,
                rationale=rationale,
            )

        try:
            result = await self._execute_order(order)

            # Log execution result
            if result.filled_quantity > 0:
                self._log_activity(
                    ActivityType.ORDER_EXECUTED,
                    f"Order filled: {result.filled_quantity} shares @ ₩{result.avg_price:,.0f}",
                    agent="order",
                    ticker=ticker,
                    details={
                        "filled_quantity": result.filled_quantity,
                        "avg_price": result.avg_price,
                        "order_id": result.order_id,
                    },
                )
                # Update order agent with success result
                self._update_agent_status(
                    "order",
                    AgentStatus.IDLE,
                    action=f"Filled {result.filled_quantity} shares @ ₩{result.avg_price:,.0f}",
                    processing_stock=ticker,
                    processing_stock_name=stock_name,
                    trade_details={
                        "action": action,
                        "quantity": result.filled_quantity,
                        "entry_price": result.avg_price,
                        "total_amount": result.filled_quantity * result.avg_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    },
                    last_result={
                        "success": True,
                        "message": f"Order filled: {result.filled_quantity} shares",
                        "order_id": result.order_id,
                        "filled_quantity": result.filled_quantity,
                        "avg_price": result.avg_price,
                    },
                )
                self._complete_agent_task("order", success=True)

                # E1-4 (scope 2, PART 2 gap follow-up): this branch used to ONLY
                # write the ledger row (see the now-superseded comment this
                # replaces) — it never decremented `_state.positions`, so a fill
                # placed through THIS entry point (agent-chat direct decisions +
                # queue replays) left a phantom leftover position exactly the
                # size of the fill; only a LATER poll delta (E1-2) would shave
                # anything off, never the placement-time fill itself.
                # `_apply_sell_fill` is the shared choke point every OTHER SELL
                # caller (RiskMonitor triggers, _execute_order_from_monitor,
                # rebalance orders above) already uses — it performs the SAME
                # ledger write this block used to do directly (record_trade_fill,
                # still gated on `_persistence_active` internally) AND reconciles
                # the local position (decrement/remove + realized P&L), so
                # routing through it here REPLACES the direct call rather than
                # adding a second one (which would double-record the same fill).
                if side == OrderSide.SELL:
                    self._apply_sell_fill(ticker, result.filled_quantity, order=order, result=result)
            else:
                self._log_activity(
                    ActivityType.ORDER_FAILED,
                    f"Order failed: {result.message or 'Unknown error'}",
                    agent="order",
                    ticker=ticker,
                )
                # Update order agent with failure result
                self._update_agent_status(
                    "order",
                    AgentStatus.IDLE,
                    action=f"Order failed: {result.message or 'Unknown error'}",
                    error=result.message,
                    processing_stock=ticker,
                    processing_stock_name=stock_name,
                    last_result={
                        "success": False,
                        "message": result.message or "Unknown error",
                    },
                )
                self._complete_agent_task("order", success=False)
                # Critical 1 (최종 전체 브랜치 리뷰): 이 else 분기는 "브로커 거부"가
                # 아니라 status in {pending, rejected} 전체다 — 자율 BUY는 LIMIT
                # 주문이고 order_agent가 3폴×0.5초만 기다린 뒤 미체결이면
                # status="pending", filled_quantity=0으로 "정상" 반환한다(주문은
                # 브로커에 살아있고, 9줄 아래 _track_unfilled가 바로 그 살아있는
                # 주문을 ka10076 추적에 등록한다). pending을 "주문 실패, 수동
                # 확인하세요" 알림으로 보내면 운영자가 이미 작동 중인 지정가
                # 주문에 중복 매수를 시도할 위험이 생긴다. 실제 거부(status ==
                # "rejected")만 알린다 — pending은 의도적으로 무통지다(체결이
                # 나중에 잡히면 _poll_tracked_fills의 사후 체결 통지가 알린다).
                if result.status == "rejected":
                    self._schedule_order_failure_alert(order, result.message or "브로커 거부")
        finally:
            if is_sell_main:
                self._release_defensive_exit_guard(ticker)

        # If successful, add to monitoring
        if result.filled_quantity > 0 and side == OrderSide.BUY:
            # H3: 즉시체결도 pending체결(:3240)과 동일하게 register_fill_as_position로
            # 등록 → RiskMonitor(via _add_position, 기존과 동일) + PositionManager
            # 양쪽 감시엔진에 등록(이중엔진 실현). 이전엔 수동 _add_position만 호출해
            # PM 미등록이라 PM의 30s 손절/트레일링/재평가가 이 포지션엔 안 돌았다.
            await register_fill_as_position(
                self,
                ticker=ticker,
                stock_name=stock_name or ticker,
                quantity=result.filled_quantity,
                avg_price=result.avg_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                session_id=session_id,
                source="placement_fill",
                stop_loss_mode=self.risk_params.stop_loss_mode,
                risk_score=risk_score,
            )

            self._log_activity(
                ActivityType.POSITION_OPENED,
                f"Position opened: {result.filled_quantity} {stock_name or ticker} @ ₩{result.avg_price:,.0f}",
                agent="portfolio",
                ticker=ticker,
                details={
                    "quantity": result.filled_quantity,
                    "avg_price": result.avg_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
            )

        # F3/E1-1: an unfilled/partial order (either side) still has (or may
        # soon have) broker-side exposure that nothing is watching yet —
        # track the remainder so the scheduler's ka10076 poll can pick up
        # the post-fill later. `_track_unfilled` is side-agnostic (E1-1
        # generalized the original BUY-only F3 block, since a SELL/REDUCE
        # remainder going untracked is exactly how a real ledger under-
        # recorded a 155-share broker sell as 41 shares).
        registered = self._track_unfilled(
            side.value,
            ticker,
            stock_name or ticker,
            result,
            limit_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source_queue_id=queue_id,
            source_session_id=session_id,
            risk_score=risk_score,
        )
        if registered:
            self._schedule_persist()
            self._log_activity(
                ActivityType.ORDER_PLACED,
                f"미체결 잔량 추적 등록: {stock_name or ticker} "
                f"({', '.join(registered)})",
                agent="order",
                ticker=ticker,
                details={"tracked": registered},
            )

        return allocation

    def _track_unfilled(
        self,
        order_side: str,
        ticker: str,
        stock_name: str,
        result: OrderResult,
        *,
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        source_queue_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        risk_score: Optional[int] = None,
    ) -> List[str]:
        """Register every pending/partial part of an order result with the
        fill tracker, so the 30s ka10076 poll (`_poll_tracked_fills`) can
        pick up its post-fill later.

        Extracted from the original F3 BUY-only block (E1-1) — `order_side`
        is now threaded through instead of the block being gated on
        `OrderSide.BUY`, so the exact same registration applies to a SELL or
        REDUCE order's unfilled remainder. Returns [] (no registration) when
        the aggregate result itself is not pending/partial (e.g. fully
        filled or rejected) — same short-circuit as the original gate.

        Split orders (F3 review CRITICAL): the aggregate carries per-part
        results in `result.parts`, each with its OWN broker ord_no. ka10076
        matches by ord_no, so every unfilled/partial part is tracked as its
        own TrackedOrder — one aggregate entry would poison the diff
        arithmetic (several broker orders summed against one total).
        """
        if result.status not in ("pending", "partial"):
            return []

        registered: List[str] = []
        for part in (result.parts or [result]):
            if part.status not in ("pending", "partial"):
                continue
            remaining = part.requested_quantity - part.filled_quantity
            if remaining <= 0:
                continue
            self.fill_tracker.register(
                TrackedOrder(
                    ord_no=part.order_id,
                    ticker=ticker,
                    stock_name=stock_name or ticker,
                    side=order_side,
                    total_quantity=part.requested_quantity,
                    filled_quantity=part.filled_quantity,
                    filled_amount=part.filled_quantity * part.avg_price,
                    limit_price=limit_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    source_queue_id=source_queue_id,
                    source_session_id=source_session_id,
                    risk_score=risk_score,
                    trade_date=date.today().strftime("%Y%m%d"),
                )
            )
            registered.append(f"{part.order_id}:{remaining}주")
        return registered

    def _register_unfilled_sell(
        self,
        ticker: str,
        position: Optional[ManagedPosition],
        order: OrderRequest,
        result: OrderResult,
    ) -> List[str]:
        """Register the unfilled/partial remainder of a defensive/monitor SELL
        (`_close_position`/`_reduce_position`/`_execute_order_from_monitor`)
        with the fill tracker — the SAME registration `on_trade_approved`'s
        SELL/REDUCE path already gets via `_track_unfilled` (E1-1/E1-2), just
        reached from a different call shape here (an already-placed
        `OrderRequest`/`OrderResult` plus the coordinator's OWN
        `ManagedPosition`, not the entry-side session context
        `on_trade_approved` builds from). `position` may be None —
        `_execute_order_from_monitor` looks it up defensively and can find
        nothing if the local ledger no longer tracks the ticker — in which
        case `risk_score` is simply omitted, same as `_track_unfilled`
        already accepts `None` for it.

        `source_session_id` (I1, final-review fix, spec D2): the PLACED
        ORDER's own `session_id`, not `position.analysis_session_id` (the
        position's ENTRY-side decision). The pre-fix code read the entry id
        here, so a post-fill exit tranche (`_poll_tracked_fills` ->
        `_apply_sell_position_delta` -> `record_kr_realized_pnl`) mis-
        attributed `exit_decision_id` to the entry decision for every
        partially-filled exit, discussion-driven or mechanical alike. Every
        caller already threads (or deliberately omits) `order.session_id`
        correctly per spec D2: `_close_position`/`_reduce_position` forward
        an optional `decision_id` into it (a discussion-driven exit's own
        decision id, correctly distinct from the position's entry id), while
        a mechanical stop-loss/take-profit (`_execute_order_from_monitor`)
        and a system rebalance sell never set it at all — both naturally
        land None here, which is correct (no upstream decision to cite), not
        a gap.

        stop_loss/take_profit are always None here: every caller is an EXIT,
        which has no defense levels of its own to carry forward (unlike an
        entry BUY's stop/take).
        """
        stock_name = (position.stock_name if position else None) or order.stock_name or ticker
        registered = self._track_unfilled(
            "sell",
            ticker,
            stock_name,
            result,
            limit_price=order.price,
            source_session_id=order.session_id,
            risk_score=position.risk_score if position else None,
        )
        if registered:
            self._schedule_persist()
            self._log_activity(
                ActivityType.ORDER_PLACED,
                f"미체결 잔량 추적 등록: {stock_name} ({', '.join(registered)})",
                agent="order",
                ticker=ticker,
                details={"tracked": registered},
            )
        return registered

    def _record_fill_ledger(
        self,
        order: OrderRequest,
        result: OrderResult,
        *,
        side: str,
        entry_or_exit: str,
        realized_pnl: Optional[float] = None,
        realized_pnl_pct: Optional[float] = None,
    ) -> None:
        """Shared ledger-write half of both fill choke points (BUY in
        `_execute_order`, SELL in `_apply_sell_fill`) — split-order aware
        (Critical 1, final whole-branch review).

        A split order places SEVERAL broker orders, each with its own
        ord_no, surfaced as `result.parts`. Recording the AGGREGATE as one
        row (part0's order_id + the summed filled_quantity, the pre-fix
        behavior) made `reconcile_trade_ledger`'s per-(order_id, stk_cd) EOD
        diff see every OTHER part's ord_no as entirely absent from the
        ledger — it re-appended them at EOD as "missing", double-counting
        both the ledger row and its realized P&L (reviewer repro: a split
        SELL's placement-time fill recorded as one aggregate row, then the
        EOD reconciler re-appending the other parts' broker fills as if
        they were never recorded, inflating both the ledger and realized
        P&L on every EOD run instead of settling at diff 0).

        Recording one row PER PART (its own order_id/quantity=
        requested_quantity/executed_quantity=filled_quantity/avg_price)
        makes each part's ledger key match its broker (ord_no, stk_cd) key
        exactly, so the EOD diff lands at 0 — the same per-part contract
        `_track_unfilled` (above) already uses for the fill TRACKER side of
        the same split. `result.parts is None` (single/non-split order)
        degrades to `[result]`, keeping the previous single-row behavior
        byte-for-byte.

        Only the ledger WRITE is split here — position decrement and
        realized P&L stay total-based in `_apply_sell_position_delta` (the
        existing semantics: one matched exit against the position's
        blended average, not a per-part breakdown).

        통지(2026-07-30): 체결 통지를 여기서 던진다. 이 함수가 BUY/SELL 두
        초크포인트가 공유하는 지점이라 자율·HITL·PM 방어청산이 전부 덮인다.
        `_persistence_active` 게이트 **앞**에서 던지는 것은 의도다 — 체결
        사실이 원장 기록 여부에 종속되면 안 된다.
        """
        self._schedule_fill_notification(
            order, result, side=side,
            realized_pnl=realized_pnl, realized_pnl_pct=realized_pnl_pct,
        )

        if not self._persistence_active:
            return
        for part in (result.parts or [result]):
            if part.filled_quantity <= 0:
                continue
            record_trade_fill(
                stk_cd=order.ticker,
                stk_nm=order.stock_name,
                side=side,
                order_type=getattr(order.order_type, "value", order.order_type),
                price=part.avg_price or order.price or 0,
                quantity=part.requested_quantity,
                executed_quantity=part.filled_quantity,
                status=(
                    "completed"
                    if part.filled_quantity >= part.requested_quantity
                    else "partial"
                ),
                order_id=part.order_id,
                session_id=order.session_id,
                decision_id=order.session_id,
                entry_or_exit=entry_or_exit,
            )

    def _schedule_fill_notification(
        self,
        order: OrderRequest,
        result: OrderResult,
        *,
        side: str,
        realized_pnl: Optional[float] = None,
        realized_pnl_pct: Optional[float] = None,
    ) -> None:
        """동기 문맥에서 체결 통지를 던진다(never-raise).

        `_record_fill_ledger`가 `def`라 await를 쓸 수 없다. 레포 기존 패턴과
        같이 create_task로 던지되 강참조를 보관한다.
        """
        try:
            from services.telegram.config import get_telegram_config

            if not getattr(get_telegram_config(), "TELEGRAM_NOTIFY_FILL_ENABLED", True):
                return
        except Exception:
            pass  # 설정을 못 읽으면 통지를 막지 않는다 — 체결은 알려야 한다
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._notify_fill(
                order, result, side=side,
                realized_pnl=realized_pnl, realized_pnl_pct=realized_pnl_pct,
            )
        )
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _notify_fill(
        self,
        order: OrderRequest,
        result: OrderResult,
        *,
        side: str,
        realized_pnl: Optional[float] = None,
        realized_pnl_pct: Optional[float] = None,
    ) -> None:
        """체결 통지 본체. 실패해도 절대 밖으로 새지 않는다."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if not notifier.is_ready:
                return
            filled = int(getattr(result, "filled_quantity", 0) or 0)
            if filled <= 0:
                return
            requested = int(getattr(result, "requested_quantity", 0) or 0)
            avg = getattr(result, "avg_price", None) or order.price or 0
            await notifier.send_trade_executed(
                ticker=order.ticker,
                stock_name=order.stock_name or order.ticker,
                action="BUY" if side in ("buy", OrderSide.BUY) else "SELL",
                quantity=filled,
                price=int(round(float(avg))),
                total_amount=int(round(float(avg) * filled)),
                realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
                source=getattr(order, "reason", None),
                partial=bool(requested and filled < requested),
            )
        except Exception as e:
            # structlog 스타일 kwargs가 아니라 f-string을 쓴다 — 이 모듈은
            # stdlib logging.getLogger라 logger.error(msg, ticker=...) 같은
            # 임의 kwargs는 TypeError로 죽는다(never-raise 위반이 되어버림).
            logger.error(f"[Coordinator] fill_notification_failed ticker={order.ticker} error={e}")

    def _schedule_order_failure_alert(self, order: OrderRequest, reason: str) -> None:
        """자율 주문이 브로커 단계에서 실패했음을 알린다(never-raise)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._notify_order_failed(order, reason))
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _notify_order_failed(self, order: OrderRequest, reason: str) -> None:
        try:
            from services.telegram import get_telegram_notifier
            from services.telegram.formatting import stock_label

            notifier = await get_telegram_notifier()
            if not notifier.is_ready:
                return
            side = getattr(order.side, "value", order.side)
            await notifier.send_message(
                f"⛔ 주문 실패 ({side})\n"
                f"{stock_label(order.stock_name, order.ticker)}\n"
                f"사유: {reason}\n"
                f"→ 체결되지 않았습니다. 수동으로 확인하세요.",
                parse_mode=None,
            )
        except Exception as e:
            # 이 모듈은 stdlib logging이라 structlog 스타일 kwargs는
            # TypeError로 죽는다 — never-raise 핸들러 안에서 로거가 죽으면
            # 안 되므로 f-string을 쓴다(위 _notify_fill과 동일 패턴).
            logger.error(f"[Coordinator] order_failure_alert_failed ticker={order.ticker} error={e}")

    async def _drain_notify_tasks(self) -> None:
        """테스트용 — 던져둔 통지 태스크가 끝날 때까지 기다린다."""
        pending = list(self._notify_tasks)
        for task in pending:
            try:
                await task
            except Exception:
                pass

    async def _execute_order(self, order: OrderRequest) -> OrderResult:
        """Execute an order and update state."""
        # Add to pending
        self._state.pending_orders.append(order)
        await self._notify_state_change()

        # Execute
        result = await self.order_agent.execute_order(order)

        # Remove from pending
        self._state.pending_orders = [
            o for o in self._state.pending_orders
            if o.ticker != order.ticker
        ]

        # Update trade count
        if result.filled_quantity > 0:
            self._maybe_reset_daily_trades()
            self._state.daily_trades_count += 1
            self._schedule_persist()

            # P1-1: record the fill for /trades — BUY only here. Every SELL
            # caller of _execute_order also calls _apply_sell_fill right
            # after, which is the single choke point for SELL fills; a
            # side-agnostic record here would double-count those. Gated by
            # _persistence_active (same rule as _schedule_persist) so a
            # coordinator built in a unit test never writes to real storage.
            if order.side in (OrderSide.BUY, "buy"):
                # Critical 1 (final review): per-part ledger rows for split
                # orders — see `_record_fill_ledger` docstring.
                self._record_fill_ledger(
                    order, result, side="buy", entry_or_exit="entry"
                )

        await self._notify_state_change()

        return result

    async def _execute_order_from_monitor(self, order: OrderRequest) -> bool:
        """Execute order from risk monitor (stop-loss/take-profit).

        This is the choke point for every AGENT_AUTO defensive sell — it MUST
        pass the shared autonomy gate, the same one PositionManager's
        `_execute_close_position` (A2) and the queue re-gate (R5-P0) already
        enforce. Before this fix a stop-loss/take-profit fired straight to the
        broker with no gate check at all (audit I1, 2026-07-13). A denied sell
        places nothing and leaves the position tracked/watched — the
        USER_APPROVAL alert path (RiskMonitor's non-AGENT_AUTO branch) is
        untouched by this change.

        S-2 review fix: guarded by the coordinator-wide in-flight defensive-
        exit set (`_acquire_defensive_exit_guard`) — RiskMonitor's 1s tick
        and PositionManager's 30s tick can otherwise both detect the same
        breached stop and race to close the same position. RiskMonitor only
        ever triggers a defensive SELL through this method (never BUY), but
        the `is_sell` check is explicit rather than assumed, matching the
        "BUY/ADD paths stay untouched" contract shared with the other 5
        guarded SELL sites (`_close_position`/`_reduce_position`/
        `on_trade_approved`'s SELL/REDUCE main path AND its rebalance-orders
        loop, N1/`handle_alert_action`'s EXECUTE_STOP_LOSS/
        EXECUTE_TAKE_PROFIT) — 6 guarded SELL sites total.

        G-2 (gap discipline, spec docs/superpowers/specs/
        2026-07-20-gap-discipline-design.md §N2): returns `bool` — True only
        when the order actually reached `_execute_order` (submitted to the
        broker); False when the in-flight guard or the autonomy gate skipped
        it. Before this fix the method returned nothing, so RiskMonitor's
        `_execute_stop_loss`/`_execute_take_profit` could not tell a denied
        or in-flight-skipped call apart from a real submission and generated
        a false "Executed" alert unconditionally on every 1s tick. Existing
        callers that ignore the return value are unaffected by adding it.
        """
        from services.autonomy import check_autonomy

        is_sell = order.side == "sell"
        if is_sell and not self._acquire_defensive_exit_guard(order.ticker):
            return False

        try:
            position = next(
                (p for p in self._state.positions if p.ticker == order.ticker), None
            )

            gate = await check_autonomy(
                "kiwoom",
                action="SELL",
                quantity=order.quantity,
                entry_price=order.price,
            )
            if not gate.allowed:
                logger.warning(
                    f"[Coordinator] AGENT_AUTO defensive sell blocked by gate: "
                    f"{order.ticker} check={gate.check} reason={gate.reason}"
                )
                # Notify once per denied episode, not on every RiskMonitor tick —
                # mirrors the PositionManager A2 latch (close_gate_denied_notified).
                if position is not None and not position.monitor_gate_denied_notified:
                    position.monitor_gate_denied_notified = True
                    await self._notify_monitor_gate_denied(order, gate.reason)
                return False

            if position is not None and position.monitor_gate_denied_notified:
                # Gate allowed again: clear the latch so a future denial notifies.
                position.monitor_gate_denied_notified = False

            result = await self._execute_order(order)
            # Important 4: 브로커 거부는 예외가 아니라 정상 결과로 온다 —
            # _apply_sell_fill의 filled_quantity<=0 가드는 무통지이므로
            # 여기서 명시적으로 실패를 알린다(_close_position/_reduce_position과
            # 동일 처리).
            self._handle_defensive_sell_rejection(position, order, result)
            # Track the ACTUAL fill: full → remove, partial → reduce, none → retain.
            self._apply_sell_fill(order.ticker, result.filled_quantity, order=order, result=result)
            # E1-3: register any unfilled remainder of this AGENT_AUTO defensive
            # sell (see _close_position's same call for the full rationale) — a
            # stop-loss/take-profit trigger that only partially filled at the
            # broker previously went unwatched by the ka10076 poll entirely.
            self._register_unfilled_sell(order.ticker, position, order, result)
            return True
        finally:
            if is_sell:
                self._release_defensive_exit_guard(order.ticker)

    async def _notify_monitor_gate_denied(self, order: OrderRequest, gate_reason: str) -> None:
        """Best-effort Telegram notice when the autonomy gate blocks an
        AGENT_AUTO defensive sell — the human must know a stop-loss/take-profit
        did NOT execute and the position is still open."""
        try:
            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_message(
                    f"🚫 자율 방어매도 게이트 거부 ({order.ticker}, "
                    f"{order.reason or 'stop-loss/take-profit'}): {gate_reason}. "
                    f"포지션은 유지되며 수동 조치가 필요합니다."
                )
        except Exception as e:
            logger.warning(f"[Coordinator] Failed to notify gate denial: {e}")

    def _handle_defensive_sell_rejection(
        self,
        position: Optional[ManagedPosition],
        order: OrderRequest,
        result: OrderResult,
    ) -> None:
        """Important 4 (최종 전체 브랜치 리뷰): 방어적 SELL(_close_position/
        _reduce_position/_execute_order_from_monitor)이 브로커에서 거부되면
        예외가 아니라 정상 OrderResult(status="rejected")로 돌아온다 —
        on_trade_approved의 else 분기(Critical 1)와 달리 이 세 진입점은
        `_execute_order` 뒤 곧장 `_apply_sell_fill`로 가고, 그 함수는
        filled_quantity<=0이면 경고 로그만 남기고 반환한다. 그 결과 손절/
        익절/청산/축소가 브로커 단에서 거부돼도 통지가 전혀 나가지 않았다
        (on_trade_approved가 이미 갖고 있던 `_schedule_order_failure_alert`를
        여기서도 재사용한다 — "실패 통지가 없다"는 같은 결함의 다른 얼굴).

        이 세 진입점은 PositionManager의 30초 감시 틱에서 반복 호출될 수
        있어 브로커가 계속 거부하면(예: 거래정지 종목) 매 틱마다 재통지할
        위험이 있다 — `monitor_gate_denied_notified`와 같은 형태의 래치
        (`close_order_rejected_notified`)로 거부 에피소드당 한 번만 알리고,
        거부가 아닌 상태로 돌아오면 래치를 풀어 다음 거부가 다시 통지되게
        한다.
        """
        if result.status != "rejected":
            if position is not None and position.close_order_rejected_notified:
                position.close_order_rejected_notified = False
            return

        if position is not None:
            if position.close_order_rejected_notified:
                return
            position.close_order_rejected_notified = True

        self._schedule_order_failure_alert(order, result.message or "브로커 거부")

    # -------------------------------------------
    # Position Management
    # -------------------------------------------

    def _add_position(self, position: ManagedPosition):
        """Add a position to tracking."""
        # Check if already exists
        existing_idx = next(
            (i for i, p in enumerate(self._state.positions) if p.ticker == position.ticker),
            None
        )

        if existing_idx is not None:
            # Update existing position (average in)
            existing = self._state.positions[existing_idx]
            total_qty = existing.quantity + position.quantity
            total_cost = (existing.avg_price * existing.quantity) + (position.avg_price * position.quantity)
            existing.quantity = total_qty
            existing.avg_price = total_cost / total_qty
            existing.last_updated = datetime.now()
            # I1 (final-review): coalesce stops onto the merged position —
            # keep existing's non-None stops, only fill gaps from the
            # incoming tranche.
            if existing.stop_loss is None and position.stop_loss is not None:
                existing.stop_loss = position.stop_loss
            if existing.take_profit is None and position.take_profit is not None:
                existing.take_profit = position.take_profit
            watched = existing
        else:
            self._state.positions.append(position)
            watched = position

        # Add to risk monitor — MUST watch the merged position (`watched`),
        # not the incoming delta `position`: add_position replaces
        # WatchConfig wholesale, so after a merge the monitor would otherwise
        # watch only the last tranche's quantity while the real position is
        # the merged total — a stop trigger would then sell only that
        # tranche (I1, final-review).
        self.risk_monitor.add_position(watched)

        # Update risk agent status
        self._update_agent_status(
            "risk",
            AgentStatus.WORKING,
            task=f"Monitoring {position.stock_name or position.ticker}",
            processing_stock=position.ticker,
            processing_stock_name=position.stock_name,
            trade_details={
                "action": "MONITOR",
                "quantity": position.quantity,
                "entry_price": position.avg_price,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
            },
        )

        logger.info(f"[Coordinator] Position added/updated: {position.ticker}")
        self._schedule_persist()

    def _remove_position(self, ticker: str):
        """Remove a position from tracking."""
        # Find position before removing for status update
        position = next((p for p in self._state.positions if p.ticker == ticker), None)

        self._state.positions = [
            p for p in self._state.positions if p.ticker != ticker
        ]
        self.risk_monitor.remove_position(ticker)

        # Update risk agent status
        remaining_count = len(self._state.positions)
        if remaining_count > 0:
            self._update_agent_status(
                "risk",
                AgentStatus.WORKING,
                task=f"Monitoring {remaining_count} positions",
                last_result={
                    "success": True,
                    "message": f"Position closed: {position.stock_name if position else ticker}",
                },
            )
        else:
            self._update_agent_status(
                "risk",
                AgentStatus.IDLE,
                action="No positions to monitor",
                last_result={
                    "success": True,
                    "message": f"Position closed: {position.stock_name if position else ticker}",
                },
            )

        logger.info(f"[Coordinator] Position removed: {ticker}")
        self._schedule_persist()

    def _apply_sell_fill(
        self,
        ticker: str,
        filled_quantity: int,
        *,
        order: Optional[OrderRequest] = None,
        result: Optional[OrderResult] = None,
    ) -> None:
        """Reconcile position tracking with the ACTUAL fill of a SELL/close (A3).

        Full fill → remove; partial → reduce and keep monitoring the remainder;
        none → keep the position. A sell that did not fill must NOT orphan the
        exposure — previously the close removed the position unconditionally, so a
        rejected/unfilled sell dropped a still-open position from all defense.

        `order`/`result` are optional so existing bare callers keep working,
        but every current call site passes both — this is the single choke
        point for recording a SELL fill (/trades, P1-1), independent of
        whether we still have a locally tracked position for `ticker`.

        Composition (E1-2): the ledger write (record_trade_fill, above) stays
        here — its fields (order_type/status/etc.) come from `order`/`result`,
        which this method has but the shared delta helper below does not. The
        position reconciliation (decrement/remove + realized P&L) is extracted
        into `_apply_sell_position_delta` so `_poll_tracked_fills`'s post-fill
        SELL delta branch — which only has a `TrackedOrder`/`FillDelta`, never
        an `OrderRequest`/`OrderResult` — can reuse the exact same logic.
        """
        if filled_quantity <= 0:
            logger.warning(
                f"[Coordinator] SELL for {ticker} did not fill — position retained"
            )
            return

        if order is not None and result is not None:
            # Critical 1 (final review): per-part ledger rows for split
            # orders — see `_record_fill_ledger` docstring. The per-part loop
            # derives each row's executed_quantity from `result.parts`
            # directly; `filled_quantity` (the caller-supplied aggregate) IS
            # used below, for the notification's realized-P&L estimate.
            #
            # 실현손익은 포지션 감소 **전에** 계산해야 한다 —
            # _apply_sell_position_delta가 포지션을 줄이거나 지우고 나면
            # 진입가를 읽을 수 없다.
            #
            # 리뷰 Important 1: _apply_sell_position_delta(아래)는
            # `_matched = min(quantity, position.quantity)`로 클램프한 뒤
            # realized_amount를 계산한다(원장의 정답). 여기서 클램프 없이
            # filled_quantity 그대로 곱하면 오버셀/부분 리컨실 상황에서
            # 통지 금액이 원장 금액보다 커진다 — 같은 클램프를 그대로
            # 맞춘다.
            _pos = next((p for p in self._state.positions if p.ticker == ticker), None)
            _entry = getattr(_pos, "avg_price", None) if _pos else None
            _exit = getattr(result, "avg_price", None) if result is not None else None
            _pnl = None
            _pnl_pct = None
            if _entry and _exit and filled_quantity and _pos is not None:
                _matched_qty = min(int(filled_quantity), int(_pos.quantity))
                _pnl = (float(_exit) - float(_entry)) * _matched_qty
                _pnl_pct = (float(_exit) / float(_entry) - 1.0) * 100.0

            self._record_fill_ledger(
                order, result, side="sell", entry_or_exit="exit",
                realized_pnl=_pnl, realized_pnl_pct=_pnl_pct,
            )

        # `avg_price=None` (order/result missing) tells the delta helper below
        # there is no known exit price for this fill, so it must skip realized
        # P&L (matching the pre-extraction behavior: that block was gated on
        # `order is not None and result is not None` too) while STILL
        # reconciling the local position quantity, which was unconditional.
        _exit_price: Optional[float] = None
        _session_id: Optional[str] = None
        if order is not None and result is not None:
            _exit_price = result.avg_price or order.price or 0
            _session_id = order.session_id

        self._apply_sell_position_delta(ticker, filled_quantity, _exit_price, _session_id)

    def _apply_sell_position_delta(
        self,
        ticker: str,
        quantity: int,
        avg_price: Optional[float],
        session_id: Optional[str] = None,
    ) -> None:
        """Decrement/remove the LOCAL position for a SELL fill and record
        realized P&L — no ledger write here (callers own `record_trade_fill`
        separately, since its fields differ per call site).

        Full fill → remove; partial → reduce and keep monitoring the
        remainder (unchanged from `_apply_sell_fill`'s pre-extraction
        behavior). No local position found for `ticker` (e.g. the reconciler
        already cleared it, or — for a fill-tracker SELL delta — the order's
        earlier partial fill was recorded through a path that never touched
        `_state.positions`) → warn and no-op; decrement is meaningless
        without a position to decrement.

        `avg_price=None` means the caller has no known exit price for this
        fill (only `_apply_sell_fill`'s bare-caller fallback does this) —
        realized P&L needs an exit price to match against the position's
        entry price, so it is skipped in that case (mirrors
        `_apply_sell_fill`'s pre-extraction behavior of skipping
        `record_kr_realized_pnl` whenever `order`/`result` were absent).
        """
        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if position is None:
            logger.warning(
                f"[Coordinator] SELL fill for {ticker} ({quantity}주) has no "
                "local position to reconcile — skipping decrement/realized P&L"
            )
            return

        # T4: matched realized P&L — entry avg_price+analysis_session_id and exit fill both in scope here
        if self._persistence_active and avg_price is not None:
            _matched = min(quantity, position.quantity)
            _now = datetime.now()
            record_kr_realized_pnl(
                stk_cd=ticker, entry_price=position.avg_price, exit_price=avg_price,
                quantity=_matched, realized_amount=(avg_price - position.avg_price) * _matched,
                entry_decision_id=position.analysis_session_id, exit_decision_id=session_id,
                entry_at=position.entry_time,
                exit_at=_now,
                holding_period_seconds=(
                    int((_now - position.entry_time).total_seconds())
                    if position.entry_time else None
                ),
            )

        if quantity >= position.quantity:
            self._remove_position(ticker)
            mirror_sell_to_position_manager(ticker, 0)
        else:
            position.quantity -= quantity
            position.last_updated = datetime.now()
            # Re-register so the monitor watches the reduced size (keeps stops).
            self.risk_monitor.remove_position(ticker)
            self.risk_monitor.add_position(position)
            self._schedule_persist()
            logger.info(
                f"[Coordinator] Position {ticker} reduced by {quantity}; "
                f"{position.quantity} remaining"
            )
            mirror_sell_to_position_manager(ticker, position.quantity)

    # -------------------------------------------
    # State Persistence (R5-P1 A4)
    # -------------------------------------------
    #
    # Positions (with stop levels), the trade queue, and the daily trade count
    # lived only in memory, so a restart left the risk monitor watching nothing —
    # stop-losses became a silent no-op. Persist them to SQLite (app_settings
    # blob) and reload on start so defense and queued autonomous trades survive a
    # restart. Stops are the coordinator's own data — the broker does not know
    # them — so the local state IS the source of truth to persist.

    _STATE_KEY = "trading:coordinator_state"

    def _mode_value(self) -> str:
        """`_state.mode`를 블롭에 쓸 문자열로 정규화한다. `_persist_state`와
        `_persist_fields(mode=...)` 호출부(stop/pause/resume) 양쪽에서
        같은 규칙을 쓰도록 공유한다."""
        return (
            self._state.mode.value
            if hasattr(self._state.mode, "value")
            else str(self._state.mode)
        )

    def _maybe_reset_daily_trades(self) -> None:
        """`daily_trades_count`를 새 달력일로 lazy 롤오버한다.

        `daily_trades_count`를 읽거나 쓰는 모든 지점(게이트 판정·증가·영속·
        외부 상태 조회) **앞**에서 호출해야 한다. 특히 영속 호출이 빠지면:
        카운트가 어제 몫인 채로 `_persist_state`가 오늘 날짜를 찍어버리고,
        다음 재시작에서 `_restore_state`가 "날짜가 맞다"며 그 낡은 카운트를
        그대로 복원한다 — 재시작으로도 못 고치는 자기영속 결함이 된다
        (2026-08-04 실 라이브 사고: daily_trades_count=4 / daily_count_date=
        오늘로 영속돼 있었는데 그중 3건은 전날 거래였다).

        `agents/llm/router.py`의 `_maybe_reset_day()`(OpenRouter 일일 예산)와
        동일 패턴 — 스케줄된 잡 없이, 쓰는 시점마다 스스로 확인한다.
        """
        today = date.today()
        if today != self._daily_count_day:
            self._daily_count_day = today
            self._state.daily_trades_count = 0

    async def _persist_state(self) -> None:
        """Best-effort persist of restart-critical state. Never raises — a storage
        failure must not break trading."""
        try:
            from services.storage_service import get_storage_service

            # 아래 blob이 "오늘" 날짜를 daily_trades_count에 찍는다 — 롤오버가
            # 안 돌았으면 어제 몫 카운트에 오늘 도장을 찍는 셈이라, 다음 restore가
            # "날짜 일치"로 보고 그대로 복원해버린다(자기영속 결함, 위 docstring).
            self._maybe_reset_daily_trades()

            blob = json.dumps(
                {
                    "positions": [
                        p.model_dump(mode="json") for p in self._state.positions
                    ],
                    "trade_queue": [
                        t.model_dump(mode="json") for t in self._state.trade_queue
                    ],
                    # P2 SSOT prep (2026-07-14): the watch list lived only in
                    # memory alongside positions/queue, so a restart silently
                    # dropped every watched stock — the funnel's single source
                    # of truth must survive a restart the same way positions
                    # and the trade queue already do.
                    "watch_list": [
                        w.model_dump(mode="json") for w in self._state.watch_list
                    ],
                    "daily_trades_count": self._state.daily_trades_count,
                    "daily_count_date": date.today().isoformat(),
                    "tracked_orders": self.fill_tracker.to_payload(),
                    "risk_params": self.risk_params.model_dump(),
                    # 재시작 안전(2026-07-29): 부팅 시 "꺼져 있었나 켜져
                    # 있었나"를 알 유일한 근거다. resume_if_persisted()가
                    # 이 값만 보고 방어를 되살릴지 정한다. _restore_state는
                    # 이 필드를 읽지 않는다 — 수동 start()는 기존대로
                    # 무조건 ACTIVE로 간다.
                    "mode": self._mode_value(),
                }
            )
            storage = await get_storage_service()
            await storage.set_app_setting(self._STATE_KEY, blob)
        except Exception as e:
            logger.error(f"[Coordinator] Failed to persist state: {e}")

    async def _persist_fields(self, **kv) -> None:
        """임의 key/value 묶음만 read-modify-write로 갱신한다. Never-raise —
        `_persist_state`와 동일 계약.

        `_persist_mode_only()`의 일반화(2026-07-29 리뷰: `PUT
        /api/trading/risk-params` 라우트도 `_persist_state()`를 무조건
        호출해 미시작 코디네이터의 빈 상태로 블롭을 덮어쓰는 동일한
        REGRESSION을 갖고 있었다 — mode 하나에 특화된 헬퍼를 또 복제하는
        대신 임의 필드를 다루도록 일반화한다).

        `_persistence_active`가 False인 코디네이터(이 프로세스에서
        `_restore_state()`가 한 번도 안 돈, 즉 `start()`를 거치지 않은
        인스턴스)의 메모리 상 `_state`는 positions/trade_queue/watch_list/
        tracked_orders가 전부 기본값(빈 값)이다 — 블롭의 실제 내용을 반영하지
        않는다. 이 상태에서 `_persist_state()`(전체 스냅샷 직렬화)를 부르면
        진짜 데이터를 빈 값으로 덮어써 버린다(REGRESSION, 2026-07-29 리뷰:
        재시작 안전 브랜치 자신의 첫 배포 창에서 stop/pause/resume 중 아무거나
        한 번만 호출돼도 보유 포지션의 손절가가 통째로 사라짐).

        그래도 넘겨받은 필드는 여전히 즉시 영속돼야 한다. 그래서 전체
        persist를 건너뛰는 대신, 기존 블롭을 읽어 넘겨받은 키만 바꿔 쓴다.

        - `json.loads`는 try 안에 있다 — 기존 블롭이 깨져 있으면(파싱 실패)
          아무것도 쓰지 않는다. 부분 블롭으로 원본을 덮어쓰는 것보다, 손상된
          원본이라도 그대로 남는 편이 낫다.
        - 파싱 결과가 dict가 아니면(예: `"null"`, JSON 배열) 마찬가지로
          아무것도 쓰지 않는다 — 원본을 dict가 아닌 값으로 오염시킬 수 없다.
        - 블롭이 없거나 비어 있으면 넘겨받은 필드만 담은 새 블롭을 쓴다.
          이후 진짜 `_persist_state()`가 나머지 필드를 채운다.
        """
        try:
            from services.storage_service import get_storage_service

            storage = await get_storage_service()
            blob = await storage.get_app_setting(self._STATE_KEY)
            data = json.loads(blob) if blob else {}
            if not isinstance(data, dict):
                raise TypeError(
                    "Persisted state blob is not a JSON object "
                    f"(got {type(data).__name__}) — refusing partial write"
                )
            data.update(kv)
            await storage.set_app_setting(self._STATE_KEY, json.dumps(data))
        except Exception as e:
            logger.error(f"[Coordinator] Failed to persist fields {sorted(kv)}: {e}")

    async def _restore_state(self) -> None:
        """Reload restart-critical state. Positions (with stops) are re-registered
        with the risk monitor so defense resumes; the daily count resets on a new
        calendar day. Best-effort — a corrupt/missing blob starts clean."""
        try:
            from services.storage_service import get_storage_service

            storage = await get_storage_service()
            blob = await storage.get_app_setting(self._STATE_KEY)
            if not blob:
                return
            data = json.loads(blob)

            # Positions + stops → re-register with the risk monitor.
            self._state.positions = [
                ManagedPosition.model_validate(p) for p in data.get("positions", [])
            ]
            for position in self._state.positions:
                self.risk_monitor.add_position(position)

            # Queued trades.
            self._state.trade_queue = [
                QueuedTrade.model_validate(t) for t in data.get("trade_queue", [])
            ]

            # Watch list (P2 SSOT prep) — restored in whatever status it was
            # persisted in (ACTIVE/CONVERTED/REMOVED), so a CONVERTED entry
            # stays CONVERTED across a restart instead of reverting to
            # ACTIVE and becoming re-discussable.
            self._state.watch_list = [
                WatchedStock.model_validate(w) for w in data.get("watch_list", [])
            ]

            # Daily count — reset on a new calendar day. `_daily_count_day`도
            # 여기서 오늘로 맞춰야, 복원 직후 첫 읽기/쓰기에서
            # `_maybe_reset_daily_trades()`가 방금 복원한 값을 다시 지워버리지
            # 않는다 — 재시작이 이 in-memory day의 유일한 초기화 지점이다.
            if data.get("daily_count_date") == date.today().isoformat():
                self._state.daily_trades_count = int(data.get("daily_trades_count", 0))
            else:
                self._state.daily_trades_count = 0
            self._daily_count_day = date.today()

            # Tracked orders (F3): TRACKING orders resume so the scheduler poll
            # can pick up their post-fill. A TRACKING order whose trade_date
            # has rolled over (restarted on a later day) is expired instead —
            # nothing placed on a prior session can still fill. Log-only, no
            # notification, to avoid a restart notification storm.
            self.fill_tracker = PendingOrderTracker.from_payload(
                data.get("tracked_orders", [])
            )
            stale = self.fill_tracker.expire_stale(today=date.today().strftime("%Y%m%d"))
            if stale:
                logger.info(
                    f"[Coordinator] Expired {len(stale)} stale tracked orders on restore"
                )

            # F3 review M1c: restoring while the KRX session is CLOSED — the
            # post-close ka10076 snapshot is final, so run ONE last poll (a
            # fill that landed while the backend was down still becomes a
            # defended position) and expire whatever remains. Kills overnight
            # 30s polling and next-day tracking against reused ord_nos.
            # Expiry here is log-only (no alerts — restart storm prevention).
            if self.fill_tracker.tracking():
                market_open = self._market_hours.get_market_session(
                    MarketType.KRX
                ).is_open
                if not market_open:
                    await self._poll_tracked_fills()
                    closed_out = self.fill_tracker.expire_stale(today=None)
                    if closed_out:
                        logger.info(
                            f"[Coordinator] Expired {len(closed_out)} tracked "
                            f"orders on restore (market closed)"
                        )

            # Risk params (T3): in-place setattr, NOT rebind — risk_params is
            # reference-shared with PortfolioAgent/RiskMonitor/TradingState, so
            # replacing the attribute would desync those holders from the
            # coordinator's own copy.
            rp = data.get("risk_params")
            if rp:
                for k, v in rp.items():
                    if hasattr(self.risk_params, k):
                        setattr(self.risk_params, k, v)

            logger.info(
                f"[Coordinator] Restored {len(self._state.positions)} positions, "
                f"{len(self._state.trade_queue)} queued trades, "
                f"{len(self._state.watch_list)} watched stocks, "
                f"{len(self.fill_tracker.tracking())} tracked orders, "
                f"daily_count={self._state.daily_trades_count}"
            )
        except Exception as e:
            logger.error(f"[Coordinator] Failed to restore state: {e}")

    async def _restore_strategy(self) -> None:
        """Phase3: reload the active TradingStrategy from the
        strategy_revisions ledger via the 'strategy:active_revision_id'
        pointer (coordinator._strategy alone is in-memory and lost on
        restart). Pointer invariant (strategy_orchestrator): the pointed
        revision's strategy_json is always the strategy that WAS in effect,
        so applying it verbatim is safe. Best-effort — a missing/empty
        pointer, missing row, or corrupt json starts clean (mirrors
        _restore_state's contract). Never re-persists on restore."""
        try:
            from services.storage_service import get_storage_service
            from services.trading.strategy_orchestrator import (
                ACTIVE_STRATEGY_REVISION_KEY,
            )

            storage = await get_storage_service()
            revision_id = await storage.get_app_setting(ACTIVE_STRATEGY_REVISION_KEY)
            if not revision_id:
                return
            row = await storage.get_strategy_revision(revision_id)
            if not row or not row.get("strategy_json"):
                return
            strategy = TradingStrategy.model_validate_json(row["strategy_json"])
            self.set_strategy(strategy)
            logger.info(
                f"[Coordinator] Strategy restored from revision {revision_id}"
                f" ({strategy.name})"
            )
        except Exception as e:
            logger.warning(f"[Coordinator] strategy restore failed: {e}")

    def _schedule_persist(self) -> None:
        """Fire-and-forget persist from a (possibly sync) mutator. No-op outside a
        session, or without a running loop (a coordinator built in a unit test)."""
        if not self._persistence_active:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist_state())

    # -------------------------------------------
    # Account & Price Data
    # -------------------------------------------

    async def _refresh_account_info(self):
        """Refresh account information from Kiwoom."""
        if self._kiwoom:
            try:
                # Fetch balance from Kiwoom
                # AccountBalance is a Pydantic model with:
                # - evlu_amt: 평가금액 (may include cash, so don't use directly)
                # - d2_ord_psbl_amt: D+2 주문가능금액 (available cash)
                # - holdings: list of Holding with individual evlu_amt
                # - total_value: property (evlu_amt + d2_ord_psbl_amt)
                balance = await self._kiwoom.get_account_balance()

                # Calculate stock value from holdings (not evlu_amt which may include cash)
                # See kr_stocks.py line 968-970 for reference
                stock_value = sum(h.evlu_amt for h in balance.holdings)
                available_cash = balance.d2_ord_psbl_amt
                total_equity = available_cash + stock_value

                self._state.account = AccountInfo(
                    total_equity=total_equity,
                    available_cash=available_cash,
                    total_stock_value=stock_value,
                )
                logger.info(f"[Coordinator] Account refreshed: equity={total_equity:,}, cash={available_cash:,}, stocks={stock_value:,}")
            except Exception as e:
                logger.error(f"[Coordinator] Failed to refresh account: {e}")
        else:
            # Simulation mode - use mock data
            self._state.account = AccountInfo(
                total_equity=10_000_000,  # 1000만원
                available_cash=5_000_000,
                total_stock_value=5_000_000,
            )

        # DI2: reprice every open position from the live quote feed.
        # `ManagedPosition.current_price` was only ever set once, at open
        # (avg_price), so `unrealized_pnl = (current_price - avg_price) * qty`
        # was permanently 0 and portfolio_agent's exposure math (which also
        # reads current_price) drifted from the live total_equity refreshed
        # just above. Do this every time account info is refreshed so both
        # stay consistent.
        await self._reprice_positions()

        self._state.last_updated = datetime.now()

    async def _reprice_positions(self) -> None:
        """Update each open position's `current_price` from the live quote feed.

        `_get_current_price` fails safe to 0/None on any broker error (see
        test_current_price_feed.py) — that is a "no fresh quote" signal, not
        a real price. Writing a fabricated 0 into a live position would zero
        out unrealized_pnl and exposure math, which is worse than a stale
        (but real) last-known price, so a falsy result SKIPS that position
        and leaves current_price untouched (T2 stale-price contract).

        Watch-list entries (P2 SSOT prep, 2026-07-14) get the same treatment:
        `WatchedStock.current_price` was only ever set at registration time,
        so the periodic opportunity check (`ChatCoordinator._detect_opportunity`'s
        target-price proximity test) judged against a price that could be
        hours or days stale. Only ACTIVE entries are repriced — a
        CONVERTED/REMOVED entry's price is historical, not live.
        """
        for position in self._state.positions:
            price = await self._get_current_price(position.ticker)
            if not price:
                continue
            position.current_price = price
            position.last_updated = datetime.now()

        for watched in self._state.watch_list:
            if watched.status != WatchStatus.ACTIVE:
                continue
            price = await self._get_current_price(watched.ticker)
            if not price:
                continue
            watched.current_price = price
            watched.last_checked = datetime.now()

    def _log_market_gate_once(self, closed: bool) -> None:
        """Log a market-gate state transition once (E2-2) — never every
        sweep. Small per-file helper, duplicated across E2-1's gate points
        (agent_chat coordinator/position_manager) and RiskMonitor's E2-2
        gate by design — YAGNI, not worth a shared util for a handful of
        call sites."""
        if self._market_gate_closed == closed:
            return
        self._market_gate_closed = closed
        if closed:
            logger.info("[Coordinator] market_gate_closed")
        else:
            logger.info("[Coordinator] market_gate_reopened")

    async def _refresh_watch_prices(self) -> None:
        """Periodic, WATCH-only price sweep (monitoring-cadence-tuning arc,
        MAIN BODY).

        `_reprice_positions` above only refreshes watch-list entries when
        `_refresh_account_info` runs — at coordinator `start()` and on each
        trade approval. There was no periodic loop, so a WATCH entry's
        `current_price` (compared against `target_entry_price` by
        `ChatCoordinator._check_watch_list`) could go stale for an entire
        session between trades. `_watch_refresh_loop` drives this on a
        cadence derived from `compute_watch_ttl(W)` (W = ACTIVE watch count)
        so the refresh rate scales with load instead of a fixed interval
        that either starves responsiveness or blows the shared Kiwoom quote
        budget.

        Only ACTIVE entries are refreshed — CONVERTED/REMOVED prices are
        historical. Same T2 stale-price contract as `_reprice_positions`: a
        falsy quote (0/None, `_get_current_price`'s fail-safe "no fresh
        data" signal) must never overwrite the last-known price. A single
        ticker's fetch raising must not abort the sweep for the rest.

        Held-ticker skip (whole-arc integration review finding, 2026-07-15):
        RiskMonitor refreshes HELD positions on its own, much tighter
        `compute_held_ttl` cadence (2-20s) against the SAME
        `stock_info:<ticker>` cache key (one shared KiwoomClient). A ticker
        that is BOTH held AND an ACTIVE watch entry (reachable —
        `add_to_watch_list` has no held-position guard, and the analysis/
        HITL approval route doesn't call `mark_watch_converted`) would get
        its cache entry overwritten here with this loop's much longer
        `compute_watch_ttl` TTL (10-60s), making RiskMonitor read a stale
        price for up to that TTL and delaying stop-loss/take-profit
        reaction. So held tickers are excluded from `active` up front — they
        stay owned exclusively by RiskMonitor. `W` (fed into
        `compute_watch_ttl`) is deliberately the ACTIVE-and-not-held count
        (i.e. what this sweep actually fetches), not the raw ACTIVE count,
        so the cadence reflects the real request load.
        """
        # E2-2: 장외에는 워치 가격 갱신 사이클 전체를 쉬게 한다(완전 idle
        # 결정, E2-1/RiskMonitor와 동일 패턴). 장외엔 신규 진입/기회판정
        # 자체가 무의미하므로 전체 skip이 안전. 큐 스케줄러/마감 엣지/체결
        # 폴링/reconciler는 게이트 밖(요건대로 미변경) — 이 함수
        # (_refresh_watch_prices)만 게이트.
        if not is_krx_open_cached():
            self._log_market_gate_once(closed=True)
            return
        self._log_market_gate_once(closed=False)

        held_tickers = {p.ticker for p in self._state.positions}
        active = [
            w
            for w in self._state.watch_list
            if w.status == WatchStatus.ACTIVE and w.ticker not in held_tickers
        ]
        ttl = compute_watch_ttl(len(active))
        for watched in active:
            try:
                price = await self._get_current_price(watched.ticker, ttl=ttl)
            except Exception as e:
                logger.error(
                    f"[Coordinator] Watch refresh failed for {watched.ticker}: {e}"
                )
                continue
            if not price:
                continue
            watched.current_price = price
            watched.last_checked = datetime.now()

    async def _watch_refresh_loop(self) -> None:
        """Background loop driving `_refresh_watch_prices` on a cadence that
        scales with the current ACTIVE watch count (monitoring-cadence-
        tuning arc, MAIN BODY). Same lifecycle shape as
        `_queue_scheduler_loop` — created in `start()`, cancelled in
        `stop()`.
        """
        try:
            while True:
                try:
                    await self._refresh_watch_prices()
                except Exception as e:
                    logger.error(f"[Coordinator] Watch refresh loop error: {e}")
                active_count = sum(
                    1
                    for w in self._state.watch_list
                    if w.status == WatchStatus.ACTIVE
                )
                await asyncio.sleep(compute_watch_ttl(active_count))
        except asyncio.CancelledError:
            pass

    async def _get_current_price(
        self, ticker: str, ttl: Optional[float] = None
    ) -> float:
        """Get current price for a ticker.

        `ttl`: optional cache-TTL override forwarded to
        `KiwoomClient.get_stock_info` (monitoring-cadence-tuning arc). Used
        by `RiskMonitor` (injected as this coordinator's `price_fetcher`) to
        pass a held-position-count-derived TTL
        (`services.trading.cadence.compute_held_ttl`) for its 1s poll of
        held positions; callers that omit it (e.g. `_reprice_positions`)
        keep today's prefix-default caching behavior unchanged.
        """
        if self._kiwoom:
            try:
                # KiwoomClient has no `get_quote` method (that was a
                # never-implemented ghost API — live logs spammed "no
                # attribute 'get_quote'" every RiskMonitor cycle, always
                # returning 0 and silently disabling stop-loss/take-profit
                # checks via the `current_price <= 0` guard). The real quote
                # API is `get_stock_info` (ka10001), same one
                # agents/tools/kr_market_data.py uses.
                info = await self._kiwoom.get_stock_info(ticker, ttl=ttl)
                return float(info.cur_prc)
            except Exception as e:
                logger.error(f"[Coordinator] Failed to get price for {ticker}: {e}")
                return 0

        # Simulation mode - return mock price
        return 50000  # 5만원

    def _on_price_update(self, ticker: str, price: float) -> None:
        """Price-sink for RiskMonitor's 1s poll (T1, MEDIUM finding A, review
        2026-07-13).

        RiskMonitor already fetches a fresh price for every watched ticker
        once a second, via the very same `_get_current_price` injected above
        as `price_fetcher` — but until this fix that fresh price was written
        only to the monitor's own `WatchConfig.last_price` and discarded, so
        `ManagedPosition.current_price` (and unrealized_pnl/exposure derived
        from it) was only ever refreshed by `_reprice_positions`, itself only
        called from `_refresh_account_info` at trade-decision time. Displayed
        P&L/exposure went stale between decisions even though live price data
        was already flowing. This callback closes that loop at the same 1s
        cadence, independent of trade decisions.

        Same T2 stale-price contract as `_reprice_positions`: a falsy price
        (0/None — `_get_current_price`'s fail-safe signal for "no fresh
        quote") must never overwrite a live position's last-known price.
        """
        if not price:
            return
        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if position is None:
            return
        position.current_price = price
        position.last_updated = datetime.now()

    # -------------------------------------------
    # Alerts & Callbacks
    # -------------------------------------------

    def set_alert_callback(self, callback: Callable[[TradingAlert], Awaitable[None]]):
        """Set callback for alerts."""
        self._alert_callback = callback

    def set_state_callback(self, callback: Callable[[TradingState], Awaitable[None]]):
        """Set callback for state changes."""
        self._state_callback = callback

    async def _on_alert(self, alert: TradingAlert):
        """Handle alert from risk monitor.

        G-2 (gap discipline, spec docs/superpowers/specs/
        2026-07-20-gap-discipline-design.md §N2): dedup by (ticker,
        alert_type) — REPLACE the UNRESOLVED alert already sitting in
        `_state.pending_alerts` for the same key with this new one, in
        place, instead of appending a duplicate. Before this fix every
        RiskMonitor alert (action_required or not) was appended here
        unconditionally on every call, so a repeatedly-firing trigger (e.g.
        a stop-loss re-evaluated on each 1s tick while the position stays
        watched) grew this list without bound for the process lifetime.

        G-2 review fix (2026-07-20): the FIRST version of this dedup
        (skip-append instead of replace) introduced a fresh bug —
        `RiskMonitor._add_alert` (risk_monitor.py) dedups the SAME
        (ticker, alert_type) key by REPLACING the existing pending entry
        with the new one (new id) on every tick, not skipping. Skip-append
        here left `_state.pending_alerts` pinned to the FIRST tick's stale
        id forever, while `GET /trading/alerts` (backed by
        `risk_monitor.get_pending_alerts()`) always showed the latest id —
        the two stores diverged. `handle_alert_action(latest_id, ...)` then
        silently no-op'd (id not found in `_state.pending_alerts`) and the
        stale entry could never be pruned, permanently blocking future
        alerts for that key. Replacing in place (mirroring RiskMonitor's
        own convention exactly) keeps both stores' ids in sync while still
        capping the list at one entry per unresolved key. Once the existing
        entry resolves (`alert.resolved = True`, or it is pruned — see
        `handle_alert_action`'s cleanup below), a fresh alert for the same
        key is appended as a new entry instead of replacing anything.
        `self._alert_callback`/`_notify_state_change` still fire on every
        call, deduped or not — only the list mutation is gated.
        """
        for idx, existing in enumerate(self._state.pending_alerts):
            if (
                not existing.resolved
                and existing.ticker == alert.ticker
                and existing.alert_type == alert.alert_type
            ):
                self._state.pending_alerts[idx] = alert
                break
        else:
            self._state.pending_alerts.append(alert)

        if self._alert_callback:
            await self._alert_callback(alert)

        await self._notify_state_change()

    async def _notify_state_change(self):
        """Notify state change."""
        if self._state_callback:
            await self._state_callback(self._state)

    # -------------------------------------------
    # Alert Actions
    # -------------------------------------------

    async def handle_alert_action(self, alert_id: str, action: str, data: Optional[dict] = None):
        """
        Handle user action on an alert.

        Args:
            alert_id: Alert ID
            action: Action to take
            data: Optional additional data
        """
        alert = next(
            (a for a in self._state.pending_alerts if a.id == alert_id),
            None
        )

        if not alert:
            logger.warning(f"[Coordinator] Alert {alert_id} not found")
            return

        logger.info(f"[Coordinator] Handling alert action: {alert_id} -> {action}")

        if action == "RESUME":
            await self.resume()

        elif action == "CLOSE_POSITION" and alert.ticker:
            await self._close_position(alert.ticker)

        elif action == "ADJUST_STOP_LOSS" and alert.ticker and data:
            new_sl = data.get("stop_loss")
            if new_sl:
                self.risk_monitor.update_stop_loss(alert.ticker, new_sl)
                # Also update the ManagedPosition so the adjusted stop is what
                # gets persisted — otherwise a restart reverts it to the old
                # value stored on the position (review #4).
                position = next(
                    (p for p in self._state.positions if p.ticker == alert.ticker),
                    None,
                )
                if position is not None:
                    position.stop_loss = new_sl
                    position.last_updated = datetime.now()
                self._schedule_persist()

        elif action == "EXECUTE_STOP_LOSS" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                # S-3 review carry-over (S-2 in-flight guard, 5th SELL entry
                # point): a user-confirmed alert click can race an
                # autonomous defensive exit (RiskMonitor's AGENT_AUTO tick,
                # or PositionManager) for the SAME ticker — same guard as
                # _close_position/_reduce_position/
                # _execute_order_from_monitor/on_trade_approved's SELL/
                # REDUCE main path (see _close_position's docstring).
                # Guard-denied: skip as a no-op — the position stays
                # tracked/watched, the OTHER engine's exit already owns it.
                if self._acquire_defensive_exit_guard(alert.ticker):
                    try:
                        # Update risk agent status - executing stop-loss
                        self._update_agent_status(
                            "risk",
                            AgentStatus.WORKING,
                            task=f"Executing stop-loss for {config.stock_name or alert.ticker}",
                            processing_stock=alert.ticker,
                            processing_stock_name=config.stock_name,
                            trade_details={
                                "action": "STOP_LOSS",
                                "quantity": config.quantity,
                                "entry_price": config.entry_price,
                                "stop_loss": config.stop_loss,
                                "current_price": config.last_price,
                            },
                        )

                        price = config.last_price or config.entry_price
                        # L2 (spec D2): decision_id/session_id left unset (NULL) on
                        # purpose — a user-confirmed alert action has no upstream
                        # decision record to thread; NULL is the correct lineage
                        # state here, not a gap to wire.
                        order = OrderRequest(
                            ticker=alert.ticker,
                            stock_name=config.stock_name,
                            side=OrderSide.SELL,
                            quantity=config.quantity,
                            price=price,
                            # S-3 (survival discipline): MARKET, not the
                            # OrderRequest default of LIMIT — same rationale
                            # as _close_position's MARKET switch.
                            order_type=OrderType.MARKET,
                            reason="User-confirmed stop-loss",
                        )
                        result = await self._execute_order(order)
                        # Track the ACTUAL fill — a rejected/unfilled sell keeps the
                        # position under defense instead of orphaning it (review #8).
                        self._apply_sell_fill(alert.ticker, result.filled_quantity, order=order, result=result)
                    finally:
                        self._release_defensive_exit_guard(alert.ticker)

        elif action == "EXECUTE_TAKE_PROFIT" and alert.ticker:
            config = self.risk_monitor._watching.get(alert.ticker)
            if config:
                # S-3 review carry-over — same in-flight guard as
                # EXECUTE_STOP_LOSS above (see its comment for the full
                # rationale).
                if self._acquire_defensive_exit_guard(alert.ticker):
                    try:
                        # Update risk agent status - executing take-profit
                        self._update_agent_status(
                            "risk",
                            AgentStatus.WORKING,
                            task=f"Executing take-profit for {config.stock_name or alert.ticker}",
                            processing_stock=alert.ticker,
                            processing_stock_name=config.stock_name,
                            trade_details={
                                "action": "TAKE_PROFIT",
                                "quantity": config.quantity,
                                "entry_price": config.entry_price,
                                "take_profit": config.take_profit,
                                "current_price": config.last_price,
                            },
                        )

                        price = config.last_price or config.take_profit
                        # L2 (spec D2): decision_id/session_id left unset (NULL) —
                        # same rationale as EXECUTE_STOP_LOSS above.
                        order = OrderRequest(
                            ticker=alert.ticker,
                            stock_name=config.stock_name,
                            side=OrderSide.SELL,
                            quantity=config.quantity,
                            price=price,
                            # S-3: MARKET, not LIMIT — same rationale as
                            # EXECUTE_STOP_LOSS above.
                            order_type=OrderType.MARKET,
                            reason="User-confirmed take-profit",
                        )
                        result = await self._execute_order(order)
                        self._apply_sell_fill(alert.ticker, result.filled_quantity, order=order, result=result)
                    finally:
                        self._release_defensive_exit_guard(alert.ticker)

        elif action == "HOLD":
            # Do nothing, just acknowledge
            pass

        # Mark alert as resolved
        self.risk_monitor.resolve_alert(alert_id)
        self._state.pending_alerts = [a for a in self._state.pending_alerts if a.id != alert_id]

        await self._notify_state_change()

    async def _close_position(
        self,
        ticker: str,
        decision_id: Optional[str] = None,
        _skip_inflight_guard: bool = False,
        reason: Optional[str] = None,
    ) -> Optional[OrderResult]:
        """Close a position at market price.

        Returns the OrderResult of the placed SELL (or None if there was no
        position to close, or a concurrent defensive exit already owns this
        ticker — see the guard note below) — P1 (2026-07-15) added this
        return value so `_reduce_position` can delegate here when its own
        oversell clamp collapses a partial request into a full close, and
        still learn the ACTUAL filled quantity. Existing callers that ignore
        the return value (`handle_alert_action`'s CLOSE_POSITION,
        PositionManager's `_execute_close_position`) are unaffected.

        `decision_id` (L2, spec D2): optional durable decision-ledger id
        threaded into OrderRequest.session_id when the caller has one (e.g.
        an agent-chat-discussed exit) — defaults to None, so every existing
        call site (a user-initiated close via handle_alert_action, or a
        `_reduce_position` delegation with no id of its own) is byte-for-byte
        unchanged. NULL here is correct, not a gap, for callers with no
        upstream decision to cite.

        `reason` (Important 2, 최종 전체 브랜치 리뷰): the fill notification's
        "경로"(source) field — defaults to "User-initiated close" for a
        caller that has no more specific label of its own (`handle_alert_action`
        CLOSE_POSITION, a genuine human tap). Before this fix EVERY caller
        got that same hardcoded string, so PositionManager's autonomous
        stop-loss/take-profit close (`_execute_close_position`, which passes
        its own accurate label through this param) reported to the phone as
        "사람이 한 것" — exactly the two fills this notification arc exists
        to surface (07-24 stop-loss, 07-27 take-profit) arrived mislabeled.

        S-2 review fix: guarded by the coordinator-wide in-flight
        defensive-exit set (`_acquire_defensive_exit_guard`) so a concurrent
        close from a DIFFERENT engine (RiskMonitor via
        `_execute_order_from_monitor`, or another PositionManager tick) for
        the SAME ticker is skipped as a no-op instead of doubling the sell.
        `_skip_inflight_guard=True` is for `_reduce_position`'s OWN
        delegation into this method when its oversell clamp collapses a
        partial request into a full close — `_reduce_position` already holds
        the guard for this ticker at that point, so re-acquiring here would
        self-deny (the ticker is already "in flight", owned by the very call
        that's delegating); skipping applies ONLY to that one internal call
        site, never to an external caller.
        """
        if not _skip_inflight_guard and not self._acquire_defensive_exit_guard(ticker):
            return None

        try:
            position = next(
                (p for p in self._state.positions if p.ticker == ticker),
                None
            )

            if not position:
                logger.warning(f"[Coordinator] Position {ticker} not found")
                return None

            order = OrderRequest(
                ticker=ticker,
                stock_name=position.stock_name,
                side=OrderSide.SELL,
                quantity=position.quantity,
                price=position.current_price,
                # S-3 (survival discipline): defensive/user-initiated closes
                # submit as MARKET, not the OrderRequest default of LIMIT —
                # matches risk_monitor.py's existing _execute_stop_loss/
                # _execute_take_profit convention (P2-4) so a gap/crash
                # reports the true adverse fill instead of the (favorable)
                # price captured above. `price` is kept as the mock/paper
                # broker's fill-price fallback and the live Kiwoom fill-
                # confirm's fallback_price — MARKET orders never actually
                # send it to the broker (order_agent.py only tick-rounds/
                # sends price for LIMIT).
                order_type=OrderType.MARKET,
                reason=reason or "User-initiated close",
                session_id=decision_id,
            )

            result = await self._execute_order(order)
            # Important 4: 브로커 거부는 예외가 아니라 정상 결과로 온다 —
            # 아래 _apply_sell_fill의 filled_quantity<=0 가드는 무통지이므로
            # 여기서 명시적으로 실패를 알린다.
            self._handle_defensive_sell_rejection(position, order, result)
            # Only drop/reduce tracking by the ACTUAL fill — a rejected or unfilled
            # sell must keep the position under defense (A3).
            self._apply_sell_fill(ticker, result.filled_quantity, order=order, result=result)
            # E1-3: a partial/unfilled defensive close still has broker-side
            # exposure nothing is watching yet — register the remainder with the
            # fill tracker (same helper on_trade_approved's BUY/SELL entries use,
            # E1-1/E1-2) so the ka10076 poll can pick up the post-fill later.
            # stop_loss/take_profit are None: this is an exit, not an entry with
            # defense levels of its own to carry forward.
            self._register_unfilled_sell(ticker, position, order, result)
            return result
        finally:
            if not _skip_inflight_guard:
                self._release_defensive_exit_guard(ticker)

    async def _reduce_position(
        self,
        ticker: str,
        quantity: int,
        decision_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[OrderResult]:
        """Place a SELL order for a SPECIFIC quantity — a partial reduce, not
        a full close (P1, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).

        `reason` (Important 2, 최종 전체 브랜치 리뷰): same source-label
        threading as `_close_position` — forwarded to the delegated full
        close below and used verbatim on the direct-partial order; defaults
        to "Autonomous partial reduce" for a caller with no more specific
        label (today's only caller, `_execute_reduce_position`, always
        passes one).

        `PositionManager._execute_reduce_position` is the (only) autonomous
        caller today: it already passes the request through
        `check_autonomy(SELL)` before reaching here, mirroring the existing
        full-close pattern (`PositionManager._execute_close_position` gates,
        then calls `_close_position`).

        Oversell-proof against THIS coordinator's OWN tracked quantity. The
        caller may be working off a separate ledger (PositionManager's
        `MonitoredPosition`, distinct from this coordinator's
        `ManagedPosition`) that can diverge from this one, so the clamp is
        re-applied here rather than trusted from the caller: `sell_qty =
        min(quantity, position.quantity)`. If that clamp collapses the
        request into a full close (requested >= held), delegates to the
        existing `_close_position` instead of duplicating its
        position-removal/risk-monitor-stop cleanup.

        `decision_id` (L2, spec D2): optional durable decision-ledger id,
        threaded into OrderRequest.session_id (and passed through to the
        delegated `_close_position` call below) — defaults to None so every
        existing call site is byte-for-byte unchanged.

        Returns the OrderResult of whichever order was actually placed (the
        partial sell, or the delegated full close) so the caller can react to
        the ACTUAL filled quantity — never the requested one — the same
        choke-point discipline `_apply_sell_fill` already applies to every
        other SELL path.

        S-2 review fix: guarded by the coordinator-wide in-flight
        defensive-exit set for the same dual-engine race `_close_position`
        guards against (see its docstring) — acquired ONCE here at the top
        and held across the delegated `_close_position(_skip_inflight_guard=
        True)` call below, so the delegation never tries to re-acquire it.
        """
        if not self._acquire_defensive_exit_guard(ticker):
            return None

        try:
            position = next(
                (p for p in self._state.positions if p.ticker == ticker), None
            )
            if not position:
                logger.warning(f"[Coordinator] Position {ticker} not found for reduce")
                return None

            sell_qty = min(quantity, position.quantity)
            if sell_qty <= 0:
                logger.warning(
                    f"[Coordinator] Reduce for {ticker} requested non-positive "
                    f"sell quantity ({quantity} vs held {position.quantity})"
                )
                return None

            if sell_qty >= position.quantity:
                # Clamp collapses this into a full close — delegate rather than
                # duplicate _close_position's removal/stop-cleanup logic. This
                # call already holds the in-flight guard for `ticker` (acquired
                # above), so tell _close_position to skip re-acquiring it —
                # re-acquiring would self-deny (see _close_position's guard
                # docstring) and a second release here would double-discard.
                return await self._close_position(
                    ticker, decision_id=decision_id, _skip_inflight_guard=True,
                    reason=reason,
                )

            order = OrderRequest(
                ticker=ticker,
                stock_name=position.stock_name,
                side=OrderSide.SELL,
                quantity=sell_qty,
                price=position.current_price,
                # S-3: same MARKET rationale as _close_position above — a
                # partial defensive reduce must report the true fill too.
                order_type=OrderType.MARKET,
                reason=reason or "Autonomous partial reduce",
                session_id=decision_id,
            )

            result = await self._execute_order(order)
            # Important 4: 브로커 거부는 예외가 아니라 정상 결과로 온다 —
            # 아래 _apply_sell_fill의 filled_quantity<=0 가드는 무통지이므로
            # 여기서 명시적으로 실패를 알린다.
            self._handle_defensive_sell_rejection(position, order, result)
            # Reconcile by the ACTUAL fill, not the requested quantity — same
            # choke point every other SELL path uses (full → remove, partial →
            # decrement, none → retain).
            self._apply_sell_fill(ticker, result.filled_quantity, order=order, result=result)
            # E1-3: register any unfilled remainder (see _close_position's same
            # call for the full rationale) — the clamp-to-full-close branch above
            # already gets this via the delegated _close_position call, so only
            # this direct-partial branch needs its own call.
            self._register_unfilled_sell(ticker, position, order, result)
            return result
        finally:
            self._release_defensive_exit_guard(ticker)

    async def _clamp_add_for_liquidity(
        self, ticker: str, quantity: int, position: ManagedPosition
    ) -> int:
        """자율 ADD 수량을 유동성 천장 안으로 깎는다(총 포지션 기준).

            allowed_notional = max(0, ADTV * SIZING_PARTICIPATION_PCT - 보유평가액)

        **추가분이 아니라 총 포지션이 기준인 이유**: 추가분에만 캡을 걸면 매번
        캡만큼 더 살 수 있어 천장을 영원히 넘는다. 라이브 실측(094840)에서
        ADTV 5.3억 -> 캡 265만원인데 이미 1,729만원(6.5배)을 보유 중이었다 —
        이 경우 허용 ADD는 0이어야 한다.

        **ADTV 미상은 fail-open**(C1 `apply_liquidity_cap`과 동일 규약):
        ADD는 이미 `check_autonomy(BUY)` 게이트를 통과한 요청이고, 여기서
        fail-closed로 막으면 조회 실패가 곧 포지션 관리 정지가 된다. 대신
        경고를 남겨 캡이 조용히 꺼진 것을 관측할 수 있게 한다.

        never-raise — 유동성 조회 실패가 ADD 경로를 죽이면 안 된다.
        """
        from services.discovery.liquidity import liquidity_cap_value

        try:
            adtv = await self.portfolio_agent._resolve_adtv(ticker)
        except Exception as e:
            logger.warning(
                f"[Coordinator] ADD 유동성 조회 실패 {ticker}: {e} — 캡 미적용"
            )
            return quantity

        cap = liquidity_cap_value(adtv)
        if cap is None:
            logger.warning(
                f"[Coordinator] ADD 유동성 캡 미적용 {ticker}: adtv_unknown"
            )
            return quantity

        price = position.current_price or position.avg_price
        # NaN 가드: `not price`도 `price <= 0`도 NaN을 통과시키고(NaN 비교는
        # 항상 False), 그러면 아래 int(0.0/nan)이 ValueError를 던져 docstring의
        # never-raise 계약이 깨진다.
        if not price or not math.isfinite(price) or price <= 0:
            logger.warning(
                f"[Coordinator] ADD 유동성 캡 미적용 {ticker}: 가격 없음/비유한"
            )
            return quantity

        held_notional = position.quantity * price
        allowed = int(max(0.0, cap - held_notional) / price)

        if allowed < quantity:
            logger.info(
                f"[Coordinator] ADD 유동성 캡 적용 {ticker}: "
                f"{quantity}주 -> {allowed}주 "
                f"(ADTV {adtv / 1e8:,.1f}억, 캡 {cap / 1e4:,.0f}만원, "
                f"보유 {held_notional / 1e4:,.0f}만원)"
            )
        return min(quantity, allowed)

    async def _add_to_position(
        self, ticker: str, quantity: int, decision_id: Optional[str] = None
    ) -> Optional[OrderResult]:
        """Place a BUY order for a SPECIFIC quantity to increase an existing
        position — the opposite side of `_reduce_position` (P2, 2026-07-15,
        docs/superpowers/plans/2026-07-15-position-mgmt-execution.md).

        `PositionManager._execute_add_position` is the (only) autonomous
        caller today: it already passes the request through
        `check_autonomy(BUY)` — the SAME gate (master gate, market mode,
        paper-only, daily-loss breaker, max-open-positions, per-trade
        notional cap) the entry BUY path (`on_trade_approved`) enforces —
        before reaching here.

        Requires a matching position on THIS coordinator's OWN ledger
        (`_state.positions`). The caller (PositionManager) works off a
        SEPARATE ledger (`MonitoredPosition`) that can diverge from this
        one — mirrors `_reduce_position`'s conservative contract: rather
        than blindly opening an untracked position with unknown stop
        levels, a divergent/desynced ledger is a no-op here (logged), same
        as a reduce against a ticker this coordinator doesn't track.

        On any real fill, reuses `_add_position`'s existing "average in"
        merge (quantity summed, avg_price recomputed as the cost-weighted
        average) — the exact same code path an entry BUY's
        `on_trade_approved` already exercises, so this doesn't duplicate
        that arithmetic.

        `decision_id` (L2, spec D2): optional durable decision-ledger id,
        threaded into OrderRequest.session_id — defaults to None so every
        existing call site is byte-for-byte unchanged.

        Returns the OrderResult of the placed order (or None if there's no
        matching position to add to, or the requested quantity is
        non-positive), so the caller can react to the ACTUAL filled
        quantity — never the requested one.
        """
        position = next(
            (p for p in self._state.positions if p.ticker == ticker), None
        )
        if not position:
            logger.warning(f"[Coordinator] Position {ticker} not found for add")
            return None

        if quantity <= 0:
            logger.warning(
                f"[Coordinator] Add for {ticker} requested non-positive "
                f"quantity ({quantity})"
            )
            return None

        # 유동성 캡 (2026-07-27 유동성 인지 아크 후속). 진입 BUY는 C1 사이징
        # 캡(ADTV의 0.5%)을 받는데 이 ADD 경로만 우회하고 있었다 — 진입이
        # 0.5%를 지켜도 추가매수가 천장을 넘는 유일한 exposure-increasing
        # 경로였다. 기준은 추가분이 아니라 **총 포지션**이다: 추가분에만
        # 캡을 걸면 매번 캡만큼 더 살 수 있어 천장을 영원히 넘는다.
        if getattr(get_settings(), "LIQUIDITY_SIZING_CAP_ENABLED", True):
            clamped = await self._clamp_add_for_liquidity(ticker, quantity, position)
            if clamped <= 0:
                # 원장 불일치(position not found)와 **구별되는** 결과를 돌려준다.
                # 호출자(PositionManager._execute_add_position)는 None을 오직
                # "코디네이터 원장에 포지션 없음"으로 해석해 🚨 desync 통지를
                # 보내는데, 유동성 차단은 원장 문제가 아니라 정상 억제다.
                # 이미 캡을 초과 보유한 종목은 ADD가 매번 0이 되므로, None을
                # 돌려주면 토론 주기마다 허위 경보가 반복된다.
                logger.warning(
                    f"[Coordinator] ADD 유동성 차단 {ticker}: "
                    f"{quantity}주 요청 -> 0주 (총 포지션이 이미 유동성 천장 초과)"
                )
                return OrderResult(
                    order_id="",
                    ticker=ticker,
                    side=OrderSide.BUY,
                    requested_quantity=quantity,
                    filled_quantity=0,
                    avg_price=0,
                    status=ORDER_STATUS_REJECTED_LIQUIDITY_CAP,
                    message="유동성 캡 — 총 포지션이 ADTV 참여율 상한을 초과",
                )
            quantity = clamped

        order = OrderRequest(
            ticker=ticker,
            stock_name=position.stock_name,
            side=OrderSide.BUY,
            quantity=quantity,
            price=position.current_price,
            reason="Autonomous add-to-position",
            session_id=decision_id,
        )

        result = await self._execute_order(order)
        if result.filled_quantity > 0:
            # Reuse the SAME average-in merge an entry BUY's
            # on_trade_approved already exercises via _add_position — sums
            # quantity, recomputes avg_price as the cost-weighted average
            # against whatever this coordinator's ledger already tracked.
            self._add_position(
                ManagedPosition(
                    ticker=ticker,
                    stock_name=position.stock_name,
                    quantity=result.filled_quantity,
                    avg_price=result.avg_price,
                    current_price=result.avg_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    stop_loss_mode=position.stop_loss_mode,
                    status=PositionStatus.FILLED,
                    risk_score=position.risk_score,
                )
            )

        return result

    # -------------------------------------------
    # State Access
    # -------------------------------------------

    @property
    def state(self) -> TradingState:
        """Get current trading state."""
        # 외부 조회(상태 API, 포트폴리오 요약 등)가 게이트/증가/영속 호출 없이
        # 하루의 첫 접근이 될 수도 있다 — 여기서도 롤오버를 확인해야 새 날의
        # 첫 조회가 어제 카운트를 보여주지 않는다.
        self._maybe_reset_daily_trades()
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if trading is active."""
        return self._state.mode == TradingMode.ACTIVE

    def get_portfolio_summary(self) -> dict:
        """Get portfolio summary."""
        # `self._state`를 직접 넘겨 `state` 프로퍼티(위)를 건너뛰므로 여기서도
        # 롤오버를 확인해야 한다 — 그렇지 않으면 이 경로로만 조회할 때
        # daily_trades가 새 날에도 어제 값으로 보인다.
        self._maybe_reset_daily_trades()
        return self.portfolio_agent.get_portfolio_summary(self._state)

    def get_pending_alerts(self) -> List[TradingAlert]:
        """Get pending alerts."""
        return self.risk_monitor.get_pending_alerts()

    # -------------------------------------------
    # Agent Status Management
    # -------------------------------------------

    def _update_agent_status(
        self,
        agent: str,
        status: AgentStatus,
        task: Optional[str] = None,
        action: Optional[str] = None,
        error: Optional[str] = None,
        # 세부 정보 (Sub Agent Status 개선)
        processing_stock: Optional[str] = None,
        processing_stock_name: Optional[str] = None,
        trade_details: Optional[dict] = None,
        analysis_summary: Optional[dict] = None,
        last_result: Optional[dict] = None,
    ):
        """Update status of a specific agent with detailed information."""
        if agent in self._state.agent_states:
            agent_state = self._state.agent_states[agent]
            agent_state.status = status
            agent_state.current_task = task
            if action:
                agent_state.last_action = action
                agent_state.last_action_time = datetime.now()
            if error:
                agent_state.error_message = error
            else:
                agent_state.error_message = None

            # 세부 정보 업데이트
            if processing_stock is not None:
                agent_state.processing_stock = processing_stock
            if processing_stock_name is not None:
                agent_state.processing_stock_name = processing_stock_name
            if trade_details is not None:
                agent_state.trade_details = trade_details
            if analysis_summary is not None:
                agent_state.analysis_summary = analysis_summary
            if last_result is not None:
                agent_state.last_result = last_result

    def _complete_agent_task(self, agent: str, success: bool = True):
        """Mark agent task as completed."""
        if agent in self._state.agent_states:
            agent_state = self._state.agent_states[agent]
            agent_state.status = AgentStatus.IDLE
            agent_state.current_task = None
            if success:
                agent_state.tasks_completed += 1
            else:
                agent_state.tasks_failed += 1

    def get_agent_states(self) -> dict:
        """Get all agent states as dict."""
        return {
            name: state.model_dump()
            for name, state in self._state.agent_states.items()
        }

    # -------------------------------------------
    # Trade Queue Management
    # -------------------------------------------

    def add_to_queue(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        action: str,
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        risk_score: int,
        reason: str,
        autonomous: bool = False,
        quantity: Optional[int] = None,
    ) -> QueuedTrade:
        """Add a trade to the queue for later execution.

        quantity carries the size decided at queueing time. It MUST be preserved
        for autonomous trades: the execution-time re-gate's notional cap denies
        a BUY/ADD of unknown size (fail-closed), so dropping it would cancel
        every queued autonomous buy — audit finding A5 (2026-07-12).
        """
        queued_trade = QueuedTrade(
            session_id=session_id,
            ticker=ticker,
            stock_name=stock_name,
            action=action,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_score=risk_score,
            reason=reason,
            autonomous=autonomous,
        )

        self._state.trade_queue.append(queued_trade)

        self._log_activity(
            ActivityType.TRADE_QUEUED,
            f"Trade queued: {action} {stock_name or ticker} (reason: {reason})",
            agent="system",
            ticker=ticker,
            details={
                "queue_id": queued_trade.id,
                "action": action,
                "entry_price": entry_price,
                "reason": reason,
            },
        )

        logger.info(f"[Coordinator] Trade queued: {queued_trade.id}")
        self._schedule_persist()
        return queued_trade

    def get_trade_queue(self, include_all: bool = False) -> List[QueuedTrade]:
        """
        Get trades in queue.

        Args:
            include_all: If True, return all trades including FAILED/COMPLETED.
                        If False, return only PENDING and PROCESSING trades.
        """
        if include_all:
            return list(self._state.trade_queue)

        # Default: return active trades (PENDING or PROCESSING)
        return [
            t for t in self._state.trade_queue
            if t.status in (QueueStatus.PENDING, QueueStatus.PROCESSING)
        ]

    def dismiss_trade(self, queue_id: str) -> bool:
        """
        Dismiss a completed/failed/cancelled trade from the queue.

        Only removes trades that are not PENDING or PROCESSING.
        """
        for i, trade in enumerate(self._state.trade_queue):
            if trade.id == queue_id:
                if trade.status in (QueueStatus.PENDING, QueueStatus.PROCESSING):
                    logger.warning(
                        f"[Coordinator] Cannot dismiss active trade: {queue_id} (status={trade.status})"
                    )
                    return False

                self._state.trade_queue.pop(i)
                logger.info(f"[Coordinator] Trade dismissed from queue: {queue_id}")
                self._schedule_persist()
                return True
        return False

    def cancel_queued_trade(self, queue_id: str) -> bool:
        """Cancel a queued trade."""
        for trade in self._state.trade_queue:
            if trade.id == queue_id and trade.status == QueueStatus.PENDING:
                trade.status = QueueStatus.CANCELLED

                self._log_activity(
                    ActivityType.TRADE_DEQUEUED,
                    f"Queued trade cancelled: {trade.ticker}",
                    agent="system",
                    ticker=trade.ticker,
                    details={"queue_id": queue_id},
                )

                logger.info(f"[Coordinator] Queued trade cancelled: {queue_id}")
                self._schedule_persist()
                return True
        return False

    async def process_trade_queue(self):
        """Process pending trades in queue (call when market opens).

        Re-entrancy-guarded: a second concurrent call returns immediately so a
        trade already being processed is not executed twice.
        """
        if self._processing_queue:
            logger.info("[Coordinator] process_trade_queue already running — skipping")
            return
        self._processing_queue = True
        try:
            await self._process_trade_queue_inner()
        finally:
            self._processing_queue = False

    async def _process_trade_queue_inner(self):
        pending_trades = self.get_trade_queue()
        if not pending_trades:
            return

        logger.info(f"[Coordinator] Processing {len(pending_trades)} queued trades")

        self._update_agent_status("order", AgentStatus.WORKING, f"Processing {len(pending_trades)} queued trades")

        for trade in pending_trades:
            try:
                trade.status = QueueStatus.PROCESSING

                self._log_activity(
                    ActivityType.TRADE_DEQUEUED,
                    f"Processing queued trade: {trade.action} {trade.ticker}",
                    agent="order",
                    ticker=trade.ticker,
                    details={"queue_id": trade.id},
                )

                # R3: autonomy-originated trades must pass the gate AGAIN at
                # execution time — the verdict from queueing time is stale
                # (mode may have been flipped to HITL, a limit may have tripped).
                if trade.autonomous:
                    from services.autonomy import check_autonomy

                    gate = await check_autonomy(
                        "kiwoom",
                        action=trade.action,
                        quantity=trade.quantity,
                        entry_price=trade.entry_price,
                    )
                    if not gate.allowed:
                        trade.status = QueueStatus.CANCELLED
                        self._log_activity(
                            ActivityType.TRADE_DEQUEUED,
                            f"Queued autonomous trade cancelled by gate: {trade.action} "
                            f"{trade.ticker} ({gate.check}: {gate.reason})",
                            agent="order",
                            ticker=trade.ticker,
                            details={"queue_id": trade.id, "gate_check": gate.check},
                        )
                        continue

                # Execute the trade
                allocation = await self.on_trade_approved(
                    session_id=trade.session_id,
                    ticker=trade.ticker,
                    stock_name=trade.stock_name,
                    action=trade.action,
                    entry_price=trade.entry_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    risk_score=trade.risk_score,
                    quantity_override=trade.quantity,
                    autonomous=trade.autonomous,
                    queue_id=trade.id,
                )

                trade.allocation = allocation
                trade.executed_at = datetime.now()

                if allocation.quantity > 0:
                    trade.status = QueueStatus.COMPLETED
                else:
                    trade.status = QueueStatus.FAILED
                    trade.error_message = allocation.rationale

            except Exception as e:
                logger.error(f"[Coordinator] Failed to process queued trade {trade.id}: {e}")
                trade.status = QueueStatus.FAILED
                trade.error_message = str(e)

        self._complete_agent_task("order", True)
        if self._persistence_active:
            await self._persist_state()
        await self._notify_state_change()

    async def _run_discovery_scan(self) -> bool:
        """DS-5: trigger a discovery-mode background scan and wait for it to
        finish, capped at a SC-2 dynamic, universe-proportional timeout (see
        `_compute_discovery_scan_timeout_seconds`; floor/fallback
        `_DISCOVERY_SCAN_TIMEOUT_SECONDS`, cap `_DISCOVERY_SCAN_TIMEOUT_
        CAP_SECONDS` — spec §2 SC-2). Only ever called from
        `_check_queue_on_market_open` behind the `settings.DISCOVERY_ENABLED`
        kill switch.

        Never raises — every branch below is defensive and returns False on
        anything but a clean scan-session status of ScanStatus.COMPLETED, so
        a stuck/erroring/never-started scan degrades to "skip promotion for
        today" rather than breaking the market-close scheduler tick.

        Completion detection is polling-based (`get_progress().status`,
        `_DISCOVERY_SCAN_POLL_INTERVAL_SECONDS` apart) because
        BackgroundScanner exposes no awaitable completion signal — this is
        the same public surface (`get_progress()`/`start_scan()`/
        `stop_scan()`) app/api/routes/scanner.py's own status endpoints
        already use, no reach into scanner internals.

        On timeout, `stop_scan()` is called so the scanner doesn't keep
        chewing through the universe (and holding the shared Kiwoom rate
        budget) long after the EOD chain has moved on without it (spec §3:
        "스캔 태스크는 stop 시도").
        """
        scanner = await get_background_scanner()

        # Important (DS-5 review fix): `start_scan()` is a silent no-op when
        # a scan of ANY mode is already in flight (scanner.py:371-373 --
        # `if self._running: logger.warning(...); return`, no exception, no
        # signal). The OLD guard below (`get_progress().status != RUNNING`)
        # ran only AFTER calling start_scan, so it could not tell "my scan
        # just started" apart from "someone else's manual scan was already
        # RUNNING and start_scan() silently no-op'd" -- both look like
        # status==RUNNING, and the old code would go on to poll a manual
        # scan it never started to completion and report scan_ok=True for
        # today's discovery, even though nothing discovery-specific ever
        # ran. Checking the scanner's own `is_running` BEFORE calling
        # start_scan at all closes that gap: a busy scanner (manual or
        # otherwise) skips the trigger entirely rather than being mistaken
        # for this call's own scan.
        if scanner.is_running:
            logger.warning(
                "[Coordinator] discovery_scan_skipped_scanner_busy — a scan "
                "is already running; skipping today's discovery scan trigger"
            )
            return False

        try:
            await scanner.start_scan(mode="discovery", notify_progress=False)
        except Exception as e:
            logger.warning(f"[Coordinator] Discovery scan failed to start: {e}")
            return False

        progress_after_start = scanner.get_progress()
        if progress_after_start.status != ScanStatus.RUNNING:
            logger.warning(
                "[Coordinator] Discovery scan did not start (scanner busy?) "
                "— skipping today's discovery"
            )
            return False

        # SC-2: read the universe size off the SAME progress snapshot used
        # for the RUNNING confirmation above (no extra get_progress() call)
        # — `start_scan()` has already synchronously set `total_stocks =
        # len(stock_list)` by the time it returns (scanner.py), so this is
        # never a stale/pre-scan read. `getattr` (not `.total_stocks`
        # directly) tolerates progress objects that don't carry the field at
        # all, which folds into the same "universe unavailable" fallback
        # path as a real 0/None reading.
        universe = getattr(progress_after_start, "total_stocks", None)
        timeout_seconds = _compute_discovery_scan_timeout_seconds(universe)

        async def _poll_until_not_running() -> None:
            while scanner.get_progress().status == ScanStatus.RUNNING:
                await asyncio.sleep(_DISCOVERY_SCAN_POLL_INTERVAL_SECONDS)

        try:
            await asyncio.wait_for(
                _poll_until_not_running(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[Coordinator] Discovery scan timed out after "
                f"{timeout_seconds}s (universe={universe}) — proceeding "
                "with EOD chain, promotion skipped for today"
            )
            try:
                # FI-1: reason="timeout" -- this stop still follows the
                # scan's own notify_progress preference (start_scan(mode=
                # "discovery", notify_progress=False) above), it just isn't
                # unconditionally suppressed the way an FE-initiated manual
                # stop is.
                await scanner.stop_scan(reason="timeout")
            except Exception as e:
                logger.warning(f"[Coordinator] Discovery scan stop_scan cleanup failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"[Coordinator] Discovery scan wait failed: {e}")
            return False

        status = scanner.get_progress().status
        if status != ScanStatus.COMPLETED:
            logger.warning(
                f"[Coordinator] Discovery scan ended with status={status} "
                "— promotion skipped for today"
            )
            return False
        return True

    async def _check_queue_on_market_open(self) -> None:
        """One scheduler tick: process the queue on a KRX closed→open transition,
        and expire tracked orders on the inverse open→closed transition (F3).
        The open→closed edge ALSO writes the day's durable EOD performance
        snapshot (Phase1 Task 5/C3b — see .eod_snapshot.write_daily_snapshot),
        after the fill poll/expiry so it reflects the final post-close ka10076
        fills, and then runs the Phase2 EOD review chain (regime snapshot +
        per-agent calibration + review report + regime FK backfill — see
        .eod_orchestrator.run_eod_review), which reads that snapshot row so
        it MUST run after it exists.

        start() already drains the queue if the market is open at start time; this
        covers the case where the system is started (or a trade is queued) while
        the market is closed and the market opens later. Only the EDGE triggers —
        an already-open market is not re-processed every tick. The execution-time
        re-gate (R5-P0) re-checks autonomy safety when each queued trade runs.

        The open→closed edge is the local signal for "nothing placed today can
        fill any further" — KRX limit orders are day-valid and there is no
        broker push telling us the session ended, so every still-TRACKING order
        is expired and notified once, on the edge only (mirrors the open-edge
        guard so a closed market doesn't re-notify every tick).
        """
        is_open = self._market_hours.get_market_session(MarketType.KRX).is_open
        if is_open and not self._market_was_open and self.get_trade_queue():
            logger.info("[Coordinator] Market opened — processing queued trades")
            await self.process_trade_queue()
        elif not is_open and self._market_was_open:
            # F3 review HIGH: poll BEFORE expiring — the post-close ka10076
            # snapshot is final and includes closing-auction fills; expiring
            # first would drop a fill that landed on this very edge.
            await self._poll_tracked_fills()
            await self._expire_tracked_orders_on_market_close()

            # DS-5: discovery scan trigger, behind the DISCOVERY_ENABLED
            # kill switch — spec §3 chain order. off (default) means this
            # whole block, AND the run_discovery_pipeline block below, are
            # never entered at all: the remaining 8-step chain immediately
            # below is byte-identical to before this feature existed.
            # Whole-block try/except mirrors every other EOD step's
            # never-raise contract even though `_run_discovery_scan` is
            # already internally never-raise — defense in depth per spec.
            discovery_scan_ok = False
            if get_settings().DISCOVERY_ENABLED:
                try:
                    discovery_scan_ok = await self._run_discovery_scan()
                except Exception as e:
                    logger.warning(f"[Coordinator] Discovery scan step failed: {e}")

            await write_daily_snapshot(self, await get_storage_service(), datetime.now().strftime("%Y-%m-%d"))  # T5c: 마감 1회
            await run_eod_review(self, await get_storage_service(), datetime.now().strftime("%Y-%m-%d"))  # Phase2 T4: EOD 리뷰(레짐/캘리브레이션/리포트+FK 백필)
            await run_strategy_consensus(self, await get_storage_service(), datetime.now().strftime("%Y-%m-%d"))  # Phase3: EOD 전략 합의(리뷰 소비→TradingStrategy 갱신+버전 영속; 타임아웃/실패는 내부 소유)
            await wait_for_pending_trade_fill_writes()  # Minor 2 (final review): drain in-flight fire-and-forget record_trade_fill tasks (placement-time fills scheduled just above via _poll_tracked_fills/_apply_sell_fill) before the EOD reconciler reads kr_stock_trades — otherwise a write still in flight looks "missing" to the diff and gets spuriously re-appended.
            await reconcile_trade_ledger(self._kiwoom, await get_storage_service(), datetime.now().strftime("%Y-%m-%d"))  # E1-5: EOD 원장 대사 백스톱(ka10076 vs kr_stock_trades diff upsert; never-raise, 포지션 미변경)

            # DS-5: discovery post-processing (backfill -> rank -> LLM
            # review -> promote -> ledger, DS-3/DS-4 batched by
            # run_discovery_pipeline), AFTER reconcile_trade_ledger and
            # BEFORE the final notify step so _notify_eod_summary can pick
            # up today's freshly-promoted candidates (mirrors the existing
            # Important-1 strategy-section freshness refresh below).
            if get_settings().DISCOVERY_ENABLED:
                try:
                    await run_discovery_pipeline(
                        coordinator=self,
                        storage=await get_storage_service(),
                        scanner=await get_background_scanner(),
                        trade_date=datetime.now().strftime("%Y-%m-%d"),
                        scan_ok=discovery_scan_ok,
                    )
                except Exception as e:
                    logger.warning(f"[Coordinator] Discovery pipeline invocation failed: {e}")

            await self._notify_eod_summary(datetime.now().strftime("%Y-%m-%d"))  # E3-3: 장마감 요약 통지(Telegram+WS) — run_eod_review가 저장한 digest/narrative 재조회
        self._market_was_open = is_open

    async def _notify_eod_summary(self, trade_date: str) -> bool:
        """E3-3: best-effort Telegram + WS notification of the day's EOD
        digest/narrative, appended after the market-close chain's other
        steps (write_daily_snapshot -> run_eod_review -> run_strategy_
        consensus -> reconcile_trade_ledger, all untouched/unreordered
        above this call in `_check_queue_on_market_open`).

        Re-reads the digest/narrative that run_eod_review's own E3-1/E3-2
        steps just computed and persisted (report_json's "digest"/
        "narrative" keys, via `storage.get_eod_reviews(limit=1)`) rather
        than recomputing either. This is deliberate: `run_eod_review`'s
        own return contract is a bare bool ("chain completed"), not the
        report dict -- changing that contract would touch its own
        docstring/every existing caller and test that already depends on
        the bool shape, which is more invasive than one extra read of a
        row this same market-close tick just wrote.

        Never-raise (one try/except for the whole step), mirroring every
        other EOD chain step above it (write_daily_snapshot/
        run_eod_review/run_strategy_consensus/reconcile_trade_ledger all
        document the same contract): a Telegram/WS delivery failure must
        never break the market-close scheduler tick, especially not after
        reconcile_trade_ledger already completed its ledger backstop work
        this same tick.

        Important 1 (final review) — strategy-section freshness: `digest`
        is assembled INSIDE `run_eod_review` (its E3-2 step), which runs
        BEFORE `run_strategy_consensus` in `_check_queue_on_market_open`'s
        chain. So the `digest["strategy"]` section `run_eod_review` computed
        and persisted always reflects the PRIOR revision, never the new one
        `run_strategy_consensus` just wrote this same tick — every automatic
        close-of-day notification and the persisted `eod_review` row itself
        was permanently one revision stale (spec §3 T8 wants the strategy
        section to reflect the SAME-DAY consensus). Since this function is
        the chain's LAST step (called after `run_strategy_consensus` AND
        `reconcile_trade_ledger`), it re-fetches the digest's strategy
        section here — via the same `eod_digest._build_strategy_section`
        helper `run_eod_review` itself calls, so the shape is identical —
        and, if it changed, patches `report["digest"]["strategy"]` and
        re-persists via `save_eod_review` (INSERT OR REPLACE on trade_date,
        so this updates the SAME row in place rather than accreting a
        duplicate). Deliberately NOT re-running `narrate_eod_digest`
        (no second LLM call this tick): the narrative's prose may reference
        the prior stance, but it is already framed as "익일 적용 전략(EOD
        합의)" rather than "오늘의 전략", so a one-revision-old narrative
        text remains factually harmless even though the structured
        `strategy` section it will be templated/broadcast alongside is now
        current — this residual gap is intentionally out of scope here.
        Best-effort: a failure in this refresh (storage read/write) is
        logged and the ORIGINAL (possibly stale) digest is still sent
        rather than dropping the notification entirely.

        Stale guard (review fix): `get_eod_reviews(limit=1)` returns the
        newest row by trade_date regardless of whether TODAY's
        run_eod_review actually wrote one this tick. If run_eod_review
        failed before reaching `save_eod_review` (its own try/except
        swallows the failure and returns False -- see its docstring), the
        newest row on disk is still YESTERDAY's, and without this check
        this step would silently re-send yesterday's digest/narrative
        relabeled as today's. Comparing the row's own `trade_date` to the
        `trade_date` this call was invoked with catches that mismatch and
        skips the send entirely rather than notifying with stale content.

        Returns (E3-4 review fix): True once delivery is actually attempted
        (past every guard above, WS broadcast reached -- Telegram too, if
        `notifier.is_ready`), False when a guard skipped the send (no row
        yet / stale row / no digest) or the whole step raised. This is
        purely additive: the market-close edge
        (`_check_queue_on_market_open`) still calls this fire-and-forget
        and ignores the return value entirely (see
        tests/test_services/test_f3_fill_tracking.py's E3-3 section, which
        pins that call site and never inspects a return value) -- the new
        bool exists so `POST /trading/eod-report/run` (E3-4) can report
        whether its manual re-notify actually went out.
        """
        try:
            storage = await get_storage_service()
            reviews = await storage.get_eod_reviews(limit=1)
            if not reviews:
                return False

            row_trade_date = reviews[0].get("trade_date")
            if row_trade_date != trade_date:
                logger.warning(
                    f"[Coordinator] eod_summary_stale_skipped — requested "
                    f"trade_date={trade_date} latest_row_trade_date={row_trade_date}"
                )
                return False

            report = json.loads(reviews[0].get("report_json") or "{}")
            digest = report.get("digest")
            if not digest:
                return False
            narrative = report.get("narrative")

            # Important 1 (final review): refresh the strategy section AFTER
            # run_strategy_consensus has had a chance to write a new
            # revision this same tick — see docstring above. Best-effort:
            # any failure here falls back to the (possibly stale) digest
            # already loaded, never blocks the notification.
            try:
                fresh_strategy = await _build_strategy_section(storage)
                if fresh_strategy is not None and fresh_strategy != digest.get("strategy"):
                    digest["strategy"] = fresh_strategy
                    report["digest"] = digest
                    await storage.save_eod_review(
                        {"trade_date": trade_date, "report_json": json.dumps(report)}
                    )
            except Exception as e:
                logger.warning(
                    f"[Coordinator] EOD digest strategy refresh failed: {e}"
                )

            # DS-5: same freshness fix as the strategy-section refresh just
            # above, for the `discovery` section — run_discovery_pipeline
            # (services/discovery/orchestrator.py, DS-3/DS-4 backfill/rank/
            # LLM-review/promote batch) runs even LATER in the market-close
            # chain than run_strategy_consensus does (after
            # reconcile_trade_ledger, right before this notify step), so the
            # digest run_eod_review originally built above almost always
            # predates today's actual discovery results entirely (nothing
            # promoted/backfilled yet at that point in the same tick).
            # Best-effort, same contract: any failure here falls back to the
            # digest already loaded, never blocks the notification.
            #
            # Critical (DS-5 review fix): explicitly gated on
            # DISCOVERY_ENABLED, matching every other discovery call site in
            # this file (the scan trigger above and the pipeline invocation
            # below). Before this fix the block ran unconditionally every
            # day — off happened to stay harmless only because the ledger
            # table is empty (build_eod_digest's null-tolerant fallback), an
            # accident of data state, not a contract: "off" must mean this
            # code path is never entered at all, not "entered but its
            # output happens to be a no-op today".
            if get_settings().DISCOVERY_ENABLED:
                try:
                    fresh_discovery = await _build_discovery_section(storage, trade_date)
                    if fresh_discovery is not None and fresh_discovery != digest.get("discovery"):
                        digest["discovery"] = fresh_discovery
                        report["digest"] = digest
                        await storage.save_eod_review(
                            {"trade_date": trade_date, "report_json": json.dumps(report)}
                        )
                except Exception as e:
                    logger.warning(
                        f"[Coordinator] EOD digest discovery refresh failed: {e}"
                    )

            from services.telegram import get_telegram_notifier

            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                await notifier.send_daily_summary(digest, narrative)

            from app.api.routes.websocket import broadcast_eod_summary

            await broadcast_eod_summary(digest, narrative)
            return True
        except Exception as e:
            logger.warning(f"[Coordinator] EOD summary notification failed: {e}")
            return False

    async def _expire_tracked_orders_on_market_close(self) -> None:
        """F3: expire every still-TRACKING order on the open→closed edge and
        notify once per order via the coordinator's normal alert path."""
        expired = self.fill_tracker.expire_stale(today=None)
        if not expired:
            return

        logger.info(f"[Coordinator] Market closed — expired {len(expired)} tracked orders")
        self._log_activity(
            ActivityType.MARKET_CLOSED,
            f"장 마감 — 미체결 추적 주문 {len(expired)}건 만료 처리",
            agent="system",
        )
        for order in expired:
            remaining = order.total_quantity - order.filled_quantity
            await self._on_alert(
                TradingAlert(
                    id=str(uuid.uuid4())[:8],
                    alert_type=AlertType.ORDER_FAILED,
                    ticker=order.ticker,
                    title="미체결 주문 만료",
                    message=(
                        f"{order.stock_name or order.ticker} 잔량 {remaining}주 — "
                        f"장 마감으로 추적 종료 (ord_no={order.ord_no})"
                    ),
                    data={"ord_no": order.ord_no, "remaining": remaining},
                )
            )
        self._schedule_persist()

    async def _poll_tracked_fills(self) -> None:
        """One scheduler tick: reconcile TRACKING orders against ka10076 fills.

        Skips the broker call entirely when nothing is TRACKING (flow-control —
        this runs every 30s alongside the queue-open check). ka10076 returns a
        cumulative daily snapshot per order, so `apply_fills` diffs it against
        each order's own accumulated fill and returns only the NEW portion —
        re-polling an unchanged snapshot is a no-op (idempotent). A query
        failure is logged and left for the next tick; tracked state does not
        change on failure.
        """
        if not self.fill_tracker.tracking():
            return
        if self._kiwoom is None:
            return

        try:
            fills = await self._kiwoom.get_filled_orders(use_cache=False)
        except Exception as e:
            logger.error(f"[Coordinator] Fill tracker poll failed: {e}")
            return

        deltas = self.fill_tracker.apply_fills(fills)
        if not deltas:
            return

        for delta in deltas:
            order = delta.order

            # P1-1: record this post-fill discovery for /trades. `quantity`
            # is the tracked order's full requested size; `executed_quantity`
            # is just the NEW portion this poll tick uncovered (delta), since
            # a single order can surface several of these rows across ticks.
            if self._persistence_active:
                order_status = getattr(order.status, "value", order.status)
                record_trade_fill(
                    stk_cd=order.ticker,
                    stk_nm=order.stock_name or order.ticker,
                    side=order.side,
                    order_type="limit",
                    price=delta.avg_fill_price,
                    quantity=order.total_quantity,
                    executed_quantity=delta.new_fill_qty,
                    status="completed" if order_status == "filled" else "partial",
                    order_id=order.ord_no,
                    session_id=order.source_session_id,
                    decision_id=order.source_session_id,
                    entry_or_exit="entry" if order.side == "buy" else "exit",
                )

            # Important 3 (최종 전체 브랜치 리뷰): 이 폴이 발견하는 체결은
            # `_record_fill_ledger`를 거치지 않는다(원장 기록은 위에서
            # `record_trade_fill`을 직접 부른다 — 중복 방지) — 그래서
            # 지연 체결(placed_pending_fill → 나중에 이 폴이 발견)이 전부
            # 무통지였다. 자율 손절/익절도 지연 체결될 수 있어 실질적이다.
            # 안전성: 이 델타는 이번 틱에 새로 발견된 "증분"만이라 —
            # placement 시점 통지(있었다면)와 절대 겹치지 않는다. `order`
            # (TrackedOrder)/`delta`(FillDelta)에는 OrderRequest.reason이
            # 없으므로 "사후 체결 확인"으로 명시해, 이게 즉시체결이 아니라
            # 나중에 발견된 체결이라는 것 자체를 경로로 남긴다.
            synthetic_order = OrderRequest(
                ticker=order.ticker,
                stock_name=order.stock_name or order.ticker,
                side=order.side,
                quantity=delta.new_fill_qty,
                price=order.limit_price,
                reason="사후 체결 확인",
                session_id=order.source_session_id,
            )
            synthetic_result = OrderResult(
                order_id=order.ord_no,
                ticker=order.ticker,
                side=synthetic_order.side,
                # requested_quantity는 주문 전체 수량 — cumulative filled이
                # 아직 total에 못 미치면 "(부분)" 표시가 정직하게 붙는다.
                requested_quantity=order.total_quantity,
                filled_quantity=delta.new_fill_qty,
                avg_price=delta.avg_fill_price,
                status="filled" if order.filled_quantity >= order.total_quantity else "partial",
            )

            # E1-2: a SELL's fill delta must NOT flow into
            # register_fill_as_position below — that call only ever GROWS a
            # position, so an unguarded sell fill here would double-count it
            # as a buy. Instead, reconcile the local position via the same
            # helper `_apply_sell_fill` uses (decrement/remove + realized
            # P&L; the ledger row was already recorded above, side-aware).
            if order.side == "sell":
                # 실현손익은 포지션이 줄어들기/사라지기 전에 계산해야
                # 진입가를 읽을 수 있다 — _apply_sell_fill과 같은 이유
                # (coordinator.py의 realized-P&L 클램프 주석 참고).
                _pos = next(
                    (p for p in self._state.positions if p.ticker == order.ticker), None
                )
                _pnl = None
                _pnl_pct = None
                if _pos is not None and _pos.avg_price and delta.avg_fill_price:
                    _matched_qty = min(int(delta.new_fill_qty), int(_pos.quantity))
                    _pnl = (float(delta.avg_fill_price) - float(_pos.avg_price)) * _matched_qty
                    _pnl_pct = (float(delta.avg_fill_price) / float(_pos.avg_price) - 1.0) * 100.0
                self._schedule_fill_notification(
                    synthetic_order, synthetic_result, side="sell",
                    realized_pnl=_pnl, realized_pnl_pct=_pnl_pct,
                )

                self._apply_sell_position_delta(
                    order.ticker,
                    delta.new_fill_qty,
                    delta.avg_fill_price,
                    order.source_session_id,
                )

                self._log_activity(
                    ActivityType.POSITION_CLOSED,
                    f"사후 매도 체결: {order.stock_name or order.ticker} "
                    f"{delta.new_fill_qty}주 @ ₩{delta.avg_fill_price:,.0f}",
                    agent="order",
                    ticker=order.ticker,
                    details={
                        "ord_no": order.ord_no,
                        "new_fill_qty": delta.new_fill_qty,
                        "avg_fill_price": delta.avg_fill_price,
                    },
                )

                await self._on_alert(
                    TradingAlert(
                        id=str(uuid.uuid4())[:8],
                        alert_type=AlertType.ORDER_FILLED,
                        ticker=order.ticker,
                        title="사후 매도 체결 감지",
                        message=(
                            f"{order.stock_name or order.ticker} "
                            f"{delta.new_fill_qty}주 @ ₩{delta.avg_fill_price:,.0f} "
                            "매도 체결 확인"
                        ),
                        data={
                            "ord_no": order.ord_no,
                            "new_fill_qty": delta.new_fill_qty,
                            "avg_fill_price": delta.avg_fill_price,
                        },
                    )
                )
            else:
                # Important 3: 지연 체결된 BUY(가장 흔한 사례 — LIMIT 주문이
                # 3폴×0.5초 창을 넘겨 pending으로 등록된 뒤 나중에 이 폴이
                # 체결을 발견)도 placement 시점엔 통지가 없었으므로(Critical 1
                # 수정으로 이제 pending은 의도적으로 무통지) 여기서 반드시
                # 알려야 그 루프가 닫힌다.
                self._schedule_fill_notification(
                    synthetic_order, synthetic_result, side="buy",
                )

                await register_fill_as_position(
                    self,
                    ticker=order.ticker,
                    stock_name=order.stock_name or order.ticker,
                    quantity=delta.new_fill_qty,
                    avg_price=delta.avg_fill_price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    session_id=order.source_session_id,
                    source="fill_tracker",
                    # Match the placement-fill path's position semantics
                    # (stop_loss_mode from risk params, risk from the proposal).
                    stop_loss_mode=self.risk_params.stop_loss_mode,
                    risk_score=order.risk_score,
                )

                self._log_activity(
                    ActivityType.POSITION_OPENED,
                    f"사후 체결: {order.stock_name or order.ticker} {delta.new_fill_qty}주 "
                    f"@ ₩{delta.avg_fill_price:,.0f}",
                    agent="order",
                    ticker=order.ticker,
                    details={
                        "ord_no": order.ord_no,
                        "new_fill_qty": delta.new_fill_qty,
                        "avg_fill_price": delta.avg_fill_price,
                        "stop_loss": order.stop_loss,
                    },
                )

                stop_note = (
                    f" — 손절 ₩{order.stop_loss:,.0f} 감시 시작" if order.stop_loss else ""
                )
                await self._on_alert(
                    TradingAlert(
                        id=str(uuid.uuid4())[:8],
                        alert_type=AlertType.ORDER_FILLED,
                        ticker=order.ticker,
                        title="사후 체결 감지",
                        message=(
                            f"{order.stock_name or order.ticker} {delta.new_fill_qty}주 "
                            f"@ ₩{delta.avg_fill_price:,.0f} 체결 확인{stop_note}"
                        ),
                        data={
                            "ord_no": order.ord_no,
                            "new_fill_qty": delta.new_fill_qty,
                            "avg_fill_price": delta.avg_fill_price,
                        },
                    )
                )

            # Post-fill queue annotation: the queue item that originated this
            # order (if any) gets a note appended — its status vocabulary is
            # unchanged (design spec §4.1/§7). Shared by both sides.
            if order.source_queue_id:
                queued = next(
                    (
                        t
                        for t in self._state.trade_queue
                        if t.id == order.source_queue_id
                    ),
                    None,
                )
                if queued is not None:
                    queued.reason = (
                        f"{queued.reason} | 사후체결 {delta.new_fill_qty}주 "
                        f"@{delta.avg_fill_price:,.0f}"
                    )

        self._schedule_persist()

    async def _queue_scheduler_loop(self) -> None:
        """Periodically check for the market-open transition until stopped."""
        try:
            while True:
                await asyncio.sleep(self._queue_scheduler_interval)
                try:
                    await self._check_queue_on_market_open()
                    await self._poll_tracked_fills()
                    self._reconcile_tick_count += 1
                    if self._reconcile_tick_count % 2 == 0:
                        await reconcile(self)
                except Exception as e:
                    logger.error(f"[Coordinator] Queue scheduler error: {e}")
        except asyncio.CancelledError:
            pass

    # -------------------------------------------
    # Watch List Management
    # -------------------------------------------

    def add_to_watch_list(
        self,
        session_id: str,
        ticker: str,
        stock_name: Optional[str],
        signal: str,
        confidence: float,
        current_price: float,
        target_entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        analysis_summary: str = "",
        key_factors: Optional[List[str]] = None,
        risk_score: int = 5,
        source: str = "manual",
    ) -> WatchedStock:
        """
        Add a stock to the watch list for monitoring.

        Args:
            session_id: Analysis session ID
            ticker: Stock ticker
            stock_name: Stock name
            signal: Analysis signal (e.g., "hold", "sell")
            confidence: Analysis confidence (0-1)
            current_price: Current stock price
            target_entry_price: Suggested entry price for buying
            stop_loss: Suggested stop-loss price
            take_profit: Suggested take-profit price
            analysis_summary: Brief summary of analysis
            key_factors: Key factors from analysis
            risk_score: Risk score (1-10)
            source: Provenance tag (DS-4) — 'manual' (default, every
                pre-existing call site) or 'discovery' (regime-weighted
                ranking auto-promotion, services/discovery/ranker.py). Drives
                the watch-total-cap eviction gate: only 'discovery' entries
                are ever auto-evicted.

        Returns:
            WatchedStock object
        """
        # Check if already in watch list
        existing = next(
            (w for w in self._state.watch_list
             if w.ticker == ticker and w.status == WatchStatus.ACTIVE),
            None
        )

        if existing:
            # Update existing entry
            existing.signal = signal
            existing.confidence = confidence
            existing.current_price = current_price
            existing.target_entry_price = target_entry_price
            existing.stop_loss = stop_loss
            existing.take_profit = take_profit
            existing.analysis_summary = analysis_summary
            existing.key_factors = key_factors or []
            existing.risk_score = risk_score
            existing.source = source
            existing.last_checked = datetime.now()

            logger.info(f"[Coordinator] Watch list updated: {ticker}")
            self._schedule_persist()
            return existing

        # Create new watch list entry
        watched = WatchedStock(
            session_id=session_id,
            ticker=ticker,
            stock_name=stock_name,
            signal=signal,
            confidence=confidence,
            current_price=current_price,
            target_entry_price=target_entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            analysis_summary=analysis_summary,
            key_factors=key_factors or [],
            risk_score=risk_score,
            source=source,
        )

        self._state.watch_list.append(watched)

        self._log_activity(
            ActivityType.WATCH_ADDED,
            f"Added to watch list: {stock_name or ticker} (signal: {signal}, confidence: {confidence:.0%})",
            agent="system",
            ticker=ticker,
            details={
                "watch_id": watched.id,
                "signal": signal,
                "confidence": confidence,
                "current_price": current_price,
                "analysis_summary": analysis_summary[:100] if analysis_summary else "",
            },
        )

        logger.info(f"[Coordinator] Added to watch list: {watched.id}")
        self._schedule_persist()
        return watched

    def get_watch_list(self) -> List[WatchedStock]:
        """Get all active items in watch list."""
        return [w for w in self._state.watch_list if w.status == WatchStatus.ACTIVE]

    def remove_from_watch_list(self, watch_id: str) -> bool:
        """Remove an item from watch list."""
        for watched in self._state.watch_list:
            if watched.id == watch_id and watched.status == WatchStatus.ACTIVE:
                watched.status = WatchStatus.REMOVED

                self._log_activity(
                    ActivityType.WATCH_REMOVED,
                    f"Removed from watch list: {watched.ticker}",
                    agent="system",
                    ticker=watched.ticker,
                    details={"watch_id": watch_id},
                )

                logger.info(f"[Coordinator] Removed from watch list: {watch_id}")
                self._schedule_persist()
                return True
        return False

    def remove_discovery_watch(self, ticker: str) -> bool:
        """Remove the ACTIVE discovery-sourced (`source == 'discovery'`) watch
        entry for `ticker`, if any (DS-4 watch-total-cap eviction gate).

        Manual entries (`source != 'discovery'`, the default for every
        pre-DS-4 call site) are never touched even if `ticker` matches —
        `services/discovery/ranker.py::promote_candidates` relies on this to
        protect user-added names when evicting the lowest-scoring discovery
        candidate to stay under the 30-item watch-total cap. Reuses
        `remove_from_watch_list`'s status-flip + activity-log + persist path
        rather than duplicating it.

        Returns:
            True if a matching discovery-sourced ACTIVE entry was found and
            removed, False otherwise (no match, or the only match is manual).
        """
        watched = next(
            (
                w for w in self._state.watch_list
                if w.ticker == ticker
                and w.status == WatchStatus.ACTIVE
                and getattr(w, "source", "manual") == "discovery"
            ),
            None,
        )
        if watched is None:
            return False
        return self.remove_from_watch_list(watched.id)

    def convert_watch_to_queue(
        self,
        watch_id: str,
        action: str = "BUY",
        reason: str = "User converted from watch list",
    ) -> Optional[QueuedTrade]:
        """
        Convert a watched stock to the trade queue for execution.

        Args:
            watch_id: Watch list item ID
            action: Trade action (BUY or SELL)
            reason: Reason for conversion

        Returns:
            QueuedTrade if successful, None otherwise
        """
        watched = next(
            (w for w in self._state.watch_list
             if w.id == watch_id and w.status == WatchStatus.ACTIVE),
            None
        )

        if not watched:
            return None

        # Add to trade queue
        queued_trade = self.add_to_queue(
            session_id=watched.session_id,
            ticker=watched.ticker,
            stock_name=watched.stock_name,
            action=action,
            entry_price=watched.target_entry_price or watched.current_price,
            stop_loss=watched.stop_loss,
            take_profit=watched.take_profit,
            risk_score=watched.risk_score,
            reason=reason,
        )

        # Update watch status
        watched.status = WatchStatus.CONVERTED
        watched.triggered_at = datetime.now()

        self._log_activity(
            ActivityType.WATCH_CONVERTED,
            f"Watch list converted to trade: {watched.ticker} -> {action}",
            agent="system",
            ticker=watched.ticker,
            details={
                "watch_id": watch_id,
                "queue_id": queued_trade.id,
                "action": action,
            },
        )

        logger.info(f"[Coordinator] Watch list converted: {watch_id} -> {queued_trade.id}")
        return queued_trade

    def get_watched_stock(self, ticker: str) -> Optional[WatchedStock]:
        """Get a watched stock by ticker if it's active."""
        return next(
            (w for w in self._state.watch_list
             if w.ticker == ticker and w.status == WatchStatus.ACTIVE),
            None
        )

    def mark_watch_converted(self, ticker: str) -> bool:
        """Mark the active watch-list entry for `ticker` as CONVERTED.

        Used by the autonomous agent-chat path (`ChatCoordinator._execute_trade`)
        WITHOUT going through `convert_watch_to_queue` — that path calls
        `on_trade_approved` directly, so without this call the watch entry
        stayed ACTIVE forever. The periodic watch-list check
        (`ChatCoordinator._check_watch_list`) could then re-detect the same
        "opportunity" and start a duplicate discussion/execution on the same
        ticker (P2 funnel-consolidation audit finding, 2026-07-14).

        Callers MUST gate this on `on_trade_approved`'s actual outcome, not
        merely on having attempted a decision: `on_trade_approved` has non-
        exception outcomes where no trade actually results (daily trade
        limit reached, portfolio sizing to <=0 shares, or an order placed
        but the broker filled 0 shares) — call this only when a trade
        genuinely executed or was queued (a real position/queue entry
        resulted), otherwise the watch entry must stay ACTIVE so the
        opportunity can be re-evaluated later (T2 review gap, 2026-07-14;
        see `services.agent_chat.coordinator._trade_actually_resulted`).

        Returns False (no-op) when there is no active watch entry for the
        ticker — a decision can legitimately originate outside the watch list.
        """
        watched = self.get_watched_stock(ticker)
        if watched is None:
            return False

        watched.status = WatchStatus.CONVERTED
        watched.triggered_at = datetime.now()

        self._log_activity(
            ActivityType.WATCH_CONVERTED,
            f"Watch list auto-converted by autonomous execution: {watched.ticker}",
            agent="system",
            ticker=ticker,
            details={"watch_id": watched.id},
        )

        logger.info(f"[Coordinator] Watch list auto-converted: {watched.id}")
        self._schedule_persist()
        return True

    # -------------------------------------------
    # Strategy Management
    # -------------------------------------------

    def get_strategy(self) -> Optional[TradingStrategy]:
        """Get the current trading strategy."""
        return self._strategy

    def set_strategy(self, strategy: Optional[TradingStrategy]):
        """
        Set the trading strategy.

        Args:
            strategy: TradingStrategy to apply, or None to clear
        """
        self._strategy = strategy

        # Phase4: 전략 노브 -> 공유 RiskParameters in-place 매핑 (해제=기본값 복귀).
        # allowlist/클램프/denylist는 strategy_apply.py — 게이트 필드는 불변.
        risk_param_changes = apply_strategy_to_risk_params(strategy, self.risk_params)

        if strategy:
            self._log_activity(
                ActivityType.STRATEGY_CHANGED,
                f"Strategy set: {strategy.name} ({strategy.risk_tolerance.value})",
                agent="system",
                details={
                    "strategy_name": strategy.name,
                    "preset": strategy.preset.value,
                    "risk_tolerance": strategy.risk_tolerance.value,
                    "trading_style": strategy.trading_style.value,
                    "risk_param_changes": {k: [v[0], v[1]] for k, v in risk_param_changes.items()},
                },
            )

            logger.info(f"[Coordinator] Strategy set: {strategy.name}")
        else:
            self._log_activity(
                ActivityType.STRATEGY_CHANGED,
                "Strategy cleared",
                agent="system",
                details={
                    "risk_param_changes": {k: [v[0], v[1]] for k, v in risk_param_changes.items()},
                },
            )

            logger.info("[Coordinator] Strategy cleared")
