"""
Task Decomposition Tool (DeepAgents Pattern)

Breaks down analysis tasks into subtasks for subagent delegation.
Enables dynamic task planning based on user queries.
"""

import json
from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from agents.graph.state import SubTask
from agents.llm_provider import get_llm_provider

logger = structlog.get_logger()

# Default task templates for common analysis scenarios
DEFAULT_ANALYSIS_TASKS = [
    SubTask(
        task="Analyze technical indicators and price patterns",
        assigned_to="technical_analyst",
        priority=1,
    ),
    SubTask(
        task="Review fundamental metrics and valuation",
        assigned_to="fundamental_analyst",
        priority=2,
    ),
    SubTask(
        task="Assess market sentiment from news and social media",
        assigned_to="sentiment_analyst",
        priority=3,
    ),
    SubTask(
        task="Evaluate risk factors and position sizing",
        assigned_to="risk_assessor",
        priority=4,
    ),
]

TASK_DECOMPOSITION_PROMPT = """You are a task planning agent for a trading analysis system.

Break down the trading analysis request into specific subtasks that can be delegated to specialist agents.

Available specialist agents:
1. technical_analyst: Analyzes price patterns, indicators (RSI, MACD, Moving Averages), chart patterns, support/resistance levels, volume analysis
2. fundamental_analyst: Analyzes financials, valuations (P/E, P/B), revenue growth, profit margins, balance sheet, competitive position
3. sentiment_analyst: Analyzes news sentiment, social media buzz, analyst ratings, insider trading, institutional flows
4. risk_assessor: Evaluates portfolio risk, position sizing, stop-loss levels, correlation risk, max drawdown scenarios

Create 3-6 focused tasks. Each task should be specific and actionable.

Output format (JSON array):
[
    {{"task": "specific task description", "assigned_to": "agent_name", "priority": 1}},
    {{"task": "another task", "assigned_to": "agent_name", "priority": 2}},
    ...
]

Priority: 1 = highest (do first), 5 = lowest

Only output the JSON array, no other text."""


async def decompose_task(
    ticker: str,
    query: str,
    use_llm: bool = True,
) -> list[SubTask]:
    """
    Decompose a trading analysis task into subtasks.

    Args:
        ticker: Stock ticker symbol
        query: User's analysis request
        use_llm: If True, use LLM for dynamic decomposition.
                 If False, use default templates.

    Returns:
        List of SubTask objects for subagent execution
    """
    if not use_llm:
        return _get_default_tasks(ticker)

    try:
        llm = get_llm_provider()

        messages = [
            SystemMessage(content=TASK_DECOMPOSITION_PROMPT),
            HumanMessage(content=f"Ticker: {ticker}\nAnalysis Request: {query}"),
        ]

        response = await llm.generate(messages, temperature=0.3)

        # Parse JSON response
        tasks = _parse_tasks_response(response, ticker)

        if tasks:
            logger.info(
                "task_decomposition_success",
                ticker=ticker,
                task_count=len(tasks),
            )
            return tasks

    except Exception as e:
        logger.error(
            "task_decomposition_failed",
            ticker=ticker,
            error=str(e),
        )

    # Fallback to defaults
    return _get_default_tasks(ticker)


def _parse_tasks_response(response: str, ticker: str) -> list[SubTask]:
    """Parse LLM response into SubTask objects."""
    try:
        # Try to extract JSON from response
        # Handle cases where LLM adds extra text
        response = response.strip()

        # Find JSON array in response
        start = response.find("[")
        end = response.rfind("]") + 1

        if start == -1 or end <= start:
            return []

        json_str = response[start:end]
        tasks_data = json.loads(json_str)

        # Validate and convert to SubTask objects
        valid_agents = {
            "technical_analyst",
            "fundamental_analyst",
            "sentiment_analyst",
            "risk_assessor",
        }

        tasks = []
        for item in tasks_data:
            if not isinstance(item, dict):
                continue

            assigned_to = item.get("assigned_to", "").lower()
            if assigned_to not in valid_agents:
                continue

            task = SubTask(
                task=str(item.get("task", "")),
                assigned_to=assigned_to,
                priority=min(max(int(item.get("priority", 1)), 1), 5),
                status="pending",
            )
            tasks.append(task)

        # Sort by priority
        tasks.sort(key=lambda t: t.priority)
        return tasks

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "task_parse_failed",
            error=str(e),
            response_preview=response[:200],
        )
        return []


def _get_default_tasks(ticker: str) -> list[SubTask]:
    """Get default analysis tasks for a ticker."""
    return [
        SubTask(
            task=f"Analyze technical indicators and price patterns for {ticker}",
            assigned_to="technical_analyst",
            priority=1,
        ),
        SubTask(
            task=f"Review fundamental metrics and valuation for {ticker}",
            assigned_to="fundamental_analyst",
            priority=2,
        ),
        SubTask(
            task=f"Assess market sentiment and news for {ticker}",
            assigned_to="sentiment_analyst",
            priority=3,
        ),
        SubTask(
            task=f"Evaluate risk factors and recommend position sizing for {ticker}",
            assigned_to="risk_assessor",
            priority=4,
        ),
    ]


# -------------------------------------------
# Task Management Helpers
# -------------------------------------------


def update_task_status(
    tasks: list[SubTask],
    agent_type: str,
    new_status: str,
    result: Optional[str] = None,
) -> list[SubTask]:
    """Update status of tasks assigned to a specific agent."""
    updated = []
    for task in tasks:
        if task.assigned_to == agent_type:
            task.status = new_status
            if result:
                task.result = result
        updated.append(task)
    return updated


def get_pending_tasks(tasks: list[SubTask]) -> list[SubTask]:
    """Get all pending tasks sorted by priority."""
    pending = [t for t in tasks if t.status == "pending"]
    return sorted(pending, key=lambda t: t.priority)


def get_next_task(tasks: list[SubTask]) -> Optional[SubTask]:
    """Get the highest priority pending task."""
    pending = get_pending_tasks(tasks)
    return pending[0] if pending else None


def all_tasks_complete(tasks: list[SubTask]) -> bool:
    """Check if all tasks are completed or failed."""
    return all(t.status in ("completed", "failed") for t in tasks)


def format_tasks_for_log(tasks: list[SubTask]) -> str:
    """Format tasks for reasoning log display."""
    lines = ["Task Breakdown:"]
    for i, task in enumerate(tasks, 1):
        status_icon = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "failed": "❌",
        }.get(task.status, "❓")
        lines.append(f"  {i}. [{status_icon}] {task.task}")
        lines.append(f"      → Assigned to: {task.assigned_to}")
    return "\n".join(lines)
