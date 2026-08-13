# Phase 0 — Clear the Runway: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore 3 silently-dead features, add a ~4-line consensus safety gate, delete 5,905 LOC of dead code, stand up a CI floor, dedup 3 shared helpers, and collapse the cosmetic v1/legacy route dual-mount — leaving the tree honest and guarded before the Phase-1 intelligence-layer router lands.

**Architecture:** Backend = Python 3.12 FastAPI + LangGraph. All changes are small, isolated, and each leaves the repo shippable. No LLM/router work here (that is Phase 1). Order: CI floor first (safety net) → dead-code purge → 3 quick-win fixes → consensus gate → helper dedup → dual-mount collapse.

**Tech Stack:** Python 3.12 (conda env `agentic-trading`), pytest + pytest-asyncio, FastAPI, langgraph, structlog, pydantic v2; frontend vitest (only referenced, not changed).

## Global Constraints

- **Conda env:** Run every `python`/`pytest` command inside the `agentic-trading` env: `conda activate agentic-trading` (interpreter `/Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python`). The bare system python lacks project deps.
- **CWD:** Run all backend commands from `/Users/sunghoonk/Workspaces/JonberAITrading/backend` unless a step says otherwise.
- **Circular-import gotcha:** Importing a graph module in isolation (`import agents.graph.coin_trading_graph`) raises a circular-import error. Always `import app.api.routes` FIRST in any standalone smoke script (app startup does this implicitly).
- **FROZEN — do NOT touch:** live trading (`KIWOOM_IS_MOCK=false`), the real order-execution path, HITL resume plumbing, or in-market verification. Those are Phase 5+ and frozen until the user explicitly asks.
- **No over-claiming:** The scanner fix restores page 1 (hundreds of stocks), NOT the full paginated universe (see Task 5). State this honestly in any commit/log.
- **Markers:** `pytest.ini` has `--strict-markers`; only use registered markers (`slow`, `integration`, `unit`).
- **Commits:** Follow repo convention (`fix:`/`feat:`/`refactor:`/`chore:`/`test:`). End each commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **KR stack is off-limits for dedup:** `agents/graph/kr_stock_nodes/helpers.py` has real Korean-language logic; never merge it into shared helpers (Task 7).

---

### Task 1: CI floor — anti-hang timeout + mark network tests + GitHub Actions

**Files:**
- Modify: `backend/pytest.ini`
- Modify: `backend/tests/test_agents/test_llm_provider.py` (mark 3 network-hitting tests `slow`)
- Modify: `environment.yml`, `backend/requirements.txt` (add `pytest-timeout`, `pytest-cov`)
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a `pytest -m "not slow"` invocation that runs offline and cannot hang (60s hard per-test cap). Later tasks rely on this as their regression gate.

**Why these 3 tests:** `test_llm_provider.py` `test_health_check_returns_dict` (:53), `test_health_check_status_values` (:64), and `test_generate_with_empty_messages` (:78) call `provider.health_check()` / `provider.generate([])`, which hit the configured LLM endpoint. `generate` is wrapped in `@retry(stop_after_attempt(3))` with a 300s timeout → up to ~900s hang when the server accepts but stalls. The other tests in that file (singleton/config/close) are offline and stay.

- [ ] **Step 1: Add test tooling to dependency files**

In `backend/requirements.txt`, add two lines (near the other test deps):
```
pytest-timeout>=2.3.0
pytest-cov>=5.0.0
```
In `environment.yml`, under the `pip:` list (where `aiosqlite>=0.20.0` lives at line 54), add:
```
      - pytest-timeout>=2.3.0
      - pytest-cov>=5.0.0
```

- [ ] **Step 2: Install into the active env**

Run: `conda activate agentic-trading && pip install "pytest-timeout>=2.3.0" "pytest-cov>=5.0.0"`
Expected: both install successfully; `pytest --help | grep -E "timeout|cov"` shows the new options.

- [ ] **Step 3: Configure pytest.ini — hard timeout + re-enable coverage (report-only)**

Edit `backend/pytest.ini`. Change the `addopts` block from:
```ini
addopts =
    -v
    --tb=short
    --strict-markers
    -ra
```
to:
```ini
addopts =
    -v
    --tb=short
    --strict-markers
    -ra
    --timeout=60
    --cov=app --cov=agents --cov=services --cov-report=term-missing
```
(`--timeout=60` kills any test running >60s; coverage is report-only — no `--cov-fail-under`, so it never fails the build.)

- [ ] **Step 4: Mark the 3 network-hitting tests `slow`**

In `backend/tests/test_agents/test_llm_provider.py`, add `@pytest.mark.slow` above each of the three async tests (keep the existing `@pytest.mark.asyncio`). Example for the first:
```python
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_health_check_returns_dict(self):
```
Apply the same `@pytest.mark.slow` line to `test_health_check_status_values` (:64) and `test_generate_with_empty_messages` (:78).

