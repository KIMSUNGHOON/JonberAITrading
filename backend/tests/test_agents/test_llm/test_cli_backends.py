"""Phase 1: Claude + Codex CLI backends (parsing + argv-safety, all mocked)."""
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import SystemMessage, HumanMessage

from agents.llm.backends.claude_cli import ClaudeCLIBackend
from agents.llm.backends.codex_cli import CodexCLIBackend
from agents.llm.backends.base import BackendError


# ---------- Claude ----------

@pytest.mark.asyncio
async def test_claude_parses_success_envelope(monkeypatch):
    b = ClaudeCLIBackend(model="haiku", timeout=30)
    env = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "PONG"})
    monkeypatch.setattr("agents.llm.backends.claude_cli.run_cli", AsyncMock(return_value=(0, env, "")))
    out = await b.generate([SystemMessage(content="S"), HumanMessage(content="hi")])
    assert out == "PONG"


@pytest.mark.asyncio
async def test_claude_raises_on_is_error(monkeypatch):
    b = ClaudeCLIBackend()
    env = json.dumps({"subtype": "error", "is_error": True, "result": "boom"})
    monkeypatch.setattr("agents.llm.backends.claude_cli.run_cli", AsyncMock(return_value=(0, env, "")))
    with pytest.raises(BackendError):
        await b.generate([HumanMessage(content="hi")])


@pytest.mark.asyncio
async def test_claude_argv_disables_tools_and_no_shell(monkeypatch):
    b = ClaudeCLIBackend(model="opus")
    captured = {}

    async def fake(argv, *, stdin, timeout, cwd):
        captured["argv"] = argv
        return (0, json.dumps({"subtype": "success", "is_error": False, "result": "ok"}), "")

    monkeypatch.setattr("agents.llm.backends.claude_cli.run_cli", fake)
    await b.generate([HumanMessage(content="market $(rm -rf /) text")])
    argv = captured["argv"]
    i = argv.index("--tools")
    assert argv[i + 1] == ""  # tools disabled
    assert argv[argv.index("--model") + 1] == "opus"
    # arbitrary text is a single discrete argv element (exec, never shell)
    assert "market $(rm -rf /) text" in argv[-1]


# ---------- Codex ----------

@pytest.mark.asyncio
async def test_codex_reads_output_file(monkeypatch):
    b = CodexCLIBackend(timeout=30)

    async def fake(argv, *, stdin, timeout, cwd):
        # emulate codex writing the final message to the -o file
        out_path = argv[argv.index("-o") + 1]
        with open(out_path, "w") as f:
            f.write("PONG\n")
        return (0, "full transcript noise", "")

    monkeypatch.setattr("agents.llm.backends.codex_cli.run_cli", fake)
    out = await b.generate([SystemMessage(content="S"), HumanMessage(content="hi")])
    assert out == "PONG"


@pytest.mark.asyncio
async def test_codex_prompt_via_stdin_not_argv(monkeypatch):
    b = CodexCLIBackend()
    captured = {}

    async def fake(argv, *, stdin, timeout, cwd):
        captured["argv"] = argv
        captured["stdin"] = stdin
        out_path = argv[argv.index("-o") + 1]
        with open(out_path, "w") as f:
            f.write("ok")
        return (0, "", "")

    monkeypatch.setattr("agents.llm.backends.codex_cli.run_cli", fake)
    await b.generate([HumanMessage(content="danger $(whoami)")])
    # prompt goes via stdin, never as an argv element
    assert "danger $(whoami)" in captured["stdin"]
    assert all("danger" not in a for a in captured["argv"])
    assert "-s" in captured["argv"] and captured["argv"][captured["argv"].index("-s") + 1] == "read-only"


# ---------- missing-binary -> BackendAuthError (so the router falls through) ----------

@pytest.mark.asyncio
async def test_claude_missing_binary_maps_to_auth_error(monkeypatch):
    from agents.llm.backends.base import BackendAuthError

    async def boom(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'claude'")

    monkeypatch.setattr("agents.llm.backends.claude_cli.run_cli", boom)
    with pytest.raises(BackendAuthError):
        await ClaudeCLIBackend().generate([HumanMessage(content="hi")])


@pytest.mark.asyncio
async def test_codex_missing_binary_maps_to_auth_error(monkeypatch):
    from agents.llm.backends.base import BackendAuthError

    async def boom(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'codex'")

    monkeypatch.setattr("agents.llm.backends.codex_cli.run_cli", boom)
    with pytest.raises(BackendAuthError):
        await CodexCLIBackend().generate([HumanMessage(content="hi")])


@pytest.mark.asyncio
async def test_claude_non_object_json_is_backend_error(monkeypatch):
    b = ClaudeCLIBackend()
    monkeypatch.setattr("agents.llm.backends.claude_cli.run_cli", AsyncMock(return_value=(0, '"just a string"', "")))
    with pytest.raises(BackendError):
        await b.generate([HumanMessage(content="hi")])
