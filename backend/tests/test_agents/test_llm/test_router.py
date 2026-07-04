"""Phase 1: Router — chain resolution, streaming filter, circuit breaker, fallback,
budget guard, graceful degrade. Pure unit tests with fake backends (no network/CLI)."""
import pytest
from langchain_core.messages import HumanMessage

from agents.llm.backends.base import (
    LLMBackend, BackendError, LLMAllBackendsFailed,
)
from agents.llm.router import Router, CircuitBreaker
from agents.llm.tasks import BackendName, TaskType


class FakeBackend(LLMBackend):
    def __init__(self, name, *, result="ok", error=None, supports_stream=False):
        self.name = name
        self._result = result
        self._error = error
        self.supports_stream = supports_stream
        self.supports_schema = True
        self.calls = 0

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._result

    async def health(self):
        return True


def _router(backends, now=None):
    return Router(backends=backends, now=now)


# ---------- resolve ----------

def test_resolve_scanner_openrouter_only():
    orr = FakeBackend(BackendName.OPENROUTER)
    r = _router({BackendName.OPENROUTER: orr, BackendName.CLAUDE_CLI: FakeBackend(BackendName.CLAUDE_CLI)})
    chain = r.resolve(TaskType.SCANNER, streaming=False)
    assert [b.name for b in chain] == [BackendName.OPENROUTER]


def test_resolve_drops_missing_openrouter():
    # scanner has only openrouter; if it isn't constructed, chain is empty
    r = _router({BackendName.CLAUDE_CLI: FakeBackend(BackendName.CLAUDE_CLI)})
    assert r.resolve(TaskType.SCANNER, streaming=False) == []


def test_streaming_filter_drops_non_stream_backends():
    claude = FakeBackend(BackendName.CLAUDE_CLI, supports_stream=False)
    orr = FakeBackend(BackendName.OPENROUTER, supports_stream=True)
    r = _router({BackendName.OPENROUTER: orr, BackendName.CLAUDE_CLI: claude})
    # strategic_decision chain is [claude, openrouter]; streaming keeps only openrouter
    chain = r.resolve(TaskType.STRATEGIC_DECISION, streaming=True)
    assert [b.name for b in chain] == [BackendName.OPENROUTER]


# ---------- generate + fallback ----------

@pytest.mark.asyncio
async def test_fallback_to_second_backend():
    bad = FakeBackend(BackendName.CLAUDE_CLI, error=BackendError("boom"))
    good = FakeBackend(BackendName.OPENROUTER, result="recovered")
    r = _router({BackendName.OPENROUTER: good, BackendName.CLAUDE_CLI: bad})
    out = await r.generate([HumanMessage(content="x")], task=TaskType.STRATEGIC_DECISION)
    assert out == "recovered"
    assert bad.calls == 1 and good.calls == 1


@pytest.mark.asyncio
async def test_all_fail_raises():
    r = _router({BackendName.OPENROUTER: FakeBackend(BackendName.OPENROUTER, error=BackendError("x"))})
    with pytest.raises(LLMAllBackendsFailed):
        await r.generate([HumanMessage(content="x")], task=TaskType.SCANNER)


@pytest.mark.asyncio
async def test_empty_chain_raises():
    r = _router({BackendName.CLAUDE_CLI: FakeBackend(BackendName.CLAUDE_CLI)})
    with pytest.raises(LLMAllBackendsFailed):
        await r.generate([HumanMessage(content="x")], task=TaskType.SCANNER)


# ---------- circuit breaker ----------

def test_circuit_breaker_opens_and_recovers():
    clock = {"t": 0.0}
    cb = CircuitBreaker(fail_threshold=2, cooldown=60, now=lambda: clock["t"])
    assert cb.allow()
    cb.record_failure(); cb.record_failure()
    assert not cb.allow()          # open after 2 fails
    clock["t"] = 61
    assert cb.allow()              # half-open after cooldown
    cb.record_success()
    assert cb.allow()              # reset


@pytest.mark.asyncio
async def test_open_circuit_skips_backend():
    clock = {"t": 0.0}
    bad = FakeBackend(BackendName.CLAUDE_CLI, error=BackendError("boom"))
    good = FakeBackend(BackendName.OPENROUTER, result="ok")
    r = _router({BackendName.OPENROUTER: good, BackendName.CLAUDE_CLI: bad}, now=lambda: clock["t"])
    # drive claude's breaker open (default threshold from settings = 3)
    for _ in range(3):
        await r.generate([HumanMessage(content="x")], task=TaskType.STRATEGIC_DECISION)
    bad_calls_after_open = bad.calls
    await r.generate([HumanMessage(content="x")], task=TaskType.STRATEGIC_DECISION)
    assert bad.calls == bad_calls_after_open  # claude skipped while circuit open


# ---------- budget ----------

@pytest.mark.asyncio
async def test_budget_exhaustion_drops_openrouter():
    good = FakeBackend(BackendName.OPENROUTER, result="ok")
    r = _router({BackendName.OPENROUTER: good})
    r.add_openrouter_spend(1000.0)  # far over the default $5/day budget
    assert r.resolve(TaskType.SCANNER, streaming=False) == []
    with pytest.raises(LLMAllBackendsFailed):
        await r.generate([HumanMessage(content="x")], task=TaskType.SCANNER)


def test_snapshot_shape():
    r = _router({BackendName.OPENROUTER: FakeBackend(BackendName.OPENROUTER)})
    snap = r.snapshot()
    assert "backends" in snap


# ---------- health cache gating + missing-CLI fall-through ----------

def test_unhealthy_backend_dropped_from_resolve():
    r = _router({BackendName.OPENROUTER: FakeBackend(BackendName.OPENROUTER)})
    r._health_cache[BackendName.OPENROUTER] = False  # probed down at startup
    assert r.resolve(TaskType.SCANNER, streaming=False) == []


@pytest.mark.asyncio
async def test_auth_error_falls_through_and_marks_unavailable():
    from agents.llm.backends.base import BackendAuthError

    bad = FakeBackend(BackendName.CLAUDE_CLI, error=BackendAuthError("cli not found"))
    good = FakeBackend(BackendName.OPENROUTER, result="ok")
    r = _router({BackendName.OPENROUTER: good, BackendName.CLAUDE_CLI: bad})
    out = await r.generate([HumanMessage(content="x")], task=TaskType.STRATEGIC_DECISION)
    assert out == "ok"
    assert BackendName.CLAUDE_CLI in r._unavailable  # won't be retried next call
    # next call skips claude entirely
    bad_calls = bad.calls
    await r.generate([HumanMessage(content="x")], task=TaskType.STRATEGIC_DECISION)
    assert bad.calls == bad_calls
