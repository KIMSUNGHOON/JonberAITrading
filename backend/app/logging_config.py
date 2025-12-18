"""
Enhanced Logging Configuration for Development

Provides:
- Structured logging with log levels (DEBUG, INFO, WARNING, ERROR)
- Request lifecycle logging
- Agent workflow tracing
- Color-coded console output
- Request/Response body logging
"""

import logging
import sys
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Optional
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variables for request tracking
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
agent_ctx: ContextVar[str] = ContextVar("agent", default="")


# -------------------------------------------
# Log Level Configuration
# -------------------------------------------

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(
    log_level: str = "DEBUG",
    json_logs: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
        json_logs: If True, output JSON logs (for production)
        log_file: Optional file path for log output
    """
    # Set up stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=LOG_LEVELS.get(log_level.upper(), logging.DEBUG),
    )

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(LOG_LEVELS.get(log_level.upper(), logging.DEBUG))
        logging.getLogger().addHandler(file_handler)

    # Configure structlog processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f"),
        structlog.processors.StackInfoRenderer(),
        add_request_context,
        add_agent_context,
    ]

    if json_logs:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Colored console output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def add_request_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """Add request ID to log context."""
    request_id = request_id_ctx.get()
    if request_id:
        event_dict["request_id"] = request_id[:8]  # Short ID for readability
    return event_dict


def add_agent_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict,
) -> dict:
    """Add agent name to log context."""
    agent = agent_ctx.get()
    if agent:
        event_dict["agent"] = agent
    return event_dict


# -------------------------------------------
# Request Logging Middleware
# -------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP request/response lifecycle.

    Logs:
    - Request start with method, path, headers
    - Request body (for POST/PUT/PATCH)
    - Response status and timing
    - Response body (for errors)
    """

    def __init__(self, app, log_request_body: bool = True, log_response_body: bool = False):
        super().__init__(app)
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.logger = structlog.get_logger("http")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid4())
        request_id_ctx.set(request_id)

        # Add request ID to response headers
        start_time = time.perf_counter()

        # Log request start
        self.logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params) if request.query_params else None,
            client_ip=request.client.host if request.client else None,
        )

        # Log request body for mutations
        if self.log_request_body and request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.body()
                if body:
                    # Store body for later use
                    request.state.body = body
                    body_preview = body[:500].decode("utf-8", errors="replace")
                    self.logger.debug(
                        "request_body",
                        body_preview=body_preview,
                        body_size=len(body),
                    )
            except Exception as e:
                self.logger.warning("request_body_read_error", error=str(e))

        # Process request
        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log response
            log_method = self.logger.info if response.status_code < 400 else self.logger.warning
            log_method(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration_ms, 2),
            )
            raise


# -------------------------------------------
# Agent Workflow Logging
# -------------------------------------------

