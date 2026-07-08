# Agent Group-Chat — Structured Vote Parsing — Design

> Restructure roadmap Phase 3 follow-on (the group-chat half). The consensus **gate** is already enforced (`moderator_agent.py:328-331` + `test_moderator_gate.py`, added in Phase 0). This spec replaces the group-chat analyst agents' **regex vote parsing** with structured LLM output (`generate_structured` + a vote schema) — the same pattern just applied to the strategic decision nodes — eliminating the brittle silent-`ABSTAIN` fallthrough. Live trading stays FROZEN.

## The problem today

Each analyst agent (`technical`/`fundamental`/`sentiment`/`risk`) votes by calling `self._call_llm(...)` → free-text Korean → **regex/keyword parsing** (`base_agent._parse_vote:229`, `_parse_confidence:205`, `_extract_key_factors:247`). `_parse_vote` does substring keyword matching and **falls through to `VoteType.ABSTAIN`** when no keyword matches — so a perfectly reasonable vote phrased unexpectedly is silently dropped to ABSTAIN, corrupting the weighted consensus. `_parse_confidence` guesses from `강력/약한` words when no `NN%` is present. Brittle and lossy on the happy path.

Infrastructure is ready: `self.llm = get_llm_provider()` (`base_agent.py:40`) exposes `generate_structured(messages, schema, *, task) -> dict` (raises `ValueError` on parse/missing-keys); `TaskType.GROUP_CHAT` / `TaskType.RISK` exist for routing.

## Approach

**Structured vote authoritative, regex fallback. Mirror Phase 3's `decide_action`.** Each agent calls `generate_structured` with a vote schema; on success it builds the `AgentVote` from the validated structured object (no more silent ABSTAIN). On failure (`ValueError`) it falls back to the **existing** regex path — so robustness is preserved and the change is strictly additive (worst case == today). The regex parsers are kept as the fallback, not deleted.

## Design

### 1. Vote schemas — new `services/agent_chat/vote_schema.py`

`VoteType` values are **lowercase** (`strong_buy/buy/hold/sell/strong_sell/abstain`) — the schema enum and the prompt use lowercase, and the mapping normalizes with `.lower()`.

```python
VOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vote": {"type": "string",
                 "enum": ["strong_buy", "buy", "hold", "sell", "strong_sell", "abstain"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vote", "confidence"],
}

# Risk agent adds its position/stop/take suggestions.
RISK_VOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        **VOTE_SCHEMA["properties"],
        "suggested_position_pct": {"type": "number"},
        "suggested_stop_loss_pct": {"type": "number"},
        "suggested_take_profit_pct": {"type": "number"},
    },
    "required": ["vote", "confidence"],
}
```

### 2. Orchestrator — `base_agent._structured_vote`

A thin shared wrapper (dependency-light — uses `self.llm`, no new imports beyond the schema/task):

```python
async def _structured_vote(self, messages, *, schema, task) -> dict | None:
    """Return the validated structured vote dict, or None on any failure
    (the caller then uses the regex fallback path)."""
    try:
        return await self.llm.generate_structured(messages, schema, task=task)
    except (ValueError, KeyError) as e:
        logger.warning("structured_vote_failed", agent=self.agent_type.value, error=str(e))
        return None
```

### 3. Analyst agents' `vote()` (technical / fundamental / sentiment)

Each agent's `vote()` builds its prompt as today, then:

```python
messages = [SystemMessage(content=self.system_prompt), HumanMessage(content=prompt)]
data = await self._structured_vote(messages, schema=VOTE_SCHEMA, task=TaskType.GROUP_CHAT)
if data is not None:
    try:
        return AgentVote(
            agent_type=self.agent_type,
            vote=VoteType(str(data["vote"]).strip().lower()),
            confidence=float(data["confidence"]),
            reasoning=data.get("reasoning") or "",
            key_factors=data.get("key_factors") or [],
        )
    except (ValueError, KeyError):
        pass  # malformed structured payload -> fall through to the regex path
# Fallback: existing regex path (unchanged) — no silent ABSTAIN unless the LLM
# both fails structured output AND matches no keyword.
response = await self._call_llm(self.system_prompt, prompt)
return AgentVote(
    agent_type=self.agent_type,
    vote=self._parse_vote(response),
    confidence=self._parse_confidence(response),
    reasoning=response,
    key_factors=self._extract_key_factors(response),
)
```

