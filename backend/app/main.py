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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.llm_provider import get_llm_provider, reset_llm_provider
from app.api.routes import analysis, approval, websocket, auth, coin, kr_stocks, chat, indicators, settings as settings_routes, news, trading, scanner
from app.config import settings
from app.core.analysis_limiter import cleanup_old_sessions
from app.logging_config import configure_logging, RequestLoggingMiddleware
from services.realtime_service import close_realtime_service, get_realtime_service
from services.storage_service import close_storage_service, get_storage_service
from services.telegram import get_telegram_notifier

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

    yield

    # Shutdown
    logger.info("application_shutdown")
    await close_realtime_service()
    await llm.close()
    reset_llm_provider()
    await close_storage_service()


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

# Include API routers
app.include_router(
    analysis.router,
    prefix="/api/analysis",
    tags=["Analysis"],
)
app.include_router(
    approval.router,
    prefix="/api/approval",
    tags=["Approval"],
)
app.include_router(
    websocket.router,
    prefix="/ws",
    tags=["WebSocket"],
)
app.include_router(
    auth.router,
    prefix="/api/auth",
    tags=["Authentication"],
)
app.include_router(
    coin.router,
    prefix="/api/coin",
    tags=["Coin"],
)
app.include_router(
    kr_stocks.router,
    prefix="/api/kr_stocks",
    tags=["Korean Stocks (Kiwoom)"],
)
app.include_router(
    chat.router,
    prefix="/api/chat",
    tags=["Chat"],
)
app.include_router(
    indicators.router,
    prefix="/api",
    tags=["Technical Indicators"],
)
app.include_router(
    settings_routes.router,
    prefix="/api/settings",
    tags=["Settings"],
)
app.include_router(
    news.router,
    prefix="/api",
    tags=["News"],
)
app.include_router(
    trading.router,
    prefix="/api",
    tags=["Trading"],
)
app.include_router(
    scanner.router,
    prefix="/api",
    tags=["Background Scanner"],
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
        "docs": "/docs" if settings.DEBUG else "disabled",
        "health": "/health",
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
