"""Phase 1: LLMBackend ABC + exception hierarchy."""
import pytest

from agents.llm.backends.base import (
    LLMBackend, BackendError, BackendTransientError,
    BackendTimeoutError, BackendAuthError, LLMAllBackendsFailed,
)
from agents.llm.tasks import BackendName


def test_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        LLMBackend()


def test_subclass_instantiates():
    class Dummy(LLMBackend):
        name = BackendName.OPENROUTER

        async def generate(self, messages, *, temperature=None, max_tokens=None, response_schema=None):
            return "x"

        async def health(self):
            return True

    d = Dummy()
    assert d.name == BackendName.OPENROUTER
    assert d.supports_stream is False
    assert d.supports_schema is False


def test_exception_hierarchy():
    assert issubclass(BackendTransientError, BackendError)
    assert issubclass(BackendTimeoutError, BackendError)
    assert issubclass(BackendAuthError, BackendError)
    assert not issubclass(LLMAllBackendsFailed, BackendError)