The `AgentVote` construction sits inside a `try`: `VoteType(...lower())` maps the lowercase enum value back to the enum, and an out-of-enum value (or a bad `confidence`) raises `ValueError`/`KeyError` → fall through to the regex path. So the structured path is used only when it produces a fully valid vote; otherwise the existing behavior applies. (`_structured_vote` itself does not validate the enum — the `vote()` construction is the single validation point.)

### 4. Risk agent's `vote()`

Uses `RISK_VOTE_SCHEMA` + `task=TaskType.RISK`. On structured success, map the vote/confidence/reasoning/key_factors AND the three risk fields (`suggested_position_pct`/`stop_loss_pct`/`take_profit_pct`) from the dict, falling back **per-field** to the existing `_calculate_*(risk_level)` when the structured field is absent (preserving today's `_parse_* or _calculate_*` robustness). On structured failure, the existing full regex path.

### 5. Vote prompts

Each agent's `vote_prompt_template` gets a concise structured-JSON instruction: "Return your vote as JSON with `vote` (one of strong_buy/buy/hold/sell/strong_sell/abstain), `confidence` (0.0-1.0), `reasoning`, `key_factors` (array)." The risk prompt additionally requests `suggested_position_pct`/`suggested_stop_loss_pct`/`suggested_take_profit_pct`. Keep each prompt's existing analysis guidance (Korean).

## Out of scope (YAGNI — deferred)

- Moderator `_parse_action` (its consensus gate is already enforced + tested; a separate structured pass is a later item).
- Deleting the regex parsers (kept as the fallback).
- Consensus math / weighting changes; HITL routing; coordinator auto-start; any live-execution change.
- The `analyze()` (discussion) messages — only the final `vote()` is structured here.

## Testing / gates

- Run from `backend/`: `/Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python -m pytest <files> --no-cov -o addopts="" -q` FOREGROUND.
- `test_structured_vote.py`: `_structured_vote` returns the dict on a mocked `generate_structured`; returns `None` when it raises `ValueError`.
- Per-agent vote tests (mock the provider): (a) structured success → `AgentVote` carries the structured vote/confidence/factors (and, for risk, the risk fields); (b) structured failure (`ValueError`) → regex fallback path still produces a vote (no crash); (c) **no silent ABSTAIN on structured success** (a valid structured "buy" yields `VoteType.BUY`, never ABSTAIN).
- Async tests: `asyncio_mode = auto` (no decorator). No live LLM call in tests.
- No pre-existing passing test regresses (esp. `test_moderator_gate.py`, `test_agents.py`).

## Files

- **Create**: `services/agent_chat/vote_schema.py`; `tests/test_services/test_agent_chat/test_structured_vote.py`.
- **Modify**: `services/agent_chat/agents/base_agent.py` (`_structured_vote` + imports); `agents/technical_agent.py`, `agents/fundamental_agent.py`, `agents/sentiment_agent.py` (analyst `vote()` + prompt); `agents/risk_agent.py` (risk `vote()` + prompt).

## SDD task breakdown (3 tasks)

- **T1** — `vote_schema.py` (`VOTE_SCHEMA`, `RISK_VOTE_SCHEMA`) + `base_agent._structured_vote` orchestrator + `test_structured_vote.py` (dict on success, None on `ValueError`).
- **T2** — the 3 analyst agents (`technical`/`fundamental`/`sentiment`): `vote()` → structured-with-regex-fallback + each `vote_prompt_template` structured-JSON instruction + a representative per-agent vote test (structured success + fallback + no-silent-ABSTAIN).
- **T3** — `risk_agent`: `vote()` → `RISK_VOTE_SCHEMA` structured (incl. the 3 risk fields, per-field `_calculate_*` fallback) + risk vote prompt + risk vote test.