- [ ] **Step 5: Verify the offline suite skips them and cannot hang**

Run: `cd backend && pytest -m "not slow" tests/test_agents/test_llm_provider.py -v`
Expected: the 3 marked tests show as `deselected`; the singleton/config/close tests PASS; total wall-time is a few seconds (no 900s hang). `pytest -m "not slow" --collect-only -q` lists only the non-network tests.

- [ ] **Step 6: Create the GitHub Actions workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main, "**"]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run offline tests (no slow/network)
        run: pytest -m "not slow"

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install deps
        run: npm ci
      - name: Run unit tests
        run: npm run test:run
```

- [ ] **Step 7: Run the full offline suite once to find any other network-bound hangs**

Run: `cd backend && pytest -m "not slow"`
Expected: completes (no hang, thanks to `--timeout=60`) and prints a coverage summary. If any test times out or fails on network access, mark it `@pytest.mark.slow` too and note it in the commit body (iterative tightening is expected). Do NOT chase pre-existing unrelated failures beyond marking network hangs — record them for a later phase.

- [ ] **Step 8: Commit**

```bash
git add backend/pytest.ini backend/tests/test_agents/test_llm_provider.py \
        backend/requirements.txt environment.yml .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: add CI floor — pytest-timeout, mark live-LLM tests slow, GitHub Actions

- --timeout=60 hard per-test cap prevents the ~900s LLM-retry hang
- mark 3 network-hitting test_llm_provider tests @slow; CI runs -m "not slow"
- re-enable --cov as report-only; add minimal backend+frontend GH Actions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Delete 5,905 LOC of dead code + park `parallel_analysis`

**Files:**
- Delete: `backend/agents/graph/kr_stock_nodes_old.py` (1941), `backend/app/api/routes/kr_stocks_old.py` (1790), `backend/app/api/routes/coin_old.py` (1513), `backend/services/agent_chat/agents.py` (661, import-shadowed), `backend/app/api/routes/kr_stocks_new.py` (0)
- Delete (dir): `backend/agents/subagents/` (empty package)
- Modify: `backend/agents/graph/kr_stock_nodes/__init__.py` (remove `parallel_analysis` import at line 22 + `__all__` entry at line 68)
- KEEP untouched: `backend/agents/graph/sqlite_checkpointer.py` (earmarked for Phase 6), `backend/agents/graph/kr_stock_nodes/parallel_analysis.py` (Phase 4 reference)

**Interfaces:**
- Produces: a tree with no shadow/`*_old` trap files. `services.agent_chat.agents` still imports (resolves to the package `agents/`, which re-exports all 6 names).

- [ ] **Step 1: Guard check — prove zero live importers (test-first)**

Run:
```bash
cd backend
for m in kr_stock_nodes_old kr_stocks_old coin_old kr_stocks_new; do
  echo "== $m =="; grep -rn "$m" --include="*.py" . ;
done
grep -rn "import subagents\|agents.subagents" --include="*.py" .
```
Expected: every command prints nothing (no importers). If ANY import appears, STOP — that file is not dead; re-scope before deleting.

- [ ] **Step 2: Confirm the `agents.py` shadow and its 6 re-exported names**

Run:
```bash
cd backend
ls -la services/agent_chat/ | grep -E "agents(\.py|/|$)"
grep -rn "from services.agent_chat.agents import" --include="*.py" .
```
Expected: both `agents/` (dir) and `agents.py` (file) exist; the 3 importers (`chat_room.py:26`, `services/agent_chat/__init__.py:36`, `tests/.../test_agents.py:18`) request names re-exported by `services/agent_chat/agents/__init__.py` (BaseDiscussionAgent, TechnicalDiscussionAgent, FundamentalDiscussionAgent, SentimentDiscussionAgent, RiskDiscussionAgent, ModeratorAgent). The directory package wins in CPython, so deleting `agents.py` changes nothing.

- [ ] **Step 3: Delete the dead files and empty dir**

```bash
cd backend
git rm agents/graph/kr_stock_nodes_old.py \
       app/api/routes/kr_stocks_old.py \
       app/api/routes/coin_old.py \
       services/agent_chat/agents.py \
       app/api/routes/kr_stocks_new.py
git rm -r agents/subagents/
```
(Do NOT delete `app/api/schemas/kr_stocks.py` or `app/api/schemas/coin.py` — the live route packages depend on them.)

- [ ] **Step 4: Park `parallel_analysis` — edit `agents/graph/kr_stock_nodes/__init__.py`**

Remove the eager import at line 22:
```python
from .parallel_analysis import kr_stock_parallel_analysis_node
```
Remove its `__all__` entry (line 68), the string `"kr_stock_parallel_analysis_node",`. Leave the file `parallel_analysis.py` on disk untouched.

- [ ] **Step 5: Verify the app and packages still import cleanly**

