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
from tenacity import retry, stop_after_attempt, wait_exponential

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
    timeout: int = Field(default=120, ge=10, le=600)
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate(
        self,
        messages: list[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            messages: List of chat messages.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.

        Returns:
            Generated text response.

        Raises:
            Exception: If generation fails after retries.
        """
        try:
            # Create client with overrides if provided
            client = self.client
            if temperature is not None or max_tokens is not None:
                client = ChatOpenAI(
                    base_url=self.config.base_url,
                    model=self.config.model,
                    temperature=temperature or self.config.temperature,
                    max_tokens=max_tokens or self.config.max_tokens,
                    timeout=self.config.timeout,
                    api_key=self.config.api_key,
                )

            response = await client.ainvoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)

            logger.debug(
                "llm_generation_success",
                model=self.config.model,
                input_messages=len(messages),
                output_length=len(content),
            )

            return content

        except Exception as e:
            logger.error(
                "llm_generation_failed",
                error=str(e),
                model=self.config.model,
                provider=self.config.provider,
            )
            raise

    async def stream(
        self,
        messages: list[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from the LLM.

        Args:
            messages: List of chat messages.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.

        Yields:
            Text chunks as they are generated.

        Raises:
            Exception: If streaming fails.
        """
        try:
            client = self.client
            if temperature is not None or max_tokens is not None:
                client = ChatOpenAI(
                    base_url=self.config.base_url,
                    model=self.config.model,
                    temperature=temperature or self.config.temperature,
                    max_tokens=max_tokens or self.config.max_tokens,
                    timeout=self.config.timeout,
                    api_key=self.config.api_key,
                )

            async for chunk in client.astream(messages):
                if chunk.content:
                    yield chunk.content if isinstance(chunk.content, str) else str(chunk.content)

        except Exception as e:
            logger.error(
                "llm_stream_failed",
                error=str(e),
                model=self.config.model,
                provider=self.config.provider,
            )
            raise

    async def health_check(self) -> dict:
        """
        Check if the LLM server is available and responding.

        Returns:
            Dict with health status and details.
        """
        health_url = f"{self.config.base_url}/models"

        try:
            response = await self.http_client.get(health_url)

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                model_names = [m.get("id", "unknown") for m in models]

                logger.info(
                    "llm_health_check_success",
                    provider=self.config.provider,
                    available_models=model_names,
                )

                return {
                    "status": "healthy",
                    "provider": self.config.provider,
                    "base_url": self.config.base_url,
                    "configured_model": self.config.model,
                    "available_models": model_names,
                }

            logger.warning(
                "llm_health_check_failed",
                status_code=response.status_code,
                provider=self.config.provider,
            )

            return {
                "status": "unhealthy",
                "provider": self.config.provider,
                "error": f"HTTP {response.status_code}",
            }

        except httpx.ConnectError:
            logger.warning(
                "llm_server_unavailable",
                base_url=self.config.base_url,
                provider=self.config.provider,
            )
            return {
                "status": "unavailable",
                "provider": self.config.provider,
                "error": "Connection refused - is the LLM server running?",
            }

        except Exception as e:
            logger.error(
                "llm_health_check_error",
                error=str(e),
                provider=self.config.provider,
            )
            return {
                "status": "error",
                "provider": self.config.provider,
                "error": str(e),
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
