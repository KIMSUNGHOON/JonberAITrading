"""Codex CLI backend (keyless — ChatGPT Plus subscription OAuth).

Runs `codex exec -s read-only` in a throwaway cwd. The system+user prompt goes
via STDIN (exec has no system-prompt flag). The clean final message is written
to the `-o` file (stdout is the full transcript, which we do NOT parse).
Verified 2026-07-05: `-o` file contains just the final message.
"""
import json
import os
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

_RATE_MARKERS = ("rate limit", "429", "overloaded", "usage limit")
_AUTH_MARKERS = ("not logged in", "unauthorized", "please run codex login", "authentication")

_PREAMBLE = "RESPOND WITH TEXT ONLY, DO NOT USE TOOLS."


class CodexCLIBackend(LLMBackend):
    name = BackendName.CODEX_CLI
    supports_stream = False
    supports_schema = True

    def __init__(self, cli_path: str = "codex", model: Optional[str] = None, timeout: int = 180):
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
        tmpdir = tempfile.mkdtemp(prefix="codexcli-")
        out_path = os.path.join(tmpdir, "out.txt")
        argv = [
            self.cli_path, "exec", "-s", "read-only", "--skip-git-repo-check",
            "-C", tmpdir, "--color", "never", "-o", out_path,
        ]
        if response_schema is not None:
            schema_path = os.path.join(tmpdir, "schema.json")
            with open(schema_path, "w") as f:
                json.dump(response_schema, f)
            argv += ["--output-schema", schema_path]
        if self.model:
            argv += ["-m", self.model]
        argv.append("-")  # read prompt from stdin

        preamble = f"{system_str}\n\n---\n{_PREAMBLE}" if system_str else _PREAMBLE
        stdin = f"{preamble}\n\n{user_str}"
        try:
            rc, out, err = await run_cli(argv, stdin=stdin, timeout=self.timeout, cwd=tmpdir)
            if rc != 0:
                raise self._classify(f"codex exited {rc}: {err[:200]}", err)
            try:
                with open(out_path) as f:
                    text = f.read().strip()
            except FileNotFoundError:
                raise BackendError("codex produced no -o output file")
            if not text:
                raise BackendError("codex output file empty")
            return text
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def health(self) -> bool:
        tmpdir = tempfile.mkdtemp(prefix="codexcli-h-")
        out_path = os.path.join(tmpdir, "out.txt")
        argv = [
            self.cli_path, "exec", "-s", "read-only", "--skip-git-repo-check",
            "-C", tmpdir, "--color", "never", "-o", out_path,
        ]
        if self.model:
            argv += ["-m", self.model]
        argv.append("-")
        try:
            rc, _, _ = await run_cli(argv, stdin=f"{_PREAMBLE}\n\nReply: ok", timeout=30, cwd=tmpdir)
            return rc == 0 and os.path.exists(out_path)
        except Exception:
            return False
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
