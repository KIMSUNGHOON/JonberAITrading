"""Backend abstraction + exception hierarchy for the LLM router.

Every concrete backend (OpenAI-compatible HTTP, Claude CLI, Codex CLI) implements
`LLMBackend`. The router walks a per-task chain of these, catching `BackendError`
to fall through to the next; if the chain is exhausted it raises
`LLMAllBackendsFailed`.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from langchain_core.messages import BaseMessage

from agents.llm.tasks import BackendName


class BackendError(Exception):
    """A backend failed to produce a usable result. The router falls through."""


class BackendTransientError(BackendError):
    """Transient failure (rate limit / 429 / overloaded / 5xx) — longer CB cooldown."""


class BackendUsageLimitError(BackendTransientError):
    """사용량 한도 소진. 기다리면 풀리는 종류라 라우터가 신선도 상한까지 대기한다.

    `BackendTransientError`의 하위 타입인 이유: 라우터의 기존 transient 처리
    (서킷 2배 쿨다운)를 그대로 물려받아야 하기 때문이다.
    """


class BackendTimeoutError(BackendError):
    """The backend exceeded its timeout."""


class BackendAuthError(BackendError):
    """Auth failure (missing key / logged-out CLI). Router marks backend unavailable."""


class LLMAllBackendsFailed(Exception):
    """Every backend in the resolved chain failed (or the chain was empty)."""


class LLMBackend(ABC):
    """One reasoning backend. Subclasses set `name` and the capability flags."""

    name: BackendName
    supports_stream: bool = False
    supports_schema: bool = False

    @abstractmethod
    async def generate(
        self,
        messages: list[BaseMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_schema: Optional[dict] = None,
    ) -> str:
        """Return the model's text (or raw JSON when response_schema is given)."""

    async def stream(
        self,
        messages: list[BaseMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Yield text chunks. Only backends with supports_stream=True override this;
        the router never calls stream() on a non-streaming backend."""
        raise NotImplementedError(f"{self.name} does not support streaming")
        yield ""  # pragma: no cover  — makes this an async generator

    @abstractmethod
    async def health(self) -> bool:
        """Best-effort reachability probe. True if the backend can serve requests."""
