"""Phase 1: task taxonomy, routing policy, decision schema."""
import structlog.testing

from agents.llm.tasks import (
    TaskType, BackendName, ROUTING_POLICY, CLAUDE_MODEL_BY_TASK,
    coerce_task, DECISION_SCHEMA,
)


def test_routing_policy_shape():
    assert ROUTING_POLICY[TaskType.STRATEGIC_DECISION][0] == BackendName.CLAUDE_CLI
    assert ROUTING_POLICY[TaskType.RISK][0] == BackendName.CLAUDE_CLI
    assert ROUTING_POLICY[TaskType.SCANNER] == [BackendName.OPENROUTER]  # no CLI for high volume
    assert ROUTING_POLICY[TaskType.GENERAL][0] == BackendName.OPENROUTER  # cloud-first
    assert ROUTING_POLICY[TaskType.TASK_DECOMPOSITION][0] == BackendName.CODEX_CLI
    # discovery routes identically to GENERAL (no behavior change, just a
    # registered task -- see test_coerce_task_discovery_registered_no_warning)
    assert ROUTING_POLICY[TaskType.DISCOVERY] == ROUTING_POLICY[TaskType.GENERAL]
    # every task routes somewhere
    assert set(ROUTING_POLICY) == set(TaskType)
    assert all(len(v) >= 1 for v in ROUTING_POLICY.values())


def test_claude_model_by_task():
    assert CLAUDE_MODEL_BY_TASK[TaskType.STRATEGIC_DECISION] == "opus"
    assert CLAUDE_MODEL_BY_TASK[TaskType.RISK] == "opus"
    # non-critical tasks fall back to sonnet
    assert CLAUDE_MODEL_BY_TASK.get(TaskType.GENERAL, "sonnet") == "sonnet"


def test_coerce_task():
    assert coerce_task(None) == TaskType.GENERAL
    assert coerce_task("scanner") == TaskType.SCANNER
    assert coerce_task(TaskType.RISK) == TaskType.RISK
    assert coerce_task("not-a-real-task") == TaskType.GENERAL  # graceful, no raise


def test_coerce_task_discovery_registered_no_warning():
    """DS final-review fix: services/discovery/ranker.py::llm_review_top
    calls provider.generate(..., task="discovery") -- before TaskType.
    DISCOVERY existed this fell through coerce_task's except-branch
    (GENERAL fallback + a warning log, ~25x/day in production). It must
    now resolve directly, with no warning, and every OTHER task must
    still route exactly as before (no behavior change beyond the log)."""
    with structlog.testing.capture_logs() as logs:
        result = coerce_task("discovery")

    assert result == TaskType.DISCOVERY
    assert logs == []  # no unknown_llm_task_defaulting_to_general warning

    # existing routing untouched
    assert coerce_task("scanner") == TaskType.SCANNER
    assert coerce_task(None) == TaskType.GENERAL


def test_decision_schema():
    assert DECISION_SCHEMA["type"] == "object"
    assert set(DECISION_SCHEMA["required"]) == {"action", "confidence", "rationale"}
    assert DECISION_SCHEMA["properties"]["action"]["enum"][0] == "BUY"
