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
    BackendAuthError, BackendError, BackendTransientError, BackendUsageLimitError, LLMBackend,
)
from agents.llm.messages import flatten_messages
from agents.llm.subprocess_runner import run_cli
from agents.llm.tasks import BackendName

logger = structlog.get_logger()

_LIMIT_MARKERS = ("usage limit",)
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

    def _classify(self, msg: str, extra: str = "") -> BackendError:
        low = f"{msg} {extra}".lower()
        # 한도를 rate보다 먼저 본다 — 한도는 대기로 풀리지만 일반 rate는 아니다.
        if any(m in low for m in _LIMIT_MARKERS):
            return BackendUsageLimitError(msg)
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
            try:
                rc, out, err = await run_cli(argv, stdin=stdin, timeout=self.timeout, cwd=tmpdir)
            except (FileNotFoundError, PermissionError) as e:
                # missing/unrunnable binary -> permanent; router marks unavailable + falls through
                raise BackendAuthError(f"codex CLI unavailable at '{self.cli_path}': {e}")
            if rc != 0:
                # claude_cli.py와 같은 이유로 **각 스트림에** strip을 건다:
                # 공백뿐인 stderr("\n")가 truthy라 `(err or out)`이 그걸 골라
                # 잡으면 사유가 빈 채로 나간다. 분류는 두 스트림을 따로 받으므로
                # 영향 없다.
                detail = (err.strip() or out.strip())
                raise self._classify(f"codex exited {rc}: {detail[:200]}", f"{err} {out}")
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
