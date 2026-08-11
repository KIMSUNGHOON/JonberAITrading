"""
FastAPI Application Entry Point

Main application setup with:
- CORS middleware
- Lifespan events (startup/shutdown)
- API router inclusion
- Health check endpoint
- Enhanced logging for development
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.llm_provider import get_llm_provider, reset_llm_provider
from app.api.routes import approval, websocket, kr_stocks, chat, settings as settings_routes, trading, scanner, agent_chat, translate
from app.config import settings
from app.core.analysis_limiter import cleanup_old_sessions
from app.logging_config import configure_logging, RequestLoggingMiddleware
from services.storage_service import close_storage_service, get_storage_service
from services.telegram import get_telegram_notifier, TelegramNotifier
from services.telegram.receiver import start_telegram_receiver, stop_telegram_receiver
from services.krx_holiday import get_holiday_service
from services.session_manager import get_session_manager

# Configure enhanced logging
configure_logging(
    log_level="DEBUG" if settings.DEBUG else "INFO",
    json_logs=not settings.DEBUG,
)

logger = structlog.get_logger()

# Strong references for fire-and-forget lifespan tasks (e.g. the US AI signal
# boot refresh) so they aren't garbage-collected mid-flight; entries are
# discarded via add_done_callback once the task completes.
_background_tasks: set[asyncio.Task] = set()

# 부팅 자동 방어 복원의 상한. start()가 _refresh_account_info()로 키움을
# 부르므로, API가 죽어 있으면 부팅이 영영 멈출 수 있다. 코디네이터마다
# 독립된 예산이다 — 하나가 이 시간을 다 써도 다른 하나는 자기 몫의
# BOOT_AUTO_RESUME_TIMEOUT_S를 그대로 받는다(공유 예산이 아니다).
BOOT_AUTO_RESUME_TIMEOUT_S = 60

# 코디네이터별 실패 시 안내할 수동 복구 명령 — 어느 감시가 꺼졌는지뿐
# 아니라 무엇을 눌러야 하는지까지 알림에 정확히 남기기 위해서다.
_BOOT_RESUME_REMEDIATION = {
    "trading": "POST /api/trading/start",
    "agent_chat": "POST /api/agent-chat/start",
}


async def _resume_one(label: str, get_coordinator) -> tuple[str, bool, Exception | None]:
    """코디네이터 하나만 되살린다. (label, resumed, error)를 돌려준다 — raise하지 않는다.

    예외를 여기서 잡는 이유: 한쪽 장애가 다른 쪽 복원을 막으면 안 된다 —
    키움 장애가 키움과 무관한 에이전트챗 감시까지 꺼버릴 이유가 없다.
    타임아웃도 코디네이터마다 따로 건다(전체를 하나로 묶으면 앞선
    코디네이터가 예산을 다 써버려 뒤 코디네이터가 사실상 시도조차 못
    한다).

    get_coordinator() 자체도 wait_for 안에서 부른다(MINOR 5) —
    get_shared_kiwoom_client_async()가 잡는 모듈 전역 asyncio.Lock이 걸려
    있으면 코디네이터 획득 자체가 예산 밖에서 무한정 멈출 수 있었다.
    """

    async def _do() -> bool:
        coordinator = await get_coordinator()
        return await coordinator.resume_if_persisted()

    try:
        resumed = await asyncio.wait_for(_do(), timeout=BOOT_AUTO_RESUME_TIMEOUT_S)
        return label, resumed, None
    except Exception as e:
        return label, False, e


async def _boot_auto_resume() -> None:
    """재시작 후 사람이 /trading/start를 칠 때까지 손절·익절이 무방비인
    창을 없앤다.

    복원 기계는 이미 각 코디네이터의 start() 안에 다 있었고(_restore_state,
    restore_stop_overlay), 부팅 시 그것을 부를 사람이 없던 것이 유일한
    갭이었다. 여기서는 "되살릴지 말지"만 정한다 — 판단 자체는 각
    코디네이터의 resume_if_persisted()가 저장된 상태를 보고 내린다.

    fire-and-forget이 아니라 await로 부른다(US 신호 갱신과 의도적으로
    다르다). 부팅 몇 초 지연이 무방비 몇 분보다 낫다.

    트레이딩을 먼저 시도한다 — 실 포지션 방어가 우선순위다. 하지만
    트레이딩이 터지거나 타임아웃 나도 에이전트챗은 결과와 무관하게 반드시
    시도한다(_resume_one이 예외를 삼키므로 여기서 순서대로 불러도 한쪽
    장애가 다른 쪽을 막지 않는다) — 키움과 무관한 감시까지 같이 꺼질
    이유가 없다.

    절대 raise하지 않는다 — 방어 복원 실패가 서버 부팅을 막아선 안 된다.
    다만 무성 실패도 금지라, 실패는 코디네이터별로 로그와 Telegram 양쪽에
    남긴다.
    """
    if not settings.BOOT_AUTO_RESUME_ENABLED:
        logger.info("boot_auto_resume_disabled")
        return

    try:
        from app.dependencies import get_trading_coordinator
        from services.agent_chat.coordinator import get_chat_coordinator

        results = [
            await _resume_one("trading", get_trading_coordinator),
            await _resume_one("agent_chat", get_chat_coordinator),
        ]

        logger.info(
            "boot_auto_resume_complete",
            trading=results[0][1],
            agent_chat=results[1][1],
        )

        failures = [(label, error) for label, _resumed, error in results if error is not None]
        if not failures:
            return

        for label, error in failures:
            # asyncio.TimeoutError 등은 str(e)가 대개 빈 문자열이라 타입명을
            # 같이 남긴다 — 안 그러면 로그가 error=""로만 남아 원인을 잃는다.
            logger.error(
                "boot_auto_resume_failed",
                coordinator=label,
                error_type=type(error).__name__,
                error=str(error),
            )

        # 무성 실패 금지 — 방어를 못 켰다는 사실은 폰까지 가야 한다. 실패한
        # 코디네이터별로 원인과 복구 명령을 남긴다 — 뭉뚱그리면(예: 트레이딩만
        # 재개 성공, 에이전트챗 실패) 운영자가 트레이딩 명령만 실행하고 다
        # 됐다고 믿을 수 있다. 알림 실패가 부팅을 막지 않도록 이 호출도
        # 따로 감싼다.
        #
        # CRITICAL 1 (2026-07-29): label/타입명/str(error)는 전부 자유텍스트다.
        # send_system_status가 legacy Markdown으로 보내므로 이스케이프 없이
        # 넣으면 "_"(예: agent_chat) 하나로도 Telegram이 400을 뱉고
        # _send_message가 그 실패를 조용히 삼킨다 — 방어가 안 켜졌다는 알림
        # 자체가 유실된다(service.py:728의 daily_cap 사고와 동일 패턴).
        # TelegramNotifier._md_escape로 자유텍스트 부분만 이스케이프한다
        # (복구 명령 문자열은 고정 상수라 이스케이프 대상이 아니다).
        try:
            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                detail = " / ".join(
                    f"{TelegramNotifier._md_escape(label)} 실패("
                    f"{TelegramNotifier._md_escape(type(error).__name__)}: "
                    f"{TelegramNotifier._md_escape(str(error))}) — 수동으로 "
                    f"{_BOOT_RESUME_REMEDIATION.get(label, label)} 를 실행하세요."
                    for label, error in failures
                )
                sent = await notifier.send_system_status(
                    "error",
                    f"부팅 자동 방어 복원 실패 — 감시 일부가 꺼져 있습니다. {detail}",
                )
                # MINOR 6: send_system_status는 설정으로 꺼져 있거나 발송이
                # 실패하면 조용히 False를 돌려준다 — 미발송 알림이 발송된
                # 것처럼 보이면 안 된다.
                if not sent:
                    logger.error("boot_auto_resume_alert_not_sent")
        except Exception as e:
            # MINOR 7: 원인 없이는 로그가 "그냥 실패"로만 남는다.
            logger.error(
                "boot_auto_resume_alert_failed",
                error_type=type(e).__name__,
                error=str(e),
            )
    except Exception as e:
        # 최후 방어선. _resume_one이 코디네이터별 예외를 이미 삼키므로 여기까지
        # 오는 건 get_trading_coordinator/get_chat_coordinator의 import 실패 같은
        # 상상 밖의 상황뿐이지만, 그래도 raise는 절대 안 된다.
        logger.error(
            "boot_auto_resume_unexpected_failure",
            error_type=type(e).__name__,
            error=str(e),
        )
        try:
            notifier = await get_telegram_notifier()
            if notifier.is_ready:
                sent = await notifier.send_system_status(
                    "error",
                    f"부팅 자동 방어 복원 중 예상 밖 오류 — 수동으로 상태를 "
                    f"확인하세요. ({TelegramNotifier._md_escape(type(e).__name__)}: "
                    f"{TelegramNotifier._md_escape(str(e))})",
                )
                if not sent:
                    logger.error("boot_auto_resume_alert_not_sent")
        except Exception as alert_error:
            logger.error(
                "boot_auto_resume_alert_failed",
                error_type=type(alert_error).__name__,
                error=str(alert_error),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.

    Startup:
    - Initialize LLM provider
    - Health check LLM server
    - Initialize SQLite storage

    Shutdown:
    - Clean up resources
    """
    # Startup
    logger.info(
        "application_startup",
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG,
    )

    # Initialize and health check LLM
    llm = get_llm_provider()
    health = await llm.health_check()

    if health["status"] == "healthy":
        logger.info(
            "llm_server_connected",
            provider=health["provider"],
            model=health.get("configured_model"),
        )
    else:
        logger.warning(
            "llm_server_unavailable",
            status=health["status"],
            error=health.get("error"),
        )

    # Initialize and health check SQLite storage
    try:
        storage_service = await get_storage_service()
        storage_health = await storage_service.health_check()

        if storage_health["status"] == "healthy":
            logger.info(
                "storage_connected",
                type=storage_health.get("type"),
                db_path=storage_health.get("db_path"),
            )
        else:
            logger.warning(
                "storage_unavailable",
                status=storage_health["status"],
                error=storage_health.get("error"),
            )
    except Exception as e:
        logger.warning("storage_connection_failed", error=str(e))

    # DQ-3: re-seed discovery regime-weight thresholds once at startup. A
    # stored discovery:regime_weights config that still matches the
    # pre-DQ-3 hardcoded default (bearish threshold 0.65, un-recalibrated)
    # gets moved onto the new measured default (bearish threshold ->
    # 0.52); any hand-adjusted or EOD-strategy-consensus-updated config is
    # left untouched (deep-compared against the old snapshot). never-raise
    # -- a migration failure never blocks startup.
    try:
        from services.discovery.ranker import migrate_regime_weights_reseed

        storage_service = await get_storage_service()
        reseeded = await migrate_regime_weights_reseed(storage_service)
        logger.info("discovery_regime_weights_migration_complete", reseeded=reseeded)
    except Exception as e:
        logger.warning("discovery_regime_weights_migration_failed", error=str(e))

    # FI-1: reconcile orphaned scan_sessions rows left at status='running' by
    # a previous process that died mid-scan (crash/kill) without ever
    # reaching stop_scan()'s own partial-completion cleanup. MUST run here,
    # before anything in this process could itself start a scan, so every
    # 'running' row found is guaranteed to be a previous-process leftover
    # (see BackgroundScanner.reconcile_orphan_scan_sessions docstring).
    # Never-raise -- a reconcile failure must not block startup.
    try:
        from services.background_scanner import get_background_scanner

        bg_scanner = await get_background_scanner()
        reconciled = await bg_scanner.reconcile_orphan_scan_sessions()
        logger.info("scan_orphan_reconcile_complete", reconciled=reconciled)
    except Exception as e:
        logger.warning("scan_orphan_reconcile_failed", error=str(e))

    # Initialize unified SessionManager
    try:
        session_manager = await get_session_manager()
        stats = await session_manager.get_stats()
        logger.info(
            "session_manager_initialized",
            loaded_sessions=stats.get("total_sessions", 0),
        )
    except Exception as e:
        logger.error("session_manager_init_failed", error=str(e))

    # Re-arm the autonomy auto-approve injector for sessions ALREADY
    # awaiting_approval (R3 gap fix): producers only schedule the injector at
    # the moment a session first sets awaiting_approval, so a session that
    # reached it while the master gate was off (or before a restart) never
    # got a countdown — and AUTONOMY_ENABLED only takes effect via a restart.
    # Runs after SessionManager init (above) so session state is available;
    # per-session errors are handled inside and never propagate here, but the
    # pass is wrapped too so it can never block startup.
    try:
        from app.api.routes._autonomy_injector import rearm_awaiting_approvals

        await rearm_awaiting_approvals()
        logger.info("autonomy_rearm_complete")
    except Exception as e:
        logger.error("autonomy_rearm_failed", error=str(e))

    # Start session cleanup background task
    asyncio.create_task(cleanup_old_sessions())
    logger.info("session_cleanup_task_started")

    # 재시작 안전(2026-07-29): 마지막으로 저장된 mode가 active/paused면
    # 트레이딩·에이전트챗 코디네이터를 자동으로 되살린다. autonomy rearm
    # 뒤에 둔다 — 승인 대기 세션이 카운트다운을 먼저 받아야 하고
    # SessionManager도 초기화돼 있어야 한다. never-raise.
    await _boot_auto_resume()

    # Initialize Telegram notifications (if configured)
    try:
        telegram_notifier = await get_telegram_notifier()
        if telegram_notifier.is_ready:
            await telegram_notifier.send_system_status("started", "Trading system started successfully")
            logger.info("telegram_notifier_ready")
        else:
            logger.info("telegram_notifier_disabled", message="Telegram not configured")
    except Exception as e:
        logger.warning("telegram_init_failed", error=str(e))

    # Start the Telegram receiver (TG-1) -- inbound PTB Application, separate
    # instance from the notifier above (services/telegram/receiver.py).
    # Best-effort: never raises, returns None when unconfigured/failed --
    # receiver state doesn't affect notifier readiness or server startup.
    try:
        await start_telegram_receiver()
    except Exception as e:
        logger.warning("telegram_receiver_init_failed", error=str(e))

    # Initialize KRX Holiday Service
    try:
        holiday_service = await get_holiday_service()
        status = holiday_service.get_status()
        logger.info(
            "holiday_service_initialized",
            total_holidays=status.get("total_holidays", 0),
            years=list(status.get("year_stats", {}).keys()),
            # 출처와 신뢰 못 하는 연도를 부팅 로그에 드러낸다 -- 이게 없으면
            # KRX 연동이 죽어 폴백 표를 쓰고 있다는 사실이 보이지 않는다.
            source=status.get("source"),
            year_sources=status.get("year_sources"),
            untrusted_years=status.get("untrusted_years"),
        )
        if status.get("untrusted_years"):
            logger.error(
                "holiday_calendar_untrusted_years",
                years=status.get("untrusted_years"),
                fallback_covers=status.get("fallback_covers_years"),
                hint="해당 연도는 완전한 달력이 저장돼 있지 않아 모르는 휴장일이 "
                     "거래일로 보인다. update_holidays(year) 필요.",
            )

        # Start automatic update scheduler (monthly on 1st at 6:00 AM)
        holiday_service.start_scheduler(update_day=1, update_hour=6)
        logger.info("holiday_update_scheduler_started")

        # 장전 브리핑 08:30 자동 발송 (2026-08-06). 실패해도 앱을 죽이지
        # 않는다 -- 브리핑은 관측용이고 매매와 무관하다.
        from services.telegram.briefing import start_morning_brief_scheduler

        start_morning_brief_scheduler()
        logger.info("morning_brief_scheduler_wired")
    except Exception as e:
        logger.warning("holiday_service_init_failed", error=str(e))

    # US AI 크로스마켓 신호 pre-open 스케줄러(US_SIGNAL_ENABLED off면 no-op) + 부팅 1회 갱신
    try:
        from services.trading.us_market_data import refresh_us_ai_signal_cache, start_us_signal_scheduler

        us_signal_scheduler = start_us_signal_scheduler()
        if us_signal_scheduler is not None:
            # 논블로킹: Finnhub 장애 시 3종목 x 10s 타임아웃이 최대 ~30s
            # 앱 부팅을 지연시킬 수 있어 fire-and-forget으로 실행(refresh는
            # never-raise라 태스크가 루프를 죽일 수 없음). 강참조 보관으로
            # GC 수거 방지(다음 08:00 cron 전까지는 캐시가 비어도 무해).
            task = asyncio.create_task(refresh_us_ai_signal_cache())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            logger.info("us_ai_signal_scheduler_started_and_refresh_scheduled")
    except Exception as e:
        logger.warning("us_ai_signal_scheduler_init_failed", error=str(e))

    # 레짐 인지 노출도 08:05 일일 사이클(REGIME_EXPOSURE_ENABLED off면 no-op).
    try:
        from services.trading.regime_judge import start_regime_scheduler

        start_regime_scheduler()
        logger.info("regime_scheduler_wired")
    except Exception as e:
        logger.warning("regime_scheduler_init_failed", error=str(e))

    # Initialize the LLM router (best-effort CLI/HTTP health probes for /api/llm/stats)
    try:
        from agents.llm.router import get_router

        await get_router().startup()
        logger.info("llm_router_ready")
    except Exception as e:
        logger.warning("llm_router_startup_failed", error=str(e))

    yield

    # Shutdown
    logger.info("application_shutdown")

    # Stop the Telegram receiver first (reverse of its late startup position,
    # and it may still be dispatching handlers that call into services torn
    # down below -- best-effort, no-op if never started).
    try:
        await stop_telegram_receiver()
    except Exception:
        pass

    await llm.close()
    reset_llm_provider()
    await close_storage_service()

    # Close the LLM router
    try:
        from agents.llm.router import get_router

        await get_router().aclose()
    except Exception:
        pass

    # Close holiday service
    try:
        holiday_svc = await get_holiday_service()
        await holiday_svc.close()
    except Exception:
        pass


