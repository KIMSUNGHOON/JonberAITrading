# Phase 1 — Intelligence-Layer Router: Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the single-backend Ollama LLM facade with a task-routed multi-backend layer (OpenRouter/deepseek-v4-flash + keyless Claude CLI + keyless Codex CLI + optional local), preserving `get_llm_provider().generate()` so all ~25 callers keep working.

**Architecture:** New `backend/agents/llm/` package (tasks/messages/subprocess_runner/router + backends/{base,openai_compat,claude_cli,codex_cli}). `llm_provider.py` stays the public facade and delegates to a module-singleton Router with per-backend semaphore + circuit-breaker + timeout + fallback chain + optional daily budget guard. Design doc: `docs/superpowers/specs/2026-07-04-intelligence-layer-restructure-design.md`.

**Tech Stack:** Python 3.12 (conda env `agentic-trading`), langchain-openai (ChatOpenAI, kept for HTTP backends), pydantic v2 + pydantic-settings, tenacity, structlog, asyncio subprocess.

## Global Constraints

- **Env/CWD:** run python/pytest as `/Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python -m pytest ... --no-cov -o addopts="" -q` (FOREGROUND; full suite + coverage stalls). CWD `backend/`. To import graph modules standalone, `import app.api.routes` first (pre-existing circular import).
- **Backward compat (hard):** `await get_llm_provider().generate(messages[, temperature, max_tokens])` keeps its exact positional signature and `str` return. `task`/`response_schema` are keyword-only additions. `task=None -> GENERAL`. Unknown task string -> GENERAL (logged once), never raises.
- **Cloud-first:** default/fallback tier = OpenRouter; `local` backend class exists but is only registered when `LLM_LOCAL_ENABLED=true`. No Ollama in default chains.
- **Secrets = prevention only:** the ONLY secret is `OPENROUTER_API_KEY` (`SecretStr`, from gitignored `.env`, `get_secret_value()` only at backend construction, never logged/argv). CLIs keyless. If the key is empty, the openrouter backend is simply not constructed (graceful degrade, no crash). No rotation/history rewrite.
- **Subprocess safety:** prompts contain arbitrary market/news text -> pass via argv array / stdin ONLY, never `shell=True`, never string-interpolated into a shell. CLIs run with `cwd=<throwaway tempdir>`, tools disabled (`--tools ""` / `-s read-only`), MCP ignored (`--strict-mcp-config`).
- **Commits:** conventional (`feat:`/`refactor:`/`test:`), end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Do NOT** touch trade signals/decisions (Phase 3), the 3 market stacks (Phase 4), or live trading (frozen).

## Verified CLI contracts (captured 2026-07-05 from installed CLIs)

**Claude** (`claude` 2.1.201), `claude -p --output-format json --tools "" --strict-mcp-config --system-prompt "<sys>" --model <opus|sonnet|haiku> [--json-schema '<schema>'] "<user>"` → stdout is ONE JSON object:
```json
{"type":"result","subtype":"success","is_error":false,"result":"PONG","stop_reason":"end_turn","total_cost_usd":0.0032,"usage":{...},"permission_denials":[]}
```
Parse: `json.loads(stdout)`; success = `subtype=="success" and not is_error`; text = `obj["result"]`; treat non-zero exit / unparseable / `is_error` as failure; stderr matching `rate limit|overloaded|429` → transient.

**Codex** (`codex` 0.142.4, account model gpt-5.5), `codex exec -s read-only --skip-git-repo-check -C <tmpdir> --color never -o <outfile> [--output-schema <schemafile>] [-m <model>] -` with the system+user prompt on stdin → the clean final message is written to `<outfile>` (stdout is the full transcript; DO NOT parse stdout). Parse: read `<outfile>`.

---

## File Structure

