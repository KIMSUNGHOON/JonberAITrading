"""Phase 1: run_cli — the sole subprocess chokepoint (argv-safe, timeout-killing)."""
import pytest

from agents.llm.subprocess_runner import run_cli


@pytest.mark.asyncio
async def test_run_cli_passes_stdin_and_returns_output():
    rc, out, err = await run_cli(["cat"], stdin="hello", timeout=10, cwd="/tmp")
    assert rc == 0
    assert out.strip() == "hello"


@pytest.mark.asyncio
async def test_run_cli_argv_is_not_shell():
    # A shell would expand $(...); exec must pass it literally.
    rc, out, err = await run_cli(["printf", "%s", "$(whoami)"], stdin=None, timeout=10, cwd="/tmp")
    assert out == "$(whoami)"


@pytest.mark.asyncio
async def test_run_cli_timeout_kills():
    with pytest.raises(TimeoutError):
        await run_cli(["sleep", "5"], stdin=None, timeout=0.3, cwd="/tmp")
