"""The task-based multi-backend router.

Resolves a per-task fallback chain, guards each backend with a semaphore +
circuit breaker + timeout, walks the chain on failure, and enforces an optional
daily OpenRouter budget. Backends can be injected (tests) or built from settings.
"""
import asyncio
import time
from datetime import date
from typing import AsyncIterator, Callable, Optional

import structlog
from langchain_core.messages import BaseMessage

from agents.llm.backends.base import (
    BackendAuthError, BackendError, BackendTransientError, LLMAllBackendsFailed, LLMBackend,
)
from agents.llm.tasks import (
    ROUTING_POLICY, STRATEGIC_TASKS, BackendName, TaskType, coerce_task,
)
from app.config import settings

logger = structlog.get_logger()

# Flat per-successful-call OpenRouter cost estimate (USD). Coarse — the real cost
# isn't surfaced by the HTTP backend; this exists so the budget guard has signal.
_OPENROUTER_COST_ESTIMATE = 0.01


class CircuitBreaker:
    """Opens after `fail_threshold` consecutive failures for `cooldown` seconds
    (2x cooldown when the last failure was transient/rate-limited)."""

    def __init__(self, fail_threshold: int, cooldown: int, now: Callable[[], float] = time.monotonic):
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._now = now
        self._fails = 0
        self._opened_at: Optional[float] = None
        self._cooldown_used = cooldown

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        return self._now() >= self._opened_at + self._cooldown_used

    def record_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def record_failure(self, transient: bool = False) -> None:
        self._fails += 1
        if self._fails >= self.fail_threshold:
            self._opened_at = self._now()
            self._cooldown_used = self.cooldown * (2 if transient else 1)

    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self.allow() else "open"


