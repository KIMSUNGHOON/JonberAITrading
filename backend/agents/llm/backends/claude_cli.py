"""Claude Code CLI backend (keyless — Max subscription OAuth).

Runs `claude -p --output-format json` constrained to act as a model: tools
disabled, MCP ignored, in a throwaway cwd so the project CLAUDE.md / git never
leak. Verified envelope (2026-07-05): stdout is one JSON object with
subtype=="success", is_error, and result (the text).
"""
import json
import shutil
import tempfile
from typing import Optional

import structlog
from langchain_core.messages import BaseMessage

from agents.llm.backends.base import (
    BackendAuthError, BackendError, BackendTransientError, LLMBackend,
)
from agents.llm.messages import flatten_messages
from agents.llm.subprocess_runner import run_cli
from agents.llm.tasks import BackendName

logger = structlog.get_logger()

_RATE_MARKERS = ("rate limit", "overloaded", "429", "usage limit")
_AUTH_MARKERS = ("logged out", "not authenticated", "unauthorized", "please run /login", "invalid api key")


class ClaudeCLIBackend(LLMBackend):
    name = BackendName.CLAUDE_CLI
    supports_stream = False
    supports_schema = True

    def __init__(self, cli_path: str = "claude", model: str = "sonnet", timeout: int = 180):
        self.cli_path = cli_path
        self.model = model
        self.timeout = timeout

    def _classify(self, msg: str, stderr: str = "") -> BackendError:
        low = f"{msg} {stderr}".lower()
        if any(m in low for m in _RATE_MARKERS):
            return BackendTransientError(msg)
        if any(m in low for m in _AUTH_MARKERS):
            return BackendAuthError(msg)
        return BackendError(msg)

    async def generate(
        self,
        messages: list[BaseMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_schema: Optional[dict] = None,
    ) -> str:
        system_str, user_str = flatten_messages(messages)
        # NOTE: `--tools ""` (two argv elements) disables all tools — no permission
        # prompt. Do NOT add --bare (forces ANTHROPIC_API_KEY, breaks keyless OAuth).
        argv = [
            self.cli_path, "-p", "--output-format", "json",
            "--tools", "", "--strict-mcp-config", "--model", self.model,
        ]
        if system_str:
            argv += ["--system-prompt", system_str]
        if response_schema is not None:
            argv += ["--json-schema", json.dumps(response_schema)]
        argv.append(user_str)  # arbitrary text stays a single discrete argv element

        cwd = tempfile.mkdtemp(prefix="claudecli-")
        try:
            rc, out, err = await run_cli(argv, stdin=None, timeout=self.timeout, cwd=cwd)
        except (FileNotFoundError, PermissionError) as e:
            # missing/unrunnable binary -> permanent; router marks unavailable + falls through
            raise BackendAuthError(f"claude CLI unavailable at '{self.cli_path}': {e}")
        finally:
            shutil.rmtree(cwd, ignore_errors=True)

        if rc != 0:
            raise self._classify(f"claude exited {rc}: {err[:200]}", err)
        try:
            obj = json.loads(out)
        except json.JSONDecodeError:
            raise BackendError(f"claude output not JSON: {out[:200]}")
        if not isinstance(obj, dict):
            raise BackendError(f"claude output not a JSON object: {out[:200]}")
        if obj.get("subtype") != "success" or obj.get("is_error"):
            raise self._classify(
                f"claude failure subtype={obj.get('subtype')}: {str(obj.get('result'))[:200]}",
                err or json.dumps(obj)[:200],
            )
        return obj.get("result", "")

    async def health(self) -> bool:
        cwd = tempfile.mkdtemp(prefix="claudecli-h-")
        try:
            rc, out, _ = await run_cli(
                [self.cli_path, "-p", "--output-format", "json", "--tools", "",
                 "--strict-mcp-config", "--model", "haiku", "ok"],
                stdin=None, timeout=30, cwd=cwd,
            )
            return rc == 0 and json.loads(out).get("subtype") == "success"
        except Exception:
            return False
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
