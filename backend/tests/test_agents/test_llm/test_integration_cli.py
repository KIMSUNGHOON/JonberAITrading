"""Phase 1: opt-in integration smoke against the REAL claude/codex CLIs.

Marked `slow` -> excluded from CI (`pytest -m "not slow"`). Run manually:
    pytest -m slow tests/test_agents/test_llm/test_integration_cli.py
Reproduces the verified round-trip (claude .result / codex -o file).
"""
import pytest
from langchain_core.messages import SystemMessage, HumanMessage

from agents.llm.backends.claude_cli import ClaudeCLIBackend
from agents.llm.backends.codex_cli import CodexCLIBackend

_MSGS = [
    SystemMessage(content="You are a terse echo bot."),
    HumanMessage(content="Reply with exactly one word: PONG"),
]


@pytest.mark.slow
@pytest.mark.asyncio
async def test_claude_cli_real_roundtrip():
    out = await ClaudeCLIBackend(model="haiku", timeout=60).generate(_MSGS)
    assert out.strip(), "claude CLI returned empty output"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_codex_cli_real_roundtrip():
    out = await CodexCLIBackend(timeout=90).generate(_MSGS)
    assert out.strip(), "codex CLI returned empty output"