class Router:
    def __init__(self, *, backends: Optional[dict] = None, now: Optional[Callable[[], float]] = None):
        self.settings = settings
        self._now = now or time.monotonic
        if backends is None:
            self._backends, self._claude_opus, self._claude_sonnet = self._build_from_settings()
        else:
            self._backends = dict(backends)
            claude = backends.get(BackendName.CLAUDE_CLI)
            self._claude_opus = self._claude_sonnet = claude

        self._breakers = {
            bn: CircuitBreaker(
                settings.LLM_CIRCUIT_FAIL_THRESHOLD, settings.LLM_CIRCUIT_COOLDOWN, now=self._now
            )
            for bn in BackendName
        }
        self._sems = {
            BackendName.OPENROUTER: asyncio.Semaphore(settings.LLM_OPENROUTER_CONCURRENCY),
            BackendName.CLAUDE_CLI: asyncio.Semaphore(settings.LLM_CLI_CONCURRENCY),
            BackendName.CODEX_CLI: asyncio.Semaphore(settings.LLM_CLI_CONCURRENCY),
            BackendName.LOCAL: asyncio.Semaphore(settings.LLM_LOCAL_CONCURRENCY),
        }
        self._timeouts = {
            BackendName.OPENROUTER: settings.LLM_TIMEOUT,
            BackendName.CLAUDE_CLI: settings.LLM_CLI_TIMEOUT,
            BackendName.CODEX_CLI: settings.LLM_CLI_TIMEOUT,
            BackendName.LOCAL: settings.LLM_TIMEOUT,
        }
        self._unavailable: set = set()  # auth-failed backends (disabled for the process)
        self._openrouter_spend = 0.0
        self._spend_day = date.today()
        self._health_cache: dict = {}

    # ---- construction ----

    def _build_from_settings(self):
        from agents.llm.backends.claude_cli import ClaudeCLIBackend
        from agents.llm.backends.codex_cli import CodexCLIBackend
        from agents.llm.backends.openai_compat import OpenAICompatBackend

        s = self.settings
        backends: dict = {}
        if s.OPENROUTER_API_KEY:
            backends[BackendName.OPENROUTER] = OpenAICompatBackend(
                name=BackendName.OPENROUTER, base_url=s.OPENROUTER_BASE_URL,
                model=s.OPENROUTER_MODEL, api_key=s.OPENROUTER_API_KEY.get_secret_value(),
                timeout=s.LLM_TIMEOUT, default_temperature=s.LLM_TEMPERATURE,
                default_max_tokens=s.LLM_MAX_TOKENS,
            )
        else:
            logger.warning("openrouter_backend_not_constructed_no_key")
        if s.LLM_LOCAL_ENABLED:
            backends[BackendName.LOCAL] = OpenAICompatBackend(
                name=BackendName.LOCAL, base_url=s.LLM_BASE_URL, model=s.LLM_MODEL,
                api_key="not-needed-for-local", timeout=s.LLM_TIMEOUT,
                default_temperature=s.LLM_TEMPERATURE, default_max_tokens=s.LLM_MAX_TOKENS,
            )
        backends[BackendName.CODEX_CLI] = CodexCLIBackend(
            cli_path=s.CODEX_CLI_PATH, model=s.CODEX_MODEL, timeout=s.LLM_CLI_TIMEOUT
        )
        claude_opus = ClaudeCLIBackend(
            cli_path=s.CLAUDE_CLI_PATH, model=s.CLAUDE_STRATEGIC_MODEL, timeout=s.LLM_CLI_TIMEOUT
        )
        claude_sonnet = ClaudeCLIBackend(
            cli_path=s.CLAUDE_CLI_PATH, model=s.CLAUDE_FALLBACK_MODEL, timeout=s.LLM_CLI_TIMEOUT
        )
        backends[BackendName.CLAUDE_CLI] = claude_sonnet  # registry default
        return backends, claude_opus, claude_sonnet

    def _backend_for(self, bn: BackendName, task: TaskType) -> Optional[LLMBackend]:
        if bn == BackendName.CLAUDE_CLI:
            return self._claude_opus if task in STRATEGIC_TASKS else self._claude_sonnet
        return self._backends.get(bn)

    # ---- budget ----

    def _maybe_reset_day(self) -> None:
        today = date.today()
        if today != self._spend_day:
            self._spend_day = today
            self._openrouter_spend = 0.0

    def add_openrouter_spend(self, usd: float) -> None:
        self._maybe_reset_day()
        self._openrouter_spend += usd

    def _over_budget(self) -> bool:
        self._maybe_reset_day()
        budget = self.settings.OPENROUTER_DAILY_BUDGET_USD
        return budget is not None and self._openrouter_spend >= budget

    # ---- resolution ----

    def resolve(self, task: TaskType, streaming: bool) -> list:
        chain = list(ROUTING_POLICY[task])
        if self.settings.LLM_LOCAL_ENABLED:
            chain.append(BackendName.LOCAL)
        out = []
        for bn in chain:
            backend = self._backend_for(bn, task)
            if backend is None:
                continue
            if bn in self._unavailable:
                continue
            if not self._breakers[bn].allow():
                continue
            if streaming and not backend.supports_stream:
                continue
            if bn == BackendName.OPENROUTER and self._over_budget():
                continue
            out.append(backend)
        return out

    # ---- generation ----

    async def generate(
        self,
        messages: list[BaseMessage],
        *,
        task=TaskType.GENERAL,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_schema: Optional[dict] = None,
    ) -> str:
        task = coerce_task(task)
        chain = self.resolve(task, streaming=False)
        if not chain:
            raise LLMAllBackendsFailed(f"no available backend for task '{task.value}'")
        last: Optional[Exception] = None
        for backend in chain:
            bn = backend.name
            try:
                async with self._sems[bn]:
                    result = await asyncio.wait_for(
                        backend.generate(
                            messages, temperature=temperature, max_tokens=max_tokens,
                            response_schema=response_schema,
                        ),
                        timeout=self._timeouts[bn],
                    )
                self._breakers[bn].record_success()
                if bn == BackendName.OPENROUTER:
                    self.add_openrouter_spend(_OPENROUTER_COST_ESTIMATE)
                return result
            except (BackendError, asyncio.TimeoutError, TimeoutError) as e:
                transient = isinstance(e, (BackendTransientError, asyncio.TimeoutError, TimeoutError))
                self._breakers[bn].record_failure(transient=transient)
                if isinstance(e, BackendAuthError):
                    self._unavailable.add(bn)
                logger.warning("llm_fallback", from_backend=bn.value, task=task.value, reason=str(e)[:120])
                last = e
                continue
        raise LLMAllBackendsFailed(f"all backends failed for task '{task.value}': {last}")

    async def stream(
        self,
        messages: list[BaseMessage],
        *,
        task=TaskType.GENERAL,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        task = coerce_task(task)
        chain = self.resolve(task, streaming=True)
        if not chain:
            raise LLMAllBackendsFailed(f"no streaming backend for task '{task.value}'")
        last: Optional[Exception] = None
        for backend in chain:
            bn = backend.name
            try:
                async with self._sems[bn]:
                    async for chunk in backend.stream(messages, temperature=temperature, max_tokens=max_tokens):
                        yield chunk
                self._breakers[bn].record_success()
                return
            except (BackendError, asyncio.TimeoutError, TimeoutError) as e:
                self._breakers[bn].record_failure()
                logger.warning("llm_stream_fallback", from_backend=bn.value, task=task.value, reason=str(e)[:120])
                last = e
                continue
        raise LLMAllBackendsFailed(f"all streaming backends failed for task '{task.value}': {last}")

    # ---- lifecycle / introspection ----

    async def startup(self) -> None:
        """Best-effort health probes (cached for /api/llm/stats). Never raises."""
        probes = dict(self._backends)
        probes[BackendName.CLAUDE_CLI] = self._claude_sonnet
        for bn, backend in probes.items():
            if backend is None:
                continue
            try:
                self._health_cache[bn] = await backend.health()
            except Exception:
                self._health_cache[bn] = False
        logger.info("llm_router_startup", health={k.value: v for k, v in self._health_cache.items()})

    async def aclose(self) -> None:
        logger.info("llm_router_closed")

    def snapshot(self) -> dict:
        return {
            "backends": {
                bn.value: {
                    "constructed": self._backend_for(bn, TaskType.GENERAL) is not None,
                    "unavailable": bn in self._unavailable,
                    "circuit": self._breakers[bn].state(),
                    "healthy": self._health_cache.get(bn),
                }
                for bn in BackendName
            },
            "openrouter_spend_today": round(self._openrouter_spend, 4),
            "openrouter_budget_usd": self.settings.OPENROUTER_DAILY_BUDGET_USD,
        }


# ---- module singleton ----

_router: Optional[Router] = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router


def reset_router() -> None:
    global _router
    _router = None
