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
    BackendAuthError, BackendError, BackendTransientError, BackendUsageLimitError, LLMBackend,
)
from agents.llm.messages import flatten_messages
from agents.llm.subprocess_runner import run_cli
from agents.llm.tasks import BackendName

logger = structlog.get_logger()

_LIMIT_MARKERS = ("usage limit",)
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
            # `.strip()`을 **각 스트림에** 건다. `run_cli`은 디코딩만 한 원본을
            # 돌려주므로 stderr가 개행 하나("\n")여도 truthy다 — `(err or out)`은
            # 그 개행을 골라 잡고 뒤늦게 strip해 `detail=""`이 된다. 그러면
            # "claude exited 1: "처럼 사유가 빈 채로 나가고, 그 문자열이 그대로
            # Telegram 본문에 실린다(2026-08-03 조사의 출발점인 바로 그 빈 콜론).
            # 분류(`_classify`)는 두 스트림을 따로 받으므로 영향 없다.
            detail = (err.strip() or out.strip())
            raise self._classify(f"claude exited {rc}: {detail[:200]}", f"{err} {out}")
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
            # 프로브는 반드시 실제 사용 모델로 한다. haiku로 확인하고 sonnet으로 호출하면
            # 모델·플랜 단위 한도가 프로브를 통과해, /api/llm/stats가 healthy: true를
            # 보고하는 동안 전 호출이 실패한다(2026-08-03 라이브에서 실제로 발생).
            rc, out, _ = await run_cli(
                [self.cli_path, "-p", "--output-format", "json", "--tools", "",
                 "--strict-mcp-config", "--model", self.model, "ok"],
                stdin=None, timeout=30, cwd=cwd,
            )
            return rc == 0 and json.loads(out).get("subtype") == "success"
        except Exception:
            return False
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
