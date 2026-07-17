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
from app.api.routes import approval, websocket, coin, kr_stocks, chat, settings as settings_routes, trading, scanner, agent_chat, translate
from app.config import settings
from app.core.analysis_limiter import cleanup_old_sessions
from app.logging_config import configure_logging, RequestLoggingMiddleware
from services.realtime_service import close_realtime_service, get_realtime_service
from services.storage_service import close_storage_service, get_storage_service
from services.telegram import get_telegram_notifier
from services.telegram.receiver import start_telegram_receiver, stop_telegram_receiver
from services.krx_holiday import get_holiday_service
from services.session_manager import get_session_manager

# Configure enhanced logging
configure_logging(
    log_level="DEBUG" if settings.DEBUG else "INFO",
    json_logs=not settings.DEBUG,
)

logger = structlog.get_logger()


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

    # Initialize realtime service (Upbit WebSocket)
    try:
        realtime_service = await get_realtime_service()
        await realtime_service.start()
        logger.info("realtime_service_started")
    except Exception as e:
        logger.warning("realtime_service_start_failed", error=str(e))

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
        )

        # Start automatic update scheduler (monthly on 1st at 6:00 AM)
        holiday_service.start_scheduler(update_day=1, update_hour=6)
        logger.info("holiday_update_scheduler_started")
    except Exception as e:
        logger.warning("holiday_service_init_failed", error=str(e))

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

    await close_realtime_service()
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
    (coin.router, "coin", "Coin"),
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