class AgentLogger:
    """
    Logger for agent workflow tracing.

    Provides detailed logging of:
    - Agent activation and completion
    - Input/output data
    - State transitions
    - LLM interactions
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.logger = structlog.get_logger(f"agent.{agent_name}")

    def start(self, ticker: str, **context) -> None:
        """Log agent starting."""
        agent_ctx.set(self.agent_name)
        self.logger.info(
            "agent_started",
            ticker=ticker,
            **context,
        )

    def input(self, data: dict, label: str = "input") -> None:
        """Log agent input data."""
        self.logger.debug(
            f"agent_{label}",
            data_keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            data_preview=_truncate_dict(data),
        )

    def output(self, data: dict, label: str = "output") -> None:
        """Log agent output data."""
        self.logger.debug(
            f"agent_{label}",
            data_keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            data_preview=_truncate_dict(data),
        )

    def llm_request(self, messages: list, temperature: float = 0.7) -> None:
        """Log LLM request."""
        self.logger.debug(
            "llm_request",
            message_count=len(messages),
            temperature=temperature,
            system_prompt_preview=_truncate_str(messages[0].content if messages else "", 200),
        )

    def llm_response(self, response: str, duration_ms: float) -> None:
        """Log LLM response."""
        self.logger.debug(
            "llm_response",
            response_length=len(response),
            duration_ms=round(duration_ms, 2),
            response_preview=_truncate_str(response, 300),
        )

    def state_transition(self, from_stage: str, to_stage: str) -> None:
        """Log workflow state transition."""
        self.logger.info(
            "state_transition",
            from_stage=from_stage,
            to_stage=to_stage,
        )

    def result(self, signal: str, confidence: float, summary: str) -> None:
        """Log agent analysis result."""
        self.logger.info(
            "agent_result",
            signal=signal,
            confidence=round(confidence, 2),
            summary_preview=_truncate_str(summary, 200),
        )

    def complete(self, duration_ms: float, **context) -> None:
        """Log agent completion."""
        self.logger.info(
            "agent_completed",
            duration_ms=round(duration_ms, 2),
            **context,
        )
        agent_ctx.set("")

    def error(self, error: str, **context) -> None:
        """Log agent error."""
        self.logger.error(
            "agent_error",
            error=error,
            **context,
        )


# -------------------------------------------
# Workflow Tracer
# -------------------------------------------

class WorkflowTracer:
    """
    Tracer for the entire trading workflow.

    Provides a high-level view of:
    - Session lifecycle
    - Stage progression
    - Agent coordination
    - Timing breakdowns
    """

    def __init__(self, session_id: str, ticker: str):
        self.session_id = session_id
        self.ticker = ticker
        self.logger = structlog.get_logger("workflow")
        self.start_time = time.perf_counter()
        self.stage_times: dict[str, float] = {}
        self.current_stage: Optional[str] = None

    def start(self) -> None:
        """Log workflow start."""
        self.logger.info(
            "workflow_started",
            session_id=self.session_id[:8],
            ticker=self.ticker,
        )

    def enter_stage(self, stage: str) -> None:
        """Log entering a workflow stage."""
        if self.current_stage:
            # Record time spent in previous stage
            self.stage_times[self.current_stage] = time.perf_counter() - self.stage_times.get(
                f"_start_{self.current_stage}", self.start_time
            )

        self.current_stage = stage
        self.stage_times[f"_start_{stage}"] = time.perf_counter()

        self.logger.info(
            "workflow_stage_entered",
            session_id=self.session_id[:8],
            stage=stage,
            elapsed_ms=round((time.perf_counter() - self.start_time) * 1000, 2),
        )

    def log_event(self, event: str, **context) -> None:
        """Log a workflow event."""
        self.logger.debug(
            f"workflow_{event}",
            session_id=self.session_id[:8],
            stage=self.current_stage,
            **context,
        )

    def complete(self, status: str = "completed") -> None:
        """Log workflow completion with timing summary."""
        total_time = (time.perf_counter() - self.start_time) * 1000

        # Calculate stage times
        stage_summary = {
            k: round(v * 1000, 2)
            for k, v in self.stage_times.items()
            if not k.startswith("_")
        }

        self.logger.info(
            "workflow_completed",
            session_id=self.session_id[:8],
            ticker=self.ticker,
            status=status,
            total_duration_ms=round(total_time, 2),
            stage_times=stage_summary,
        )

    def error(self, error: str, stage: Optional[str] = None) -> None:
        """Log workflow error."""
        self.logger.error(
            "workflow_error",
            session_id=self.session_id[:8],
            ticker=self.ticker,
            stage=stage or self.current_stage,
            error=error,
            elapsed_ms=round((time.perf_counter() - self.start_time) * 1000, 2),
        )


# -------------------------------------------
# Decorators for Function Logging
# -------------------------------------------

def log_function_call(logger_name: str = "function"):
    """
    Decorator to log function calls with timing.

    Usage:
        @log_function_call("market_data")
        async def get_market_data(ticker: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        logger = structlog.get_logger(logger_name)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            func_name = func.__name__

            logger.debug(
                "function_called",
                function=func_name,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys()),
            )

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                logger.debug(
                    "function_completed",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    result_type=type(result).__name__,
                )

                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "function_failed",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            func_name = func.__name__

            logger.debug(
                "function_called",
                function=func_name,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys()),
            )

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                logger.debug(
                    "function_completed",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                )

                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "function_failed",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                )
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# -------------------------------------------
# Helper Functions
# -------------------------------------------

def _truncate_str(s: str, max_length: int = 200) -> str:
    """Truncate string for log output."""
    if len(s) <= max_length:
        return s
    return s[:max_length] + "..."


def _truncate_dict(d: Any, max_str_length: int = 100) -> dict:
    """Truncate dict values for log output."""
    if not isinstance(d, dict):
        return {"value": str(d)[:max_str_length]}

    result = {}
    for k, v in list(d.items())[:10]:  # Max 10 keys
        if isinstance(v, str):
            result[k] = _truncate_str(v, max_str_length)
        elif isinstance(v, dict):
            result[k] = f"<dict:{len(v)} keys>"
        elif isinstance(v, list):
            result[k] = f"<list:{len(v)} items>"
        else:
            result[k] = str(v)[:max_str_length]

    if len(d) > 10:
        result["..."] = f"+{len(d) - 10} more keys"

    return result


# -------------------------------------------
# Quick Access Logger Factory
# -------------------------------------------

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger instance by name."""
    return structlog.get_logger(name)