```
backend/agents/
  llm_provider.py            # MODIFY — facade delegates to router; +task/+response_schema/+generate_structured
  llm/
    __init__.py              # CREATE
    tasks.py                 # CREATE — TaskType, BackendName, ROUTING_POLICY, DECISION_SCHEMA
    messages.py              # CREATE — flatten_messages()
    subprocess_runner.py     # CREATE — run_cli()
    router.py                # CREATE — Router, CircuitBreaker, get_router()/reset_router()
    backends/
      __init__.py            # CREATE
      base.py                # CREATE — LLMBackend ABC + exception hierarchy
      openai_compat.py       # CREATE — OpenAICompatBackend (openrouter + optional local)
      claude_cli.py          # CREATE — ClaudeCLIBackend
      codex_cli.py           # CREATE — CodexCLIBackend
backend/app/config.py        # MODIFY — OpenRouter/CLI/budget/concurrency settings
backend/app/main.py          # MODIFY — lifespan router.startup()/aclose(); GET /api/llm/stats
backend/services/background_scanner/scanner.py  # MODIFY — task="scanner" at 2 call sites
backend/.env.example + ../.env.example           # MODIFY — OPENROUTER_API_KEY=
backend/tests/test_agents/test_llm/              # CREATE — test_router.py, test_cli_backends.py, test_facade_compat.py
```

---

### Task 1: Config — OpenRouter/CLI/budget/concurrency settings

**Files:** Modify `backend/app/config.py`; Modify `backend/.env.example` (+ root `.env.example`).

**Interfaces produced:** `settings.OPENROUTER_API_KEY: SecretStr | None`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, `LLM_LOCAL_ENABLED: bool`, `CLAUDE_CLI_PATH`, `CODEX_CLI_PATH`, `CLAUDE_STRATEGIC_MODEL`, `CLAUDE_FALLBACK_MODEL`, `CODEX_MODEL: str | None`, `OPENROUTER_DAILY_BUDGET_USD: float | None`, plus per-backend concurrency/timeout ints.

- [ ] **Step 1 (test):** `tests/test_agents/test_llm/test_config.py`:
```python
from app.config import Settings

def test_openrouter_and_cli_settings_exist():
    s = Settings()
    assert s.OPENROUTER_BASE_URL.startswith("https://openrouter.ai")
    assert s.OPENROUTER_MODEL  # non-empty default
    assert s.LLM_LOCAL_ENABLED is False           # cloud-first default
    assert s.CLAUDE_STRATEGIC_MODEL == "opus"
    assert s.OPENROUTER_DAILY_BUDGET_USD == 5.0
    # SecretStr never leaks in repr
    s2 = Settings(OPENROUTER_API_KEY="sk-secret-xyz")
    assert "sk-secret-xyz" not in repr(s2)
    assert s2.OPENROUTER_API_KEY.get_secret_value() == "sk-secret-xyz"
```
- [ ] **Step 2:** run → FAIL (fields absent).
- [ ] **Step 3:** in `config.py` add `from pydantic import Field, SecretStr` and, after the LLM block, add:
```python
    # OpenRouter (cloud LLM — the only secret in the intelligence layer)
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "deepseek-v4-flash"
    OPENROUTER_DAILY_BUDGET_USD: float | None = 5.0

    # Local backend (Ollama/vLLM) — retired from default chains; opt-in for Windows GPU
    LLM_LOCAL_ENABLED: bool = False

    # CLI backends (keyless — auth via local OAuth subscription)
    CLAUDE_CLI_PATH: str = "claude"
    CODEX_CLI_PATH: str = "codex"
    CLAUDE_STRATEGIC_MODEL: str = "opus"
    CLAUDE_FALLBACK_MODEL: str = "sonnet"
    CODEX_MODEL: str | None = None  # None -> codex account default

    # Per-backend concurrency + timeouts (seconds)
    LLM_OPENROUTER_CONCURRENCY: int = 8
    LLM_CLI_CONCURRENCY: int = 2
    LLM_LOCAL_CONCURRENCY: int = 3
    LLM_CLI_TIMEOUT: int = 180
    LLM_CIRCUIT_FAIL_THRESHOLD: int = 3
    LLM_CIRCUIT_COOLDOWN: int = 60
```
Add to both `.env.example` files a documented block: `OPENROUTER_API_KEY=` (empty) + note "CLIs (claude/codex) need NO key — they use your local subscription login."
- [ ] **Step 4:** run test → PASS. **Step 5:** commit.

