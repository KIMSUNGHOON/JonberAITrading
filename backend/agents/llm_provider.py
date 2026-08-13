"""
LLM Provider Abstraction Layer

Unified interface for LLM providers supporting:
- vLLM (OpenAI-compatible API) - Windows/Linux with NVIDIA GPU
- Ollama (OpenAI-compatible API) - All platforms including macOS Metal

Both providers use OpenAI-compatible endpoints, allowing seamless switching.
"""

import asyncio
from typing import AsyncIterator, Optional

import httpx
import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.llm.router import get_router

logger = structlog.get_logger()


class LLMConfig(BaseModel):
    """Configuration for LLM provider."""

    provider: str = Field(default="vllm", description="LLM provider: vllm or ollama")
    base_url: str = Field(
        default="http://localhost:8080/v1",
        description="OpenAI-compatible API endpoint",
    )
    model: str = Field(
        default="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        description="Model name/path",
    )
    # DeepSeek-R1 recommended: 0.5-0.7 (0.6 optimal) to prevent repetitions
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    timeout: int = Field(default=300, ge=10, le=600)  # 5 minutes for complex LLM analysis
    api_key: str = Field(default="not-needed-for-local")

    @classmethod
    def from_settings(cls) -> "LLMConfig":
        """Create config from application settings."""
        from app.config import settings

        return cls(
            provider=settings.LLM_PROVIDER,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            timeout=settings.LLM_TIMEOUT,
            api_key=settings.llm_api_key,
        )

    @property
    def is_ollama(self) -> bool:
        """Check if using Ollama provider."""
        return self.provider.lower() == "ollama"

    @property
    def is_vllm(self) -> bool:
        """Check if using vLLM provider."""
        return self.provider.lower() == "vllm"


class LLMProvider:
    """
    Unified LLM provider with OpenAI-compatible API support.

    Supports:
    - vLLM: High-throughput serving for NVIDIA GPUs
    - Ollama: Easy-to-use local LLM with Metal acceleration on macOS

    Both use OpenAI-compatible endpoints for seamless integration.
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize LLM provider.

        Args:
            config: LLM configuration. If None, loads from settings.
        """
        self.config = config or LLMConfig.from_settings()
        self._client: Optional[ChatOpenAI] = None
        self._http_client: Optional[httpx.AsyncClient] = None

        logger.info(
            "llm_provider_initialized",
            provider=self.config.provider,
            base_url=self.config.base_url,
            model=self.config.model,
        )

    @property
    def client(self) -> ChatOpenAI:
        """
        Lazy-load LangChain ChatOpenAI client.

        Returns:
            Configured ChatOpenAI instance.
        """
        if self._client is None:
            self._client = ChatOpenAI(
                base_url=self.config.base_url,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout,
                api_key=self.config.api_key,
            )
        return self._client

    @property
    def http_client(self) -> httpx.AsyncClient:
        """
        Lazy-load async HTTP client for direct API calls.

        Returns:
            Configured httpx AsyncClient.
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                follow_redirects=True,
            )
        return self._http_client

    async def generate(
        self,
        messages: list[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        task: object = None,
        response_schema: Optional[dict] = None,
    ) -> str:
        """
        Generate a response via the multi-backend router.

        Positional args are unchanged for backward compatibility. `task` (keyword-
        only) hints which backend to prefer (None -> GENERAL; unknown -> GENERAL).
        `response_schema` requests structured JSON output. Returns raw text (or a
        raw JSON string when a schema is given). Retry/fallback are owned by the
        router, so there is no blanket retry here.
        """
        return await get_router().generate(
            messages,
            task=task,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
        )

    def stream(
        self,
        messages: list[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        task: object = None,
    ) -> AsyncIterator[str]:
        """Stream response chunks via the router (HTTP-capable backends only; the
        router auto-excludes non-streaming CLI backends from the chain)."""
        return get_router().stream(
            messages, task=task, temperature=temperature, max_tokens=max_tokens
        )

    async def generate_structured(
        self,
        messages: list[BaseMessage],
        schema: dict,
        *,
        task: object = "strategic_decision",
    ) -> dict:
        """Generate a structured object, JSON-parsed and checked for the schema's
        required keys. Raises ValueError on parse failure or missing keys."""
        import json

        raw = await get_router().generate(messages, task=task, response_schema=schema)
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"structured output was not valid JSON: {str(raw)[:200]}") from e
        missing = [k for k in schema.get("required", []) if k not in obj]
        if missing:
            raise ValueError(f"structured output missing required keys {missing}: {str(raw)[:200]}")
        return obj

    async def health_check(self) -> dict:
        """Report intelligence-layer health as a summary of the router snapshot.

        Kept for backward compatibility with app startup, which reads
        ``status`` / ``provider`` / ``configured_model``.
        """
        snapshot = get_router().snapshot()
        constructed = [n for n, b in snapshot["backends"].items() if b["constructed"]]
        return {
            "status": "healthy" if constructed else "unavailable",
            "provider": "router",
            "configured_model": self.config.model,
            "available_backends": constructed,
            "backends": snapshot["backends"],
        }

    async def close(self) -> None:
        """Clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            logger.debug("llm_http_client_closed")


# -------------------------------------------
# Singleton Pattern for Global Access
# -------------------------------------------

_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """
    Get or create the global LLM provider instance.

    Returns:
        Singleton LLMProvider instance.
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider


def reset_llm_provider() -> None:
    """
    Reset the global LLM provider instance.
    Useful for testing or reconfiguration.
    """
    global _llm_provider
    if _llm_provider is not None:
        asyncio.create_task(_llm_provider.close())
    _llm_provider = None


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def create_messages(
    system_prompt: str,
    user_message: str,
    history: Optional[list[dict]] = None,
) -> list[BaseMessage]:
    """
    Create a list of chat messages for LLM input.

    Args:
        system_prompt: System instruction for the LLM.
        user_message: Current user message.
        history: Optional conversation history as list of
                 {"role": "user"|"assistant", "content": str}.

    Returns:
        List of BaseMessage objects.
    """
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]

    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=user_message))
    return messages