```bash
cd backend
python -c "import app.main; print('app.main OK')"
python -c "from services.agent_chat.agents import BaseDiscussionAgent, ModeratorAgent; print('agents pkg OK')"
python -c "import agents.graph.kr_stock_nodes as n; print('parallel parked:', 'kr_stock_parallel_analysis_node' not in n.__all__)"
python -c "from agents.graph.sqlite_checkpointer import create_checkpointer; print('checkpointer kept')"
```
Expected: `app.main OK`, `agents pkg OK`, `parallel parked: True`, `checkpointer kept`. If `import app.main` fails, a deleted file was actually live — `git restore --staged --worktree <file>` and re-investigate.

- [ ] **Step 6: Run the guarded suites**

Run: `cd backend && pytest -m "not slow" tests/test_services/test_agent_chat/test_agents.py tests/test_agents/ -q`
Expected: `test_agents.py` passes (package satisfies the 6 imports); graph tests pass (parking `parallel_analysis` didn't break node wiring). Pre-existing unrelated failures: note but don't fix here.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: delete 5,905 LOC dead code; park parallel_analysis

Remove import-shadowed services/agent_chat/agents.py (661) and the stale
*_old.py monoliths (kr_stock_nodes_old 1941, kr_stocks_old 1790, coin_old
1513) + empty kr_stocks_new.py and agents/subagents/. Remove parallel_analysis
from kr_stock_nodes __all__ (never wired) but keep the file for Phase 4.
KEEP sqlite_checkpointer.py for Phase 6.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Quick-win (a) — restore coin analysis (dead import)

**Files:**
- Modify: `backend/app/api/routes/analysis_unified.py:85-95` (coin branch of `_run_analysis_task`)
- Test: `backend/tests/test_api/test_analysis_unified_coin.py` (create)

**Interfaces:**
- Consumes: `get_coin_trading_graph()` (no args) from `agents.graph.coin_trading_graph`; `create_coin_initial_state(market, korean_name, user_query)` from `agents.graph.coin_state`.

**Root cause:** line 86 imports `agents.graph.coin_graph` — a module that does not exist (real module: `coin_trading_graph`). The import is lazy inside a BackgroundTask, so it fails silently at runtime only for `market_type=="coin"`.

- [ ] **Step 1: Write the failing smoke test**

Create `backend/tests/test_api/test_analysis_unified_coin.py`:
```python
"""Regression: the coin branch of unified analysis must import a real module."""
import importlib
import pytest


def test_coin_branch_imports_real_graph_module():
    # app.api.routes must load first to resolve the graph package circular import
    import app.api.routes  # noqa: F401

    # The WRONG module the bug used must not exist...
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agents.graph.coin_graph")

    # ...and the REAL one must import and expose the callable.
    mod = importlib.import_module("agents.graph.coin_trading_graph")
    assert hasattr(mod, "get_coin_trading_graph")


def test_analysis_unified_source_uses_correct_module():
    import app.api.routes.analysis_unified as m
    src = __import__("inspect").getsource(m)
    assert "agents.graph.coin_graph import" not in src
    assert "agents.graph.coin_trading_graph import get_coin_trading_graph" in src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && pytest tests/test_api/test_analysis_unified_coin.py -v`
Expected: `test_analysis_unified_source_uses_correct_module` FAILS (source still contains `agents.graph.coin_graph import`).

- [ ] **Step 3: Fix the import (and align initial state with the working coin path)**

In `backend/app/api/routes/analysis_unified.py`, change the coin branch (lines 85-95) from:
```python
        elif market_type == "coin":
            from agents.graph.coin_graph import get_coin_trading_graph

            graph = get_coin_trading_graph()
            initial_state = {
                "market": ticker,
                "korean_name": name,
                "user_query": query or f"{ticker} 분석해주세요",
                "messages": [],
                "reasoning_log": [],
            }
```
to:
```python
        elif market_type == "coin":
            from agents.graph.coin_trading_graph import get_coin_trading_graph
            from agents.graph.coin_state import create_coin_initial_state

            graph = get_coin_trading_graph()
            initial_state = create_coin_initial_state(
                market=ticker,
                korean_name=name,
                user_query=query or f"{ticker} 분석해주세요",
            )
```
(The one-line module fix is the critical part; switching to the canonical `create_coin_initial_state` factory — the same one `app/api/routes/coin/analysis.py` uses — supplies the ~20 downstream state keys the hand-built dict omitted. Verify the factory signature at `agents/graph/coin_state.py:293` before editing; if it differs, match `coin/analysis.py`'s call exactly.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api/test_analysis_unified_coin.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/analysis_unified.py backend/tests/test_api/test_analysis_unified_coin.py
git commit -m "$(cat <<'EOF'
fix: restore coin analysis — correct dead import in unified analysis

analysis_unified.py imported the nonexistent agents.graph.coin_graph; use
coin_trading_graph and the canonical create_coin_initial_state factory so the
coin market path runs instead of silently ModuleNotFoundError-ing in the
background task.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Quick-win (b) — fix agent-chat session-detail 500 (recompute vote weights)

**Files:**
- Modify: `backend/app/api/routes/agent_chat.py` (add `_AGENT_WEIGHTS` near line 107; fix votes comprehension at 156-166)
- Test: `backend/tests/test_api/test_agent_chat_detail.py` (create)

**Root cause:** `_session_to_detail` reads `v.weight` and `v.weighted_score`, which are NOT fields on `AgentVote` (models.py:110-123) → `AttributeError` → uncaught 500 on any session that has votes. **Do NOT "drop" the fields** — the frontend requires them (`types/index.ts` types them as required `number`; `ChatSessionViewer.tsx` calls `vote.weighted_score.toFixed(2)`). Recompute from the domain weights.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api/test_agent_chat_detail.py`:
```python
"""Regression: session-detail must not 500 on sessions that have votes."""
from services.agent_chat.models import ChatSession, AgentVote, AgentType, VoteType
from app.api.routes.agent_chat import _session_to_detail


def test_session_to_detail_recomputes_vote_weight():
    s = ChatSession(ticker="005930", stock_name="Samsung")
    s.add_vote(AgentVote(agent_type=AgentType.TECHNICAL, vote=VoteType.BUY,
                         confidence=0.8, reasoning="uptrend"))
    detail = _session_to_detail(s)  # BEFORE fix: AttributeError
    vote = detail["votes"][0]
    assert vote["weight"] == 0.25
    assert vote["weighted_score"] == 0.2  # 0.25 * 0.8
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && pytest tests/test_api/test_agent_chat_detail.py -v`
Expected: FAILS with `AttributeError: 'AgentVote' object has no attribute 'weight'`.

- [ ] **Step 3: Add the weights constant**

In `backend/app/api/routes/agent_chat.py`, in the "Helper Functions" section just above `_session_to_summary` (~line 107), add:
```python
# Per-agent consensus weights (mirror of services.agent_chat.models.calculate_consensus)
_AGENT_WEIGHTS = {
    "technical": 0.25,
    "fundamental": 0.25,
    "sentiment": 0.20,
    "risk": 0.30,
    "moderator": 0.0,
}
```

- [ ] **Step 4: Recompute the two fields in the votes comprehension**

Replace the votes comprehension at `agent_chat.py:156-166`:
```python
        "votes": [
            {
                "agent_type": v.agent_type.value,
                "vote": v.vote.value,
                "confidence": v.confidence,
                "weight": v.weight,
                "weighted_score": v.weighted_score,
                "reasoning": v.reasoning,
            }
            for v in session.votes
        ],
```
with:
```python
        "votes": [
            {
                "agent_type": v.agent_type.value,
                "vote": v.vote.value,
                "confidence": v.confidence,
                "weight": _AGENT_WEIGHTS.get(v.agent_type.value, 0.25),
                "weighted_score": round(
                    _AGENT_WEIGHTS.get(v.agent_type.value, 0.25) * v.confidence, 4
                ),
                "reasoning": v.reasoning,
            }
            for v in session.votes
        ],
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api/test_agent_chat_detail.py -v`
Expected: PASS (`weight == 0.25`, `weighted_score == 0.2`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/agent_chat.py backend/tests/test_api/test_agent_chat_detail.py
git commit -m "$(cat <<'EOF'
fix: agent-chat session-detail 500 — recompute vote weight/weighted_score

AgentVote has no weight/weighted_score fields; _session_to_detail crashed on
any voted session. Recompute from the domain agent weights (frontend requires
both fields, so drop is not an option).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Quick-win (c) — scanner fetches real stocks, not 15 hardcoded

**Files:**
- Modify: `backend/services/kiwoom/client.py:1107-1119` (the `get_stock_list` pagination call)
- Test: `backend/tests/test_services/test_kiwoom/test_client_stocklist.py` (create)

**Root cause:** the call passes `extra_headers=` to `_request`, whose signature is `_request(self, api_id, endpoint, data=None, cont_yn="", next_key="")` — no `extra_headers` → `TypeError` on the first call → swallowed by the scanner's blanket `except Exception` → 15-stock fallback. `_request` already forwards `cont_yn`/`next_key` into the exact `cont-yn`/`next-key` headers.

**Honest scope:** this restores page 1 (hundreds of stocks). Full multi-page pagination needs a separate change (continuation values arrive in HTTP response headers but the loop reads them from the JSON body) — out of scope for this quick-win. Do not claim "full universe."

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_services/test_kiwoom/test_client_stocklist.py`:
```python
"""Regression: get_stock_list must not TypeError into the 15-stock fallback."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from services.kiwoom.client import KiwoomClient
from services.kiwoom.models import MarketType


def _client_with_fake_http(body):
    client = KiwoomClient(app_key="k", secret_key="s", is_mock=True)
    client.auth.get_token = AsyncMock(return_value="tok")
    client._rate_limiter = None
    client._cache = None

    class FakeResp:
        def json(self):
            return body

    captured = {}

    async def fake_post(url, json=None, headers=None):
        captured["headers"] = headers
        return FakeResp()

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=fake_post)
    client._get_client = AsyncMock(return_value=fake_http)
    return client, captured


@pytest.mark.asyncio
async def test_request_forwards_cont_yn_and_next_key():
    client, captured = _client_with_fake_http({"return_code": 0, "list": []})
    await client._request(api_id="ka10099", endpoint="/api/dostk/stkinfo",
                          data={"mrkt_tp": "0"}, cont_yn="Y", next_key="ABC")
    assert captured["headers"]["cont-yn"] == "Y"
    assert captured["headers"]["next-key"] == "ABC"


@pytest.mark.asyncio
async def test_get_stock_list_returns_real_items_not_fallback():
    client, _ = _client_with_fake_http({"return_code": 0, "list": [
        {"code": "005930", "name": "삼성전자", "marketName": "코스피"},
        {"code": "000660", "name": "SK하이닉스", "marketName": "코스피"},
    ]})
    items = await client.get_stock_list(MarketType.KOSPI)  # pre-fix: TypeError
    assert [i.code for i in items] == ["005930", "000660"]
```
(If the real field names on the list items differ — inspect `get_stock_list`'s parsing around client.py:1120-1150 — match them so the assertion reflects the actual model.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_services/test_kiwoom/test_client_stocklist.py -v`
Expected: `test_get_stock_list_returns_real_items_not_fallback` FAILS with `TypeError: _request() got an unexpected keyword argument 'extra_headers'`.

- [ ] **Step 3: Fix the call site**

In `backend/services/kiwoom/client.py`, replace lines 1107-1119:
```python
        while True:
            # 연속 조회 헤더 설정
            extra_headers = {}
            if cont_yn == "Y":
                extra_headers["cont-yn"] = cont_yn
                extra_headers["next-key"] = next_key

            response = await self._request(
                api_id="ka10099",
                endpoint="/api/dostk/stkinfo",
                data={"mrkt_tp": market_type.value},
                extra_headers=extra_headers if extra_headers else None,
            )
```
with:
```python
        while True:
            response = await self._request(
                api_id="ka10099",
                endpoint="/api/dostk/stkinfo",
                data={"mrkt_tp": market_type.value},
                cont_yn=cont_yn if cont_yn == "Y" else "",
                next_key=next_key if cont_yn == "Y" else "",
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_services/test_kiwoom/test_client_stocklist.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/kiwoom/client.py backend/tests/test_services/test_kiwoom/test_client_stocklist.py
git commit -m "$(cat <<'EOF'
fix: scanner fetches real stock list — remove invalid _request(extra_headers=)

get_stock_list passed extra_headers= (unsupported) -> TypeError -> silent
15-stock fallback. Use the cont_yn/next_key params _request already forwards to
the cont-yn/next-key headers. Restores page 1 (hundreds of stocks); full
multi-page pagination (body-vs-header continuation) is a separate follow-up.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Consensus safety gate — refuse to trade below threshold

**Files:**
- Modify: `backend/services/agent_chat/agents/moderator_agent.py` (`_parse_decision`, after line 326)
- Test: `backend/tests/test_services/test_agent_chat/test_moderator_gate.py` (create)

**Root cause:** `consensus_threshold` (0.75) has ZERO comparison sites — a 50/50 vote still trades. Edit the LIVE package moderator (`agents/moderator_agent.py`), NOT the shadowed `agents.py` (deleted in Task 2). The coordinator executes only on `decision.action` in {BUY, SELL, ADD, REDUCE}, so forcing HOLD/NO_ACTION blocks execution.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_services/test_agent_chat/test_moderator_gate.py`:
```python
"""A sub-threshold (50/50) consensus must be forced to HOLD/NO_ACTION."""
from unittest.mock import MagicMock, patch
import pytest
from services.agent_chat.agents.moderator_agent import ModeratorAgent
from services.agent_chat.models import (
    ChatSession, MarketContext, AgentVote, AgentType, VoteType, DecisionAction,
)


def _split_5050_session(has_position):
    ctx = MarketContext(ticker="005930", stock_name="삼성전자",
                        current_price=72500, price_change_pct=0.0,
                        has_position=has_position)
    s = ChatSession(ticker="005930", stock_name="삼성전자", context=ctx,
                    consensus_threshold=0.75)
    s.add_vote(AgentVote(agent_type=AgentType.TECHNICAL,   vote=VoteType.BUY,  confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.FUNDAMENTAL, vote=VoteType.BUY,  confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.SENTIMENT,   vote=VoteType.SELL, confidence=0.8, reasoning="x"))
    s.add_vote(AgentVote(agent_type=AgentType.RISK,        vote=VoteType.SELL, confidence=0.8, reasoning="x"))
    s.calculate_consensus()  # sets consensus_level = 0.5
    return s, ctx


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_5050_forces_no_action_when_flat(_llm):
    session, ctx = _split_5050_session(has_position=False)
    assert session.consensus_level == 0.5
    decision = ModeratorAgent()._parse_decision("최종 결정: 매수 (BUY)", session, ctx)
    assert decision.action == DecisionAction.NO_ACTION


@patch("services.agent_chat.agents.base_agent.get_llm_provider", return_value=MagicMock())
def test_5050_forces_hold_when_holding(_llm):
    session, ctx = _split_5050_session(has_position=True)
    decision = ModeratorAgent()._parse_decision("최종 결정: 매수", session, ctx)
    assert decision.action == DecisionAction.HOLD
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_services/test_agent_chat/test_moderator_gate.py -v`
Expected: both FAIL — `_parse_action` returns `BUY` from the "매수" text; the gate does not exist yet.

- [ ] **Step 3: Insert the gate in `_parse_decision`**

In `backend/services/agent_chat/agents/moderator_agent.py`, inside `_parse_decision`, immediately after `action = self._parse_action(response, context.has_position)` (line 326), insert:
```python

        # --- Consensus safety gate ---
        # If agents did not reach the required agreement level, refuse to trade.
        if session.consensus_level < session.consensus_threshold:
            action = DecisionAction.HOLD if context.has_position else DecisionAction.NO_ACTION
```
(No new imports: `DecisionAction` is already imported at line 18; `session`/`context` are params. The returned `TradeDecision.consensus_level` still carries the true 0.5, so the UI/Telegram show the real consensus next to the forced HOLD/NO_ACTION.)

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_services/test_agent_chat/test_moderator_gate.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent_chat/agents/moderator_agent.py backend/tests/test_services/test_agent_chat/test_moderator_gate.py
git commit -m "$(cat <<'EOF'
fix: enforce consensus gate — sub-threshold votes force HOLD/NO_ACTION

consensus_threshold (0.75) had zero comparison sites; a 50/50 vote still
traded. Gate the action in the live ModeratorAgent._parse_decision so
below-threshold consensus never reaches the coordinator's execute set.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Dedup 3 shared extractors (US + coin only)

**Files:**
- Create: `backend/agents/graph/shared_extractors.py`
- Modify: `backend/agents/graph/nodes.py` (remove local defs 815-847, add alias import)
- Modify: `backend/agents/graph/coin_nodes.py` (remove local defs 1082-1112, add alias import)
- Test: `backend/tests/test_agents/test_shared_extractors.py` (create)
- **DO NOT TOUCH:** `agents/graph/kr_stock_nodes/helpers.py` (Korean logic), `services/agent_chat/agents/base_agent.py:247` (unrelated method), `_signal_to_action` (enum-coupled — stays per-stack)

**Scope correction:** only `extract_key_factors`, `extract_bull_case`, `extract_bear_case` are byte-identical between US and coin. KR diverges (Korean keywords/bullets) and MUST keep its own. `_signal_to_action` is excluded (three separate enum classes; ~5 lines, not worth cross-module coupling).

**Interfaces:**
- Produces: `agents.graph.shared_extractors` with `extract_key_factors(response)->list[str]`, `extract_bull_case(response)->str`, `extract_bear_case(response)->str`.

- [ ] **Step 1: Write the failing test (behavior + KR non-regression guard)**

Create `backend/tests/test_agents/test_shared_extractors.py`:
```python
from agents.graph.shared_extractors import (
    extract_key_factors, extract_bull_case, extract_bear_case,
)
from agents.graph.kr_stock_nodes.helpers import (
    _extract_bull_case as kr_bull, _extract_key_factors as kr_factors,
)


def test_shared_extractors_behavior():
    r = "- alpha factor is strong\n2. beta momentum rising\nshort"
    assert extract_key_factors(r) == ["alpha factor is strong", "beta momentum rising"]
    assert extract_bull_case("X bull thesis here").startswith("bull thesis here")
    assert extract_bear_case("no keyword here") == ""


def test_kr_helpers_keep_korean_logic():
    # KR must still match Korean keywords / middle-dot bullets (NOT merged)
    assert kr_bull("종목 상승 기대") != ""
    assert kr_factors("· 한국형 불릿 항목입니다") == ["한국형 불릿 항목입니다"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_agents/test_shared_extractors.py -v`
Expected: FAILS at import (`No module named 'agents.graph.shared_extractors'`).

- [ ] **Step 3: Create the shared module**

Create `backend/agents/graph/shared_extractors.py`:
```python
"""Shared, market-agnostic LLM-response extraction helpers.

Used by the US (nodes.py) and coin (coin_nodes.py) stacks. The KR stack
(kr_stock_nodes/helpers.py) intentionally keeps its OWN Korean-language
variants and must NOT import from here.
"""


def extract_key_factors(response: str) -> list[str]:
    """Extract key factors (bullets / numbered items) from an LLM response."""
    factors = []
    lines = response.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith(("-", "•", "*")) or (line and line[0].isdigit() and "." in line[:3]):
            clean = line.lstrip("-•*0123456789. ").strip()
            if clean and len(clean) > 10:
                factors.append(clean[:200])
    return factors[:5]


def extract_bull_case(response: str) -> str:
    """Extract the first 500 chars starting at the word 'bull'."""
    lower = response.lower()
    if "bull" in lower:
        start = lower.find("bull")
        return response[start : start + 500]
    return ""


def extract_bear_case(response: str) -> str:
    """Extract the first 500 chars starting at the word 'bear'."""
    lower = response.lower()
    if "bear" in lower:
        start = lower.find("bear")
        return response[start : start + 500]
    return ""
```

- [ ] **Step 4: Switch US `nodes.py` to the shared module**

In `backend/agents/graph/nodes.py`, DELETE the three local defs (`_extract_key_factors`, `_extract_bull_case`, `_extract_bear_case`) at lines 815-847 (keep `_signal_to_action` at 806-813). Add near the top import block:
```python
from agents.graph.shared_extractors import (
    extract_key_factors as _extract_key_factors,
    extract_bull_case as _extract_bull_case,
    extract_bear_case as _extract_bear_case,
)
```
(Aliasing to the underscore names means the call sites at 171/245/310/379/464/465 need no change.)

- [ ] **Step 5: Switch coin `coin_nodes.py` to the shared module**

In `backend/agents/graph/coin_nodes.py`, DELETE the three local defs at lines 1082-1112 (keep `_signal_to_action` at 1073-1081). Add the same alias import near the top import block. Call sites at 191/269/331/399/521/522 need no change.

- [ ] **Step 6: Run tests + import integrity**

```bash
cd backend
pytest tests/test_agents/test_shared_extractors.py -v
python -c "import app.api.routes; import agents.graph.nodes, agents.graph.coin_nodes; print('imports OK')"
```
Expected: tests PASS (including KR non-regression); `imports OK` (no missing alias).

- [ ] **Step 7: Commit**

```bash
git add backend/agents/graph/shared_extractors.py backend/agents/graph/nodes.py \
        backend/agents/graph/coin_nodes.py backend/tests/test_agents/test_shared_extractors.py
git commit -m "$(cat <<'EOF'
refactor: extract shared US+coin LLM response helpers to shared_extractors

extract_key_factors/bull_case/bear_case were byte-identical in nodes.py and
coin_nodes.py. Move to agents/graph/shared_extractors.py and alias-import.
KR (kr_stock_nodes/helpers.py) keeps its Korean-language variants; _signal_to_action
stays per-stack (enum-coupled).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Collapse the cosmetic v1/legacy route dual-mount

**Files:**
- Modify: `backend/app/main.py` (replace `register_v1_routes` 191-263 + `register_legacy_routes` 266-343 + the two calls 346-350 with one table + loop; add `APIRouter` import at line 16)
- Test: `backend/tests/test_api/test_route_mounts.py` (create — characterization)

**Root cause:** two functions mount the SAME 14 routers at `/api/v1/*` and `/api/*`. The frontend uses `/api/*` exclusively (zero `/api/v1` references). This is a **behavior-preserving** collapse: keep BOTH prefixes, same order (v1 then legacy), same tag strings.

**Interfaces:**
- Produces: `register_api_routes(app)` mounting every router under both prefixes. Route set must be byte-identical to before.

- [ ] **Step 1: Snapshot the current route set (characterization test)**

Create `backend/tests/test_api/test_route_mounts.py`:
```python
"""The collapsed mount must expose the exact same route set as before."""
from app.main import app


def _mounted():
    return sorted(
        (r.path, tuple(sorted(getattr(r, "methods", None) or [])))
        for r in app.routes
    )


def test_both_prefixes_present():
    paths = {r.path for r in app.routes}
    assert any(p.startswith("/api/v1/") for p in paths)
    assert any(p.startswith("/api/") and not p.startswith("/api/v1/") for p in paths)


def test_v1_and_legacy_counts_match():
    paths = [r.path for r in app.routes]
    v1 = sum(p.startswith("/api/v1") for p in paths)
    legacy = sum(p.startswith("/api/") and not p.startswith("/api/v1") for p in paths)
    assert v1 == legacy and v1 > 0
```

- [ ] **Step 2: Capture the baseline route table (before refactor)**

Run:
```bash
cd backend
python -c "from app.main import app; import json; print(json.dumps(sorted((r.path, sorted(getattr(r,'methods',[]) or [])) for r in app.routes), default=str))" > /tmp/routes_before.json
pytest tests/test_api/test_route_mounts.py -v
```
Expected: the two tests PASS on current code (they characterize existing behavior). Keep `/tmp/routes_before.json`.

- [ ] **Step 3: Replace the two functions + calls with a table + loop**

In `backend/app/main.py`: at line 16 change `from fastapi import FastAPI` to `from fastapi import APIRouter, FastAPI`. Then DELETE `register_v1_routes` (191-263), `register_legacy_routes` (266-343), and the two calls (346-350), replacing all of it with:
```python
# =============================================================================
# API Routes — every router mounts under BOTH the versioned (/api/v1/*) and
# legacy (/api/*) prefixes. The frontend depends on the legacy /api/* prefix
# (see frontend/src/api/client.ts); keep both until the frontend migrates.
# =============================================================================

# (router, sub-path, tag-name). Empty sub-path => router carries its own
# internal prefix (e.g. indicators -> /indicators, agent_chat -> /agent-chat).
_API_ROUTERS: list[tuple[APIRouter, str, str]] = [
    (analysis_unified.router, "unified-analysis", "Unified Analysis"),
    (analysis.router, "analysis", "Analysis"),
    (approval.router, "approval", "Approval"),
    (auth.router, "auth", "Authentication"),
    (coin.router, "coin", "Coin"),
    (kr_stocks.router, "kr_stocks", "Korean Stocks"),
    (chat.router, "chat", "Chat"),
    (indicators.router, "", "Indicators"),
    (settings_routes.router, "settings", "Settings"),
    (news.router, "", "News"),
    (trading.router, "", "Trading"),
    (scanner.router, "", "Scanner"),
    (holidays.router, "", "Holidays"),
    (agent_chat.router, "", "Agent Chat"),
]


def register_api_routes(app: FastAPI) -> None:
    """Mount every router under both the /api/v1 and legacy /api prefixes."""
    for base, label in (("/api/v1", "v1"), ("/api", "Legacy")):
        for router, subpath, name in _API_ROUTERS:
            prefix = f"{base}/{subpath}" if subpath else base
            app.include_router(router, prefix=prefix, tags=[f"{label} - {name}"])


register_api_routes(app)
```
(Leave the `/ws` websocket mount that follows untouched. Confirm the 14 routers/sub-paths against the current file before saving — the sub-path is empty exactly for indicators, news, trading, scanner, holidays, agent_chat.)

- [ ] **Step 4: Verify the route set is byte-identical**

Run:
```bash
cd backend
python -c "from app.main import app; import json; print(json.dumps(sorted((r.path, sorted(getattr(r,'methods',[]) or [])) for r in app.routes), default=str))" > /tmp/routes_after.json
diff /tmp/routes_before.json /tmp/routes_after.json && echo "IDENTICAL ROUTES"
pytest tests/test_api/test_route_mounts.py -v
```
Expected: empty diff → `IDENTICAL ROUTES`; both characterization tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_api/test_route_mounts.py
git commit -m "$(cat <<'EOF'
refactor: collapse v1/legacy route dual-mount into one table + loop

register_v1_routes + register_legacy_routes mounted the same 14 routers twice.
Replace ~160 lines with a single _API_ROUTERS table and register_api_routes
loop; behavior-preserving (both /api/v1 and /api prefixes kept — the frontend
uses /api). Route set verified byte-identical.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification (after all tasks)

- [ ] **Full offline suite green:** `cd backend && pytest -m "not slow"` completes with no hang and the new tests passing.
- [ ] **Tree cleaned:** `git log --oneline` shows the 8 commits; `wc -l` on backend is ~5,905 LOC lighter; no `*_old.py` / shadow `agents.py` remain.
- [ ] **Features restored (manual, needs running server + env):** coin unified analysis runs; `GET /api/agent-chat/sessions/{id}` returns 200 on a voted session; scanner logs more than 15 stocks; a 50/50 chat vote yields HOLD/NO_ACTION.
- [ ] **Exit criteria met** per roadmap Phase 0: features 200, sub-threshold vote no longer trades, ~5.9k LOC removed, green CI, no shadow/`*_old` files.

## Self-Review notes (addressed)

- **Spec coverage:** all 7 Phase-0 roadmap items map to Tasks 1-8 (CI floor=1, dead code=2, quick-wins a/b/c=3/4/5, consensus gate=6, helper dedup=7, dual-mount=8). The 2 single-site execution fixes were explicitly deferred to Phase 5 by user decision.
- **Corrections baked in:** dead-code LOC = 5,905 (not 6,354); agent-chat = recompute (not drop); helper dedup = 3 extractors × US+coin only (KR excluded); scanner = page-1 only (no full-universe claim); dual-mount = keep both prefixes (frontend uses `/api`).
- **Type consistency:** shared helper names (`extract_key_factors`/`extract_bull_case`/`extract_bear_case`) are aliased to the underscore call-site names; `_AGENT_WEIGHTS` keys match `AgentType(...).value`; `register_api_routes`/`_API_ROUTERS` names consistent.
