"""Task taxonomy, backend routing policy, and the canonical decision schema.

Pure module: no I/O, no settings import. The Router reads `ROUTING_POLICY` and
`STRATEGIC_TASKS` and combines them with `app.config.settings` at runtime.
"""
from enum import Enum

import structlog

logger = structlog.get_logger()


class TaskType(str, Enum):
    """What an LLM call is for. Callers pass the string value as `task=`."""

    STRATEGIC_DECISION = "strategic_decision"
    RISK = "risk"
    TASK_DECOMPOSITION = "task_decomposition"
    TECHNICAL_ANALYSIS = "technical_analysis"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    GROUP_CHAT = "group_chat"
    SCANNER = "scanner"
    TRANSLATION = "translation"
    CHAT = "chat"
    UTILITY = "utility"
    GENERAL = "general"
    DISCOVERY = "discovery"


class BackendName(str, Enum):
    OPENROUTER = "openrouter"
    CLAUDE_CLI = "claude_cli"
    CODEX_CLI = "codex_cli"
    LOCAL = "local"


# Task -> ordered backend fallback chain (cloud-first; `local` is appended by the
# Router only when settings.LLM_LOCAL_ENABLED is true). SCANNER intentionally has
# NO CLI fallback (high volume; ~5s/CLI call would serialize catastrophically).
ROUTING_POLICY: dict[TaskType, list[BackendName]] = {
    TaskType.STRATEGIC_DECISION: [BackendName.CLAUDE_CLI, BackendName.OPENROUTER],
    TaskType.RISK: [BackendName.CLAUDE_CLI, BackendName.OPENROUTER],
    TaskType.TASK_DECOMPOSITION: [BackendName.CODEX_CLI, BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.UTILITY: [BackendName.CODEX_CLI, BackendName.OPENROUTER],
    TaskType.TECHNICAL_ANALYSIS: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.FUNDAMENTAL_ANALYSIS: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.SENTIMENT_ANALYSIS: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.GROUP_CHAT: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.SCANNER: [BackendName.OPENROUTER],
    TaskType.TRANSLATION: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    TaskType.CHAT: [BackendName.OPENROUTER],
    TaskType.GENERAL: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
    # Same routing as GENERAL -- discovery's LLM suitability review (DS-4,
    # services/discovery/ranker.py::llm_review_top) is not a strategic/
    # high-stakes call, it just lacked an explicit TaskType entry (fell
    # through coerce_task's unknown-task warning path -> GENERAL fallback,
    # ~25x/day log spam). No behavior change, only the warning goes away.
    TaskType.DISCOVERY: [BackendName.OPENROUTER, BackendName.CLAUDE_CLI],
}

# Highest-stakes tasks get the strongest Claude model (settings.CLAUDE_STRATEGIC_MODEL,
# default "opus"); everything else uses settings.CLAUDE_FALLBACK_MODEL ("sonnet").
STRATEGIC_TASKS: frozenset[TaskType] = frozenset(
    {TaskType.STRATEGIC_DECISION, TaskType.RISK}
)

# Convenience/default map (the Router prefers settings, but this documents intent).
CLAUDE_MODEL_BY_TASK: dict[TaskType, str] = {
    TaskType.STRATEGIC_DECISION: "opus",
    TaskType.RISK: "opus",
}


# Canonical structured-decision schema (used by generate_structured / --json-schema /
# --output-schema / response_format). Phase 3 consumes it; Phase 1 only plumbs it.
DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["BUY", "SELL", "HOLD", "ADD", "REDUCE", "WATCH", "AVOID"],
        },
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "bull_case": {"type": "array", "items": {"type": "string"}},
        "bear_case": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["action", "confidence", "rationale"],
}


def coerce_task(value) -> TaskType:
    """Coerce a task hint (None | str | TaskType) to a TaskType. Unknown -> GENERAL."""
    if value is None:
        return TaskType.GENERAL
    if isinstance(value, TaskType):
        return value
    try:
        return TaskType(value)
    except ValueError:
        logger.warning("unknown_llm_task_defaulting_to_general", task=str(value))
        return TaskType.GENERAL
