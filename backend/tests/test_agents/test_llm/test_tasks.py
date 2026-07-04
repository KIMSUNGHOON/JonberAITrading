"""Phase 1: task taxonomy, routing policy, decision schema."""
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


def test_decision_schema():
    assert DECISION_SCHEMA["type"] == "object"
    assert set(DECISION_SCHEMA["required"]) == {"action", "confidence", "rationale"}
    assert DECISION_SCHEMA["properties"]["action"]["enum"][0] == "BUY"
