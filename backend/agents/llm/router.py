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
    BackendAuthError, BackendError, BackendTransientError, BackendUsageLimitError,
    LLMAllBackendsFailed, LLMBackend,
)
from agents.llm.tasks import (
    ROUTING_POLICY, STRATEGIC_TASKS, BackendName, TaskType, coerce_task,
)
from app.config import settings

logger = structlog.get_logger()

# Flat per-successful-call OpenRouter cost estimate (USD). Coarse — the real cost
# isn't surfaced by the HTTP backend; this exists so the budget guard has signal.
_OPENROUTER_COST_ESTIMATE = 0.01

# 사용량 한도 대기 — 상한은 **신선도**에서 유도된 값이다. 멈췄던 토론은 멈춘 시점의
# 가격·차트를 들고 있어서, 이보다 오래 기다렸다 재개하면 낡은 값으로 매매를 결정한다.
# 감시 주기가 1분이므로 버려도 곧 새 데이터로 다시 시작한다 — 재개해서 아끼는 것은
# "이미 한 분석"뿐이고, 잃는 것은 판단의 근거다.
#
# 알려진 한계(고치지 않음, 2026-08-03 리뷰 Finding 3): 이 상한은 `generate()` 호출
# 1건에 붙는다. 근거(신선도)는 토론 1건 전체에 붙어야 맞는데, 토론 한 번에 LLM 호출이
# 여러 단계(예: 4에이전트 각각 + 모더레이터)면 각 단계가 독립적으로 최대 300초씩
# 기다릴 수 있어 토론 전체로는 300초를 크게 넘길 수 있다. 상한을 토론 단위로 옮기려면
# `chat_room` 상태 기계를 건드려야 하는데, 이번 아크 범위 밖이다(ld-global-constraints).
_USAGE_LIMIT_WAIT_SECONDS = 300   # 감시 주기(1분)의 5배
_USAGE_LIMIT_RETRY_INTERVAL = 20


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
            if self._health_cache.get(bn) is False:  # probed down at startup
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
        deadline: Optional[float] = None
        last: Optional[Exception] = None

        def _give_up() -> None:
            logger.error(
                "llm_usage_limit_gave_up",
                task=task.value,
                waited_seconds=_USAGE_LIMIT_WAIT_SECONDS,
                reason=str(last)[:160],
            )
            raise LLMAllBackendsFailed(
                f"usage limit outlasted the {_USAGE_LIMIT_WAIT_SECONDS}s freshness cap "
                f"for task '{task.value}': {last}"
            )

        # 서킷 차단기 charge(페널티)는 이 generate() 호출 안에서 백엔드별로 딱 한 번만
        # 한다 — 재시도 패스마다 charge하면 몇 패스 만에(threshold=3이면 40초 만에)
        # 서킷이 열려 resolve()가 빈 체인을 반환하고, "체인이 비면 즉시 던진다" 규칙과
        # 충돌해 300초 대기가 사실상 도달 불가능해진다(2026-08-03 리뷰 Finding 1).
        # 헬스 캐시 갱신은 반대로 **매 실패마다** 해야 하는 관측이다(Task 3B가 여기
        # 붙는다) — 페널티(서킷)와 관측(헬스)을 한 자리에 섞지 않는다.
        charged_this_call: set = set()

        while True:
            now = self._now()
            if deadline is not None and now >= deadline:
                # 새 패스를 시작하기 전에도 상한을 확인한다. 패스 하나가 최대
                # LLM_TIMEOUT/LLM_CLI_TIMEOUT만큼 걸릴 수 있어, 패스가 끝난 뒤에만
                # 확인하면(아래) 행(hang) 백엔드 하나가 상한을 통째로 넘길 수 있다
                # (Finding 2).
                _give_up()
            chain = self.resolve(task, streaming=False)
            if not chain:
                # 체인이 비었다 = 서킷이 열렸거나 전부 unavailable. 기다려도 이 패스에서
                # 달라질 것이 없고, 긴 장애에 신선도 예산을 낭비할 이유가 없다.
                raise LLMAllBackendsFailed(f"no available backend for task '{task.value}'")
            for backend in chain:
                bn = backend.name
                timeout = self._timeouts[bn]
                if deadline is not None:
                    remaining = deadline - self._now()
                    if remaining <= 0:
                        # 이 백엔드를 시도할 예산이 이미 없다 — 시도하지 않고 패스를
                        # 접어 아래 give-up 경로로 넘긴다.
                        break
                    # 시도별 타임아웃을 남은 예산으로 clamp한다 — 안 그러면 행 백엔드
                    # 하나가 신선도 상한을 통째로 넘길 수 있다(Finding 2).
                    timeout = min(timeout, remaining)
                try:
                    async with self._sems[bn]:
                        result = await asyncio.wait_for(
                            backend.generate(
                                messages, temperature=temperature, max_tokens=max_tokens,
                                response_schema=response_schema,
                            ),
                            timeout=timeout,
                        )
                    self._breakers[bn].record_success()
                    if bn == BackendName.OPENROUTER:
                        self.add_openrouter_spend(_OPENROUTER_COST_ESTIMATE)
                    return result
                except (BackendError, asyncio.TimeoutError, TimeoutError) as e:
                    transient = isinstance(e, (BackendTransientError, asyncio.TimeoutError, TimeoutError))
                    if bn not in charged_this_call:
                        self._breakers[bn].record_failure(transient=transient)  # 페널티: 호출당 1회
                        charged_this_call.add(bn)
                    if isinstance(e, BackendAuthError):
                        self._unavailable.add(bn)
                    logger.warning("llm_fallback", from_backend=bn.value, task=task.value, reason=str(e)[:120])
                    last = e
                    continue

            # 이 패스의 모든 백엔드가 실패했다(또는 예산 부족으로 건너뛰었다). 기다리면
            # 풀리는 종류만 기다린다 — 인증 오류·모델 부재·네트워크 실패는 대기로 해결
            # 되지 않는다.
            # NOTE: `last`는 체인의 **마지막** 백엔드가 남긴 예외다 — 즉 대기 여부가
            # 체인 순서에 좌우된다(설계 그대로 유지; 알려진 한계로만 남긴다).
            if not isinstance(last, BackendUsageLimitError):
                raise LLMAllBackendsFailed(f"all backends failed for task '{task.value}': {last}")
            now = self._now()
            if deadline is None:
                deadline = now + _USAGE_LIMIT_WAIT_SECONDS
                logger.warning(
                    "llm_usage_limit_waiting",
                    task=task.value,
                    cap_seconds=_USAGE_LIMIT_WAIT_SECONDS,
                    reason=str(last)[:160],
                )
            if now >= deadline:
                _give_up()
            await asyncio.sleep(_USAGE_LIMIT_RETRY_INTERVAL)

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