---

### Task 2: tasks.py — taxonomy, routing policy, decision schema

**Files:** Create `backend/agents/llm/__init__.py` (empty), `backend/agents/llm/tasks.py`.

**Interfaces produced:** `TaskType(str,Enum)`, `BackendName(str,Enum)` = {OPENROUTER, CLAUDE_CLI, CODEX_CLI, LOCAL}, `ROUTING_POLICY: dict[TaskType, list[BackendName]]`, `CLAUDE_MODEL_BY_TASK: dict[TaskType, str]` (strategic/risk→"opus" else "sonnet"), `DECISION_SCHEMA: dict`, `coerce_task(value) -> TaskType`.

- [ ] **Step 1 (test):** `test_llm/test_tasks.py`:
```python
from agents.llm.tasks import TaskType, BackendName, ROUTING_POLICY, coerce_task, DECISION_SCHEMA

def test_routing_policy_shape():
    assert ROUTING_POLICY[TaskType.STRATEGIC_DECISION][0] == BackendName.CLAUDE_CLI
    assert ROUTING_POLICY[TaskType.SCANNER] == [BackendName.OPENROUTER]  # no CLI for high volume
    assert ROUTING_POLICY[TaskType.GENERAL][0] == BackendName.OPENROUTER  # cloud-first
    # every task has at least one backend
    assert all(len(v) >= 1 for v in ROUTING_POLICY.values())

def test_coerce_task():
    assert coerce_task(None) == TaskType.GENERAL
    assert coerce_task("scanner") == TaskType.SCANNER
    assert coerce_task("not-a-real-task") == TaskType.GENERAL  # graceful

def test_decision_schema():
    assert DECISION_SCHEMA["type"] == "object"
    assert "action" in DECISION_SCHEMA["required"]
```
- [ ] **Step 2:** FAIL. **Step 3:** implement per spec §5 routing table:
  - TaskType members: STRATEGIC_DECISION, RISK, TASK_DECOMPOSITION, TECHNICAL_ANALYSIS, FUNDAMENTAL_ANALYSIS, SENTIMENT_ANALYSIS, GROUP_CHAT, SCANNER, TRANSLATION, CHAT, UTILITY, GENERAL.
  - ROUTING_POLICY (cloud-first, from spec): strategic_decision/risk → [CLAUDE_CLI, OPENROUTER]; task_decomposition/utility → [CODEX_CLI, OPENROUTER, CLAUDE_CLI]; technical/fundamental/sentiment/group_chat/translation → [OPENROUTER, CLAUDE_CLI]; scanner → [OPENROUTER]; chat → [OPENROUTER]; general → [OPENROUTER, CLAUDE_CLI]. (Append LOCAL to each only if `settings.LLM_LOCAL_ENABLED` — do that in the Router's resolve, not here; keep policy pure.)
  - `coerce_task`: `try: return TaskType(value)` (str value matches member value) `except: log once, return GENERAL`; None → GENERAL.
  - `DECISION_SCHEMA`: object with action(enum BUY/SELL/HOLD/ADD/REDUCE/WATCH/AVOID), confidence(number), summary(string), bull_case(array), bear_case(array), rationale(string); required [action, confidence, rationale].
- [ ] **Step 4:** PASS. **Step 5:** commit.

---

### Task 3: backends/base.py — LLMBackend ABC + exception hierarchy

**Files:** Create `backend/agents/llm/backends/__init__.py` (empty), `backend/agents/llm/backends/base.py`.

**Interfaces produced:** `class LLMBackend(ABC)` with props `name: BackendName`, `supports_stream: bool`, `supports_schema: bool`; async `generate(messages, *, temperature, max_tokens, response_schema=None) -> str`; async `stream(messages, *, temperature, max_tokens) -> AsyncIterator[str]`; async `health() -> bool`. Exceptions: `BackendError(Exception)` ← `BackendTransientError`, `BackendTimeoutError`, `BackendAuthError`; top-level `LLMAllBackendsFailed(Exception)`.

- [ ] **Step 1 (test):** `test_llm/test_base.py` — assert the ABC cannot be instantiated, a trivial subclass implementing the abstracts can, and the exception subclass relationships hold (`issubclass(BackendTransientError, BackendError)`).
- [ ] **Step 2:** FAIL. **Step 3:** implement (abstractmethods; `stream` default raises `NotImplementedError`; concrete backends override). **Step 4:** PASS. **Step 5:** commit.

---

### Task 4: messages.py — flatten_messages()

**Files:** Create `backend/agents/llm/messages.py`.

**Interfaces produced:** `flatten_messages(messages: list[BaseMessage]) -> tuple[str, str]` returning `(system_str, user_str)`.

- [ ] **Step 1 (test):** `test_llm/test_messages.py`:
```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from agents.llm.messages import flatten_messages

def test_flatten_splits_system_and_renders_history():
    sys, user = flatten_messages([
        SystemMessage(content="S1"), SystemMessage(content="S2"),
        HumanMessage(content="H1"), AIMessage(content="A1"), HumanMessage(content="H2"),
    ])
    assert "S1" in sys and "S2" in sys
    assert "H1" in user and "A1" in user and "H2" in user

def test_flatten_no_system():
    sys, user = flatten_messages([HumanMessage(content="hi")])
    assert sys == "" and "hi" in user
```
- [ ] **Step 2:** FAIL. **Step 3:** implement — concatenate all `SystemMessage.content` with `\n\n` into system_str; render Human/AI history as a transcript (`Human: ...` / `Assistant: ...`) into user_str, trailing Human last. Coerce non-str content via `str()`. **Step 4:** PASS. **Step 5:** commit.

---

### Task 5: subprocess_runner.py — safe run_cli()

**Files:** Create `backend/agents/llm/subprocess_runner.py`.

**Interfaces produced:** `async def run_cli(argv: list[str], *, stdin: str | None = None, timeout: float, cwd: str) -> tuple[int, str, str]` returning `(returncode, stdout, stderr)`.

- [ ] **Step 1 (test):** `test_llm/test_subprocess_runner.py` (uses real trivial commands, no network):
```python
import pytest
from agents.llm.subprocess_runner import run_cli

@pytest.mark.asyncio
async def test_run_cli_passes_stdin_and_returns_output():
    rc, out, err = await run_cli(["cat"], stdin="hello", timeout=10, cwd="/tmp")
    assert rc == 0 and out.strip() == "hello"

@pytest.mark.asyncio
async def test_run_cli_argv_is_not_shell():
    # a shell would expand $(...); exec must pass it literally
    rc, out, err = await run_cli(["printf", "%s", "$(whoami)"], stdin=None, timeout=10, cwd="/tmp")
    assert out == "$(whoami)"

@pytest.mark.asyncio
async def test_run_cli_timeout_kills():
    with pytest.raises(TimeoutError):
        await run_cli(["sleep", "5"], stdin=None, timeout=0.3, cwd="/tmp")
```
- [ ] **Step 2:** FAIL. **Step 3:** implement with `asyncio.create_subprocess_exec(*argv, stdin=PIPE if stdin else None, stdout=PIPE, stderr=PIPE, cwd=cwd)`, `await asyncio.wait_for(proc.communicate(input=stdin.encode() if stdin else None), timeout)`; on `asyncio.TimeoutError` → `proc.kill(); await proc.wait()` then `raise TimeoutError`. Decode out/err utf-8 errors="replace". NEVER `shell=True`. **Step 4:** PASS. **Step 5:** commit.

---

### Task 6: backends/openai_compat.py — OpenAICompatBackend

**Files:** Create `backend/agents/llm/backends/openai_compat.py`.

**Interfaces produced:** `class OpenAICompatBackend(LLMBackend)` — ctor `(name, base_url, model, api_key, timeout, default_temperature, default_max_tokens)`; `supports_stream=True`, `supports_schema=True`. Lifts the current `ChatOpenAI` usage from `llm_provider.py`. Narrow `tenacity` retry (`stop_after_attempt(2)`) on httpx connect/429/5xx mapped to `BackendTransientError`; `generate(response_schema=...)` sets `response_format={"type":"json_schema","json_schema":{"name":"decision","schema":...}}`; `health()` GETs `{base_url}/models`.

- [ ] **Step 1 (test):** `test_llm/test_openai_compat.py` — construct with a dummy key, monkeypatch its internal `ChatOpenAI` client's `ainvoke` (AsyncMock returning an object with `.content="hi"`) and assert `await backend.generate([HumanMessage("x")], temperature=0.6, max_tokens=100) == "hi"`. Assert `supports_stream and supports_schema`.
- [ ] **Step 2:** FAIL. **Step 3:** implement (lazy `ChatOpenAI` like current code; reuse `LLMConfig` patterns). **Step 4:** PASS. **Step 5:** commit.

---

### Task 7: backends/claude_cli.py — ClaudeCLIBackend

**Files:** Create `backend/agents/llm/backends/claude_cli.py`.

**Interfaces produced:** `class ClaudeCLIBackend(LLMBackend)` — ctor `(cli_path, model, timeout)`; `supports_stream=False`, `supports_schema=True`. `generate` builds argv `[cli_path, "-p", "--output-format","json","--tools","","--strict-mcp-config","--system-prompt",system_str,"--model",model]` + (`["--json-schema", json.dumps(schema)]` if response_schema) + `[user_str]`; runs via `run_cli(argv, cwd=<tempfile.mkdtemp()>, timeout=timeout)`; parse `json.loads(stdout)`, require `subtype=="success" and not is_error` else raise (`BackendTransientError` if stderr/`api_error_status` looks like rate limit, else `BackendError`); return `obj["result"]`. Cleanup tempdir in `finally`. `health()` runs a trivial `--model haiku "ok"` probe (returns bool).

- [ ] **Step 1 (test):** `test_llm/test_cli_backends.py::test_claude_parses_success_envelope` — monkeypatch `agents.llm.backends.claude_cli.run_cli` (AsyncMock) to return `(0, '{"type":"result","subtype":"success","is_error":false,"result":"PONG"}', "")`; assert `generate` returns `"PONG"`. Add `test_claude_raises_on_is_error` (envelope with `is_error:true` → `BackendError`) and `test_claude_argv_has_no_shell_and_disables_tools` (capture argv passed to run_cli; assert `--tools ""` present and prompt is a discrete argv element, not interpolated).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit.

---

### Task 8: backends/codex_cli.py — CodexCLIBackend

**Files:** Create `backend/agents/llm/backends/codex_cli.py`.

**Interfaces produced:** `class CodexCLIBackend(LLMBackend)` — `supports_stream=False`, `supports_schema=True`. `generate` makes a tempdir + tempfile `out`; argv `[cli_path,"exec","-s","read-only","--skip-git-repo-check","-C",tmpdir,"--color","never","-o",out]` + (`["--output-schema", schemafile]` if response_schema) + (`["-m",model]` if model) + `["-"]`; stdin = `f"{system_str}\n\n---\nRESPOND WITH TEXT ONLY, DO NOT USE TOOLS.\n\n{user_str}"`; run via `run_cli`; on success read `out` file → return its stripped contents; nonzero exit / empty out → `BackendError`. Cleanup tmpdir/out/schemafile in `finally`.

- [ ] **Step 1 (test):** in `test_cli_backends.py::test_codex_reads_output_file` — monkeypatch `run_cli` to (0,"transcript…","") AND pre-write the `out` path... since the runner is mocked, instead patch `run_cli` with a side_effect that writes "PONG" to the `-o` path parsed from argv, then returns (0,"",""). Assert `generate` returns "PONG". Add `test_codex_prompt_via_stdin` (assert the mocked run_cli received `stdin` containing the user text, and argv has no shell).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit.

---

### Task 9: router.py — Router + CircuitBreaker + get_router()

**Files:** Create `backend/agents/llm/router.py`.

**Interfaces produced:** `class CircuitBreaker` (open after N consecutive fails for cooldown s; `allow()`, `record_success()`, `record_failure()`); `class Router` — builds the backend registry from `settings` (openrouter only if key present; local only if `LLM_LOCAL_ENABLED`; claude/codex always, one instance each with per-task model chosen at call time via `CLAUDE_MODEL_BY_TASK`), per-backend `asyncio.Semaphore` + `CircuitBreaker` + timeout; `resolve(task, streaming) -> list[LLMBackend]` (map policy → constructed backends, drop missing/circuit-open/unhealthy/non-stream-when-streaming/over-budget; append local if enabled; empty → raise later); `async generate(messages, *, task, temperature, max_tokens, response_schema) -> str` (walk chain: `async with sem`, `wait_for(timeout)`, on error record failure + `log llm_fallback` + next; exhaust → `LLMAllBackendsFailed`); `async stream(...)`; `async startup()` (best-effort health probes, cache); `async aclose()`; `snapshot() -> dict`; module singleton `get_router()` / `reset_router()`. Budget: track estimated USD/day in-memory; when `OPENROUTER_DAILY_BUDGET_USD` exceeded, drop openrouter for the (in-memory) day.

- [ ] **Step 1 (tests):** `test_llm/test_router.py` (pure, backends mocked):
  - `resolve(SCANNER)` with openrouter present → `[openrouter]`; with key absent → `[]` then generate raises `LLMAllBackendsFailed`.
  - streaming filter: a task whose chain is `[claude_cli(supports_stream=False), openrouter]` resolved with `streaming=True` drops claude_cli.
  - circuit breaker: after `fail_threshold` failures `allow()` is False; after cooldown (inject a fake clock or call an internal reset) allow True.
  - fallback: first backend raises `BackendError`, second returns "ok" → `generate` returns "ok" and logs a fallback.
  - Use fake backends (simple objects implementing the ABC with configurable behavior); do NOT hit network/CLIs.
- [ ] **Step 2:** FAIL. **Step 3:** implement. Keep clock injectable (ctor arg `now=lambda: ...` defaulting to a monotonic counter you can override in tests — do NOT call `time.time()` directly in a way tests can't control; a simple `time.monotonic` wrapper the test can monkeypatch is fine). **Step 4:** PASS. **Step 5:** commit.

---

### Task 10: llm_provider.py facade — delegate to router

**Files:** Modify `backend/agents/llm_provider.py`.

**Interfaces produced (unchanged names):** `LLMProvider.generate(messages, temperature=None, max_tokens=None, *, task=None, response_schema=None) -> str`; `stream(..., *, task=None)`; NEW `generate_structured(messages, schema, *, task="strategic_decision") -> dict`. `get_llm_provider()`/`reset_llm_provider()`/`create_messages()`/`LLMConfig` names preserved.

- [ ] **Step 1 (test):** `test_llm/test_facade_compat.py`:
```python
from unittest.mock import AsyncMock, patch
import pytest
from langchain_core.messages import HumanMessage
from agents.llm_provider import get_llm_provider, reset_llm_provider

@pytest.mark.asyncio
async def test_generate_backcompat_positional_and_str(monkeypatch):
    reset_llm_provider()
    fake_router = AsyncMock()
    fake_router.generate = AsyncMock(return_value="RESULT")
    with patch("agents.llm_provider.get_router", return_value=fake_router):
        p = get_llm_provider()
        out = await p.generate([HumanMessage(content="x")], temperature=0.3)
        assert out == "RESULT"
        # unknown task coerces to GENERAL, does not raise
        assert await p.generate([HumanMessage(content="x")], task="bogus") == "RESULT"

@pytest.mark.asyncio
async def test_generate_structured_validates(monkeypatch):
    reset_llm_provider()
    fake_router = AsyncMock()
    fake_router.generate = AsyncMock(return_value='{"action":"BUY","confidence":0.7,"rationale":"r"}')
    with patch("agents.llm_provider.get_router", return_value=fake_router):
        d = await get_llm_provider().generate_structured([HumanMessage(content="x")], schema={"type":"object"})
        assert d["action"] == "BUY"
```
- [ ] **Step 2:** FAIL. **Step 3:** rewrite `generate`/`stream` to call `get_router().generate(...)`/`.stream(...)` with `task=coerce_task(task)`; remove the blanket `@retry` (router owns retry/fallback); add `generate_structured` (calls generate with response_schema=schema, `json.loads`, minimal validation of required keys, raise on parse fail). Keep `LLMConfig`, `create_messages`, singleton. **Step 4:** PASS + run `test_llm_provider.py` (existing) offline subset to confirm singleton/config tests still pass. **Step 5:** commit.

---

### Task 11: main.py lifespan + GET /api/llm/stats

**Files:** Modify `backend/app/main.py`.

- [ ] **Step 1 (test):** `test_llm/test_llm_stats_route.py` — using `TestClient(app)` (offline; lifespan not triggered by bare client construction) assert `GET /api/llm/stats` returns 200 and a dict with a `backends` key. (If TestClient triggers lifespan/network, instead assert the route exists in `app.routes`.)
- [ ] **Step 2:** FAIL. **Step 3:** in lifespan startup add (best-effort, wrapped in try/except): `await get_router().startup()`; in shutdown add `await get_router().aclose()`. Add a tiny router `GET /api/llm/stats` returning `get_router().snapshot()` (mount it in `_API_ROUTERS` or as a small inline route). Keep the existing LLM health_check call working (it now goes through the facade/router). **Step 4:** PASS. **Step 5:** commit.

---

### Task 12: Tag the scanner (biggest cost win)

**Files:** Modify `backend/services/background_scanner/scanner.py` (the two `llm.generate(messages)` calls ~:931 and ~:1009).

- [ ] **Step 1 (test):** `test_llm/test_scanner_task_tag.py` — `inspect.getsource(scanner)` asserts `task="scanner"` appears at least twice (characterization). (A behavioral test needs network; the source check + the router unit tests cover the routing.)
- [ ] **Step 2:** FAIL. **Step 3:** add `task="scanner"` kwarg to both `await llm.generate(messages, ...)` calls. Verify the surrounding `try/except` still degrades to `_run_quick_analysis` on `LLMAllBackendsFailed`. **Step 4:** PASS. **Step 5:** commit.

---

### Task 13: Integration smoke (opt-in, real CLIs) + docs

**Files:** Create `backend/tests/test_agents/test_llm/test_integration_cli.py` marked `@pytest.mark.slow` (skipped in CI).

- [ ] **Step 1:** write two `@pytest.mark.slow @pytest.mark.asyncio` tests that call the REAL `ClaudeCLIBackend.generate` and `CodexCLIBackend.generate` with a trivial prompt and assert non-empty output (reproduces the captured `.result` / `-o` round-trip). These are excluded from `-m "not slow"`.
- [ ] **Step 2:** run them ONCE manually (`pytest -m slow test_integration_cli.py`) to confirm the real round-trip; record the result. **Step 3:** commit.

---

## Final verification

- [ ] `pytest -m "not slow" --no-cov -o addopts="" tests/test_agents/test_llm/` all green.
- [ ] Facade back-compat: existing `tests/test_agents/test_llm_provider.py -m "not slow"` still passes.
- [ ] `import app.main` OK (cwd=backend); `GET /api/llm/stats` route present.
- [ ] With no OPENROUTER_API_KEY set and CLIs logged in: `resolve(GENERAL)` degrades sanely (openrouter dropped → claude_cli) — covered by router unit test.
- [ ] One manual `-m slow` integration run per CLI reproduces the verified round-trip.

## Self-Review notes
- Spec coverage: every spec §1-9 module maps to Tasks 1-13. Structured output (§4.1 DECISION_SCHEMA) = Tasks 2+10. Concurrency/CB/budget (§5) = Task 9. Secrets (§8) = Task 1. Migration (§9) scanner-first = Task 12.
- Deferred by design (not this phase): tagging strategic/risk/analyst call sites (Phase 1e per spec, gated on parser validation) — only scanner is tagged here; the rest stay GENERAL and are flipped in a follow-up after parser validation. Consuming structured LLM *decisions* is Phase 3.