# Create FastAPI application
app = FastAPI(
    title="Agentic Trading API",
    description="AI-powered trading analysis with human-in-the-loop approval",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware (development only)
if settings.DEBUG:
    app.add_middleware(RequestLoggingMiddleware, log_request_body=True)

# =============================================================================
# API Routes — every router mounts under both the versioned (/api/v1/*) and
# legacy (/api/*) prefixes. The frontend depends on the legacy /api/* prefix
# (see frontend/src/api/client.ts); keep both until the frontend migrates.
# =============================================================================


# (router, sub-path, tag-name). An empty sub-path means the router carries its
# own internal prefix (e.g. indicators -> /indicators, agent_chat -> /agent-chat).
_API_ROUTERS: list[tuple[APIRouter, str, str]] = [
    (translate.router, "analysis", "Translate"),
    (approval.router, "approval", "Approval"),
    (kr_stocks.router, "kr_stocks", "Korean Stocks"),
    (chat.router, "chat", "Chat"),
    (settings_routes.router, "settings", "Settings"),
    (trading.router, "", "Trading"),
    (scanner.router, "", "Scanner"),
    (agent_chat.router, "", "Agent Chat"),
]


def register_api_routes(app: FastAPI) -> None:
    """Mount every router under both the /api/v1 and legacy /api prefixes.

    The frontend depends on the legacy /api/* prefix (see frontend/src/api/client.ts);
    keep both until the frontend migrates.
    """
    for base, label in (("/api/v1", "v1"), ("/api", "Legacy")):
        for router, subpath, name in _API_ROUTERS:
            prefix = f"{base}/{subpath}" if subpath else base
            app.include_router(router, prefix=prefix, tags=[f"{label} - {name}"])


register_api_routes(app)


@app.get("/api/llm/stats", tags=["LLM Router"])
@app.get("/api/v1/llm/stats", tags=["LLM Router"])
async def llm_router_stats() -> dict:
    """Per-backend health, circuit state, and OpenRouter budget for the router."""
    from agents.llm.router import get_router

    return get_router().snapshot()

# WebSocket (version-independent)
app.include_router(
    websocket.router,
    prefix="/ws",
    tags=["WebSocket"],
)


# -------------------------------------------
# Root Endpoints
# -------------------------------------------


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Agentic Trading API",
        "version": "1.0.0",
        "api_versions": {
            "current": "v1",
            "supported": ["v1"],
            "deprecated": ["legacy (no version prefix)"],
        },
        "endpoints": {
            "v1": "/api/v1",
            "legacy": "/api (deprecated)",
            "docs": "/docs" if settings.DEBUG else "disabled",
            "health": "/health",
        },
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        Health status of API and connected services.
    """
    llm = get_llm_provider()
    llm_health = await llm.health_check()

    # Storage health check
    try:
        storage_service = await get_storage_service()
        storage_health = await storage_service.health_check()
    except Exception as e:
        storage_health = {"status": "unhealthy", "error": str(e)}

    # Determine overall status
    all_healthy = (
        llm_health["status"] == "healthy" and
        storage_health["status"] == "healthy"
    )
    overall_status = "healthy" if all_healthy else "degraded"

    return {
        "status": overall_status,
        "environment": settings.ENVIRONMENT,
        "services": {
            "api": "healthy",
            "llm": llm_health,
            "storage": storage_health,
        },
    }


# -------------------------------------------
# Development/Debug Endpoints
# -------------------------------------------

if settings.DEBUG:

    @app.get("/debug/config")
    async def debug_config():
        """Show current configuration (debug only)."""
        return {
            "environment": settings.ENVIRONMENT,
            "llm_provider": settings.LLM_PROVIDER,
            "llm_base_url": settings.LLM_BASE_URL,
            "llm_model": settings.LLM_MODEL,
            "market_data_mode": settings.MARKET_DATA_MODE,
        }
