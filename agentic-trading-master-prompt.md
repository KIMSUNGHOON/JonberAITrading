# Claude Code Master Prompt: Agentic AI Trading Application

## Project Overview

Build a production-ready **Agentic AI Trading Application** with autonomous analysis, human-in-the-loop approval workflows, and real-time execution monitoring. The system uses DeepAgents for intelligent task decomposition, LangGraph for stateful agent orchestration with interrupts, and a modern FastAPI + React stack.

---

## 1. Environment & Infrastructure Setup

### 1.1 Hardware Context
- **GPU**: NVIDIA RTX 3090 (24GB VRAM)
- **Target Model**: DeepSeek-R1 Distill Llama 70B (quantized to fit VRAM) or Llama 3.1 70B Q4
- **Serving Framework**: vLLM (preferred for throughput) or Ollama (simpler setup)

### 1.2 Initialize Project Structure

Create the following directory structure:

```
agentic-trading/
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── Dockerfile.llm
│   └── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI entrypoint
│   │   ├── config.py               # Environment configuration
│   │   ├── dependencies.py         # Dependency injection
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── routes/
│   │       │   ├── __init__.py
│   │       │   ├── analysis.py     # Ticker analysis endpoints
│   │       │   ├── approval.py     # HITL approval endpoints
│   │       │   ├── execution.py    # Trade execution endpoints
│   │       │   └── websocket.py    # Real-time streaming
│   │       └── schemas/
│   │           ├── __init__.py
│   │           ├── analysis.py
│   │           ├── approval.py
│   │           └── execution.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── llm_provider.py         # LLM abstraction layer
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   ├── state.py            # LangGraph state definitions
│   │   │   ├── nodes.py            # Graph node functions
│   │   │   ├── edges.py            # Conditional edge logic
│   │   │   └── trading_graph.py    # Main graph assembly
│   │   ├── subagents/
│   │   │   ├── __init__.py
│   │   │   ├── technical_analyst.py
│   │   │   ├── fundamental_analyst.py
│   │   │   ├── sentiment_analyst.py
│   │   │   ├── risk_assessor.py
│   │   │   └── execution_agent.py
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── market_data.py      # yfinance wrapper
│   │       ├── portfolio.py        # Position tracking
│   │       └── write_todos.py      # Task decomposition tool
│   ├── services/
│   │   ├── __init__.py
│   │   ├── market_data_service.py
│   │   ├── portfolio_service.py
│   │   └── notification_service.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── trade.py
│   │   ├── portfolio.py
│   │   └── analysis.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_agents/
│   │   ├── test_api/
│   │   └── fixtures/
│   │       └── mock_market_data.json
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   │   ├── client.ts           # Axios/fetch wrapper
│   │   │   └── websocket.ts        # WebSocket client
│   │   ├── components/
│   │   │   ├── TickerInput.tsx
│   │   │   ├── AnalysisPanel.tsx
│   │   │   ├── ApprovalDialog.tsx
│   │   │   ├── LiveReasoningLog.tsx
│   │   │   ├── PositionMonitor.tsx
│   │   │   └── PnLTracker.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useAnalysis.ts
│   │   │   └── usePortfolio.ts
│   │   ├── store/
│   │   │   ├── index.ts            # Zustand store
│   │   │   └── slices/
│   │   │       ├── analysisSlice.ts
│   │   │       ├── approvalSlice.ts
│   │   │       └── portfolioSlice.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   └── utils/
│   │       └── formatters.ts
│   └── public/
├── scripts/
│   ├── setup_llm.sh                # vLLM/Ollama setup script
│   ├── download_model.sh           # Model download helper
│   └── seed_data.py                # Mock data generator
├── data/
│   └── mock/
│       ├── historical_prices.json
│       └── sample_portfolio.json
├── .env.example
├── .gitignore
├── README.md
└── CLAUDE.md                       # Claude Code project instructions
```

### 1.3 Create CLAUDE.md Project Instructions

Create a `CLAUDE.md` file in the project root with these instructions for Claude Code:

```markdown
# CLAUDE.md - Project Instructions for Claude Code

## Project Context
This is an Agentic AI Trading Application using DeepAgents, LangGraph, FastAPI, and React.

## Key Architecture Decisions
- **LLM Abstraction**: All LLM calls go through `backend/agents/llm_provider.py` which supports both local (vLLM/Ollama) and remote (OpenAI-compatible) endpoints
- **State Management**: LangGraph manages agent state with checkpointing for HITL interrupts
- **Real-time Updates**: WebSocket connections stream reasoning logs and position updates
- **Data Fallback**: Always use yfinance with graceful fallback to mock data in `data/mock/`

## Development Commands
- Backend: `cd backend && uvicorn app.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev`
- LLM Server: `./scripts/setup_llm.sh` (starts vLLM on port 8080)
- Tests: `cd backend && pytest -v`

## Code Style
- Python: Use type hints, Pydantic models, async/await patterns
- TypeScript: Strict mode, functional components with hooks
- Always handle errors gracefully with user-friendly messages

## Environment Variables (from .env)
- `LLM_BASE_URL`: OpenAI-compatible endpoint (default: http://localhost:8080/v1)
- `LLM_MODEL`: Model name (default: deepseek-r1-distill-llama-70b)
- `MARKET_DATA_MODE`: "live" or "mock"
```

---

## 2. Docker & Environment Configuration

### 2.1 Create docker-compose.yml

```yaml
version: '3.8'

services:
  llm-server:
    build:
      context: .
      dockerfile: docker/Dockerfile.llm
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    ports:
      - "8080:8080"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    command: >
      python -m vllm.entrypoints.openai.api_server
      --model deepseek-ai/DeepSeek-R1-Distill-Llama-70B
      --quantization awq
      --max-model-len 8192
      --gpu-memory-utilization 0.95
      --host 0.0.0.0
      --port 8080

  backend:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      - LLM_BASE_URL=http://llm-server:8080/v1
      - LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-70B
      - MARKET_DATA_MODE=live
    volumes:
      - ./backend:/app
      - ./data:/app/data
    depends_on:
      - llm-server
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build:
      context: .
      dockerfile: docker/Dockerfile.frontend
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    depends_on:
      - backend
    command: npm run dev -- --host 0.0.0.0

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### 2.2 Create Dockerfile.backend

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2.3 Create Dockerfile.llm

```dockerfile
FROM nvidia/cuda:12.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    vllm \
    transformers \
    accelerate \
    torch

EXPOSE 8080
```

### 2.4 Create requirements.txt

```
# Core Framework
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# LangChain & LangGraph
langchain>=0.1.0
langchain-community>=0.0.20
langchain-openai>=0.0.5
langgraph>=0.0.20

# DeepAgents (if available via pip, otherwise include as local package)
# deepagents>=0.1.0

# Data & Market
yfinance>=0.2.36
pandas>=2.1.0
numpy>=1.26.0

# Async & WebSockets
websockets>=12.0
aiohttp>=3.9.0
httpx>=0.26.0

# State & Caching
redis>=5.0.0
diskcache>=5.6.0

# Utilities
python-dotenv>=1.0.0
structlog>=24.1.0
tenacity>=8.2.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
httpx>=0.26.0
```

---

## 3. LLM Abstraction Layer

### 3.1 Create backend/agents/llm_provider.py

```python
"""
LLM Provider Abstraction Layer
Supports vLLM, Ollama, and any OpenAI-compatible endpoint.
"""

import os
from typing import AsyncIterator, Optional
from abc import ABC, abstractmethod
import httpx
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import structlog

logger = structlog.get_logger()


class LLMConfig(BaseModel):
    """Configuration for LLM provider."""
    base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
    model: str = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Llama-70B")
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120


class LLMProvider:
    """
    Unified LLM provider with OpenAI-compatible API support.
    Works with vLLM, Ollama, and remote endpoints.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._client: Optional[ChatOpenAI] = None
        self._http_client: Optional[httpx.AsyncClient] = None
    
    @property
    def client(self) -> ChatOpenAI:
        """Lazy-load LangChain ChatOpenAI client."""
        if self._client is None:
            self._client = ChatOpenAI(
                base_url=self.config.base_url,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout,
                api_key="not-needed-for-local"  # vLLM doesn't require API key
            )
        return self._client
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-load async HTTP client for streaming."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._http_client
    
    async def generate(self, messages: list[BaseMessage]) -> str:
        """Generate a response from the LLM."""
        try:
            response = await self.client.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("llm_generation_failed", error=str(e))
            raise
    
    async def stream(self, messages: list[BaseMessage]) -> AsyncIterator[str]:
        """Stream response tokens from the LLM."""
        try:
            async for chunk in self.client.astream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("llm_stream_failed", error=str(e))
            raise
    
    async def health_check(self) -> bool:
        """Check if the LLM server is available."""
        try:
            response = await self.http_client.get(
                f"{self.config.base_url}/models"
            )
            return response.status_code == 200
        except Exception:
            return False
    
    async def close(self):
        """Clean up resources."""
        if self._http_client:
            await self._http_client.aclose()


# Global instance for dependency injection
_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    """Get or create the global LLM provider instance."""
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider
```

---

## 4. LangGraph Trading Agent Implementation

### 4.1 Create backend/agents/graph/state.py

```python
"""
LangGraph State Definitions for Trading Agent
"""

from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from datetime import datetime


class AnalysisResult(BaseModel):
    """Result from a subagent analysis."""
    agent_type: str
    ticker: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: dict = Field(default_factory=dict)
    reasoning: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TradeProposal(BaseModel):
    """Proposed trade awaiting approval."""
    id: str
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    quantity: int
    price_target: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rationale: str
    risk_score: float = Field(ge=0.0, le=1.0)
    analyses: list[AnalysisResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    """Active trading position."""
    ticker: str
    quantity: int
    entry_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    opened_at: datetime


class TradingState(TypedDict):
    """
    Main state object for the LangGraph trading workflow.
    Uses Annotated types for proper state merging.
    """
    # Input
    ticker: str
    user_query: str
    
    # Messages for conversation tracking
    messages: Annotated[list, add_messages]
    
    # Task decomposition
    todos: list[dict]  # [{task: str, assigned_to: str, status: str}]
    
    # Analysis results from subagents
    technical_analysis: Optional[AnalysisResult]
    fundamental_analysis: Optional[AnalysisResult]
    sentiment_analysis: Optional[AnalysisResult]
    risk_assessment: Optional[AnalysisResult]
    
    # Strategic decision
    trade_proposal: Optional[TradeProposal]
    
    # HITL state
    awaiting_approval: bool
    approval_status: Optional[Literal["approved", "rejected", "modified"]]
    user_feedback: Optional[str]
    
    # Execution state
    execution_status: Optional[Literal["pending", "executing", "completed", "failed"]]
    active_position: Optional[Position]
    
    # Reasoning trace for live log
    reasoning_log: list[str]
    
    # Error handling
    error: Optional[str]
    
    # Workflow control
    current_stage: Literal["analysis", "approval", "execution", "complete"]
```

### 4.2 Create backend/agents/graph/nodes.py

```python
"""
LangGraph Node Functions for Trading Workflow
"""

import uuid
from datetime import datetime
from typing import Literal
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import structlog

from .state import TradingState, AnalysisResult, TradeProposal
from ..llm_provider import get_llm_provider
from ..tools.market_data import get_market_data
from ..tools.write_todos import decompose_task

logger = structlog.get_logger()


async def task_decomposition_node(state: TradingState) -> dict:
    """
    Stage 1A: Decompose the analysis task into subtasks.
    Uses write_todos tool pattern from DeepAgents.
    """
    ticker = state["ticker"]
    query = state.get("user_query", f"Analyze {ticker} for trading opportunity")
    
    logger.info("task_decomposition_start", ticker=ticker)
    
    # Generate task decomposition
    todos = await decompose_task(ticker, query)
    
    reasoning = f"[Task Decomposition] Breaking down analysis for {ticker} into {len(todos)} subtasks"
    
    return {
        "todos": todos,
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def technical_analysis_node(state: TradingState) -> dict:
    """
    Stage 1B: Technical analysis subagent.
    Analyzes price patterns, indicators, and trends.
    """
    ticker = state["ticker"]
    llm = get_llm_provider()
    
    logger.info("technical_analysis_start", ticker=ticker)
    
    # Fetch market data
    market_data = await get_market_data(ticker, period="3mo")
    
    system_prompt = """You are an expert technical analyst. Analyze the provided market data and identify:
1. Key support and resistance levels
2. Trend direction and strength
3. Important chart patterns
4. Technical indicator signals (RSI, MACD, Moving Averages)
5. Entry/exit points based on technical factors

Provide a confidence score (0-1) for your analysis."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Analyze {ticker}:\n{market_data.to_string()}")
    ]
    
    response = await llm.generate(messages)
    
    # Parse response into structured result
    result = AnalysisResult(
        agent_type="technical",
        ticker=ticker,
        summary=response[:500],
        confidence=0.75,  # Would parse from LLM response
        signals={"trend": "bullish", "rsi": 45, "macd": "bullish_crossover"},
        reasoning=response
    )
    
    reasoning = f"[Technical Analysis] Completed for {ticker}: {result.summary[:100]}..."
    
    return {
        "technical_analysis": result,
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def fundamental_analysis_node(state: TradingState) -> dict:
    """
    Stage 1C: Fundamental analysis subagent.
    Analyzes company financials, valuation, and business metrics.
    """
    ticker = state["ticker"]
    llm = get_llm_provider()
    
    logger.info("fundamental_analysis_start", ticker=ticker)
    
    # Would fetch fundamental data (earnings, ratios, etc.)
    # For now, using mock data structure
    
    system_prompt = """You are an expert fundamental analyst. Evaluate:
1. Revenue and earnings trends
2. Valuation metrics (P/E, P/B, EV/EBITDA)
3. Balance sheet strength
4. Competitive positioning
5. Growth catalysts and risks

Provide a confidence score (0-1) for your analysis."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Analyze fundamentals for {ticker}")
    ]
    
    response = await llm.generate(messages)
    
    result = AnalysisResult(
        agent_type="fundamental",
        ticker=ticker,
        summary=response[:500],
        confidence=0.7,
        signals={"valuation": "fair", "growth": "moderate"},
        reasoning=response
    )
    
    reasoning = f"[Fundamental Analysis] Completed for {ticker}: {result.summary[:100]}..."
    
    return {
        "fundamental_analysis": result,
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def sentiment_analysis_node(state: TradingState) -> dict:
    """
    Stage 1D: Sentiment analysis subagent.
    Analyzes market sentiment from news and social sources.
    """
    ticker = state["ticker"]
    llm = get_llm_provider()
    
    logger.info("sentiment_analysis_start", ticker=ticker)
    
    system_prompt = """You are a sentiment analysis expert. Evaluate:
1. Recent news sentiment
2. Social media buzz and sentiment
3. Analyst opinions and rating changes
4. Institutional activity signals
5. Overall market mood towards this asset

Provide a confidence score (0-1) for your analysis."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Analyze sentiment for {ticker}")
    ]
    
    response = await llm.generate(messages)
    
    result = AnalysisResult(
        agent_type="sentiment",
        ticker=ticker,
        summary=response[:500],
        confidence=0.65,
        signals={"news_sentiment": "positive", "social_sentiment": "neutral"},
        reasoning=response
    )
    
    reasoning = f"[Sentiment Analysis] Completed for {ticker}: {result.summary[:100]}..."
    
    return {
        "sentiment_analysis": result,
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def risk_assessment_node(state: TradingState) -> dict:
    """
    Stage 1E: Risk assessment subagent.
    Evaluates portfolio risk and position sizing.
    """
    ticker = state["ticker"]
    llm = get_llm_provider()
    
    logger.info("risk_assessment_start", ticker=ticker)
    
    # Gather all previous analyses
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis"]:
        if state.get(key):
            analyses.append(state[key])
    
    system_prompt = """You are a risk management expert. Based on the provided analyses, evaluate:
1. Volatility and drawdown risk
2. Position sizing recommendation
3. Stop-loss and take-profit levels
4. Portfolio correlation risk
5. Overall risk score (0-1, where 1 is highest risk)

Be conservative and prioritize capital preservation."""

    context = "\n\n".join([f"{a.agent_type}: {a.summary}" for a in analyses])
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Assess risk for {ticker}:\n{context}")
    ]
    
    response = await llm.generate(messages)
    
    result = AnalysisResult(
        agent_type="risk",
        ticker=ticker,
        summary=response[:500],
        confidence=0.8,
        signals={"risk_score": 0.4, "max_position_pct": 5},
        reasoning=response
    )
    
    reasoning = f"[Risk Assessment] Completed for {ticker}: Risk Score {result.signals.get('risk_score', 'N/A')}"
    
    return {
        "risk_assessment": result,
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def strategic_decision_node(state: TradingState) -> dict:
    """
    Stage 1F: Synthesize all analyses into a trade proposal.
    """
    ticker = state["ticker"]
    llm = get_llm_provider()
    
    logger.info("strategic_decision_start", ticker=ticker)
    
    # Collect all analyses
    analyses = []
    for key in ["technical_analysis", "fundamental_analysis", "sentiment_analysis", "risk_assessment"]:
        if state.get(key):
            analyses.append(state[key])
    
    system_prompt = """You are a senior portfolio manager. Based on all analyses provided:
1. Synthesize the key findings
2. Make a clear BUY, SELL, or HOLD recommendation
3. Specify entry price, stop-loss, and take-profit levels
4. Determine appropriate position size
5. Provide clear rationale for your decision

Output your decision in a structured format."""

    context = "\n\n".join([
        f"=== {a.agent_type.upper()} ANALYSIS ===\n{a.reasoning}"
        for a in analyses
    ])
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Make trading decision for {ticker}:\n{context}")
    ]
    
    response = await llm.generate(messages)
    
    # Parse response into TradeProposal (simplified)
    proposal = TradeProposal(
        id=str(uuid.uuid4()),
        ticker=ticker,
        action="BUY",  # Would parse from LLM
        quantity=100,
        price_target=None,
        stop_loss=None,
        take_profit=None,
        rationale=response,
        risk_score=state.get("risk_assessment", {}).signals.get("risk_score", 0.5) if state.get("risk_assessment") else 0.5,
        analyses=analyses
    )
    
    reasoning = f"[Strategic Decision] Proposal generated: {proposal.action} {proposal.quantity} {ticker}"
    
    return {
        "trade_proposal": proposal,
        "awaiting_approval": True,
        "current_stage": "approval",
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


async def human_approval_node(state: TradingState) -> dict:
    """
    Stage 2: Human-in-the-loop approval checkpoint.
    This node is an interrupt point - execution pauses here.
    """
    logger.info("awaiting_human_approval", 
                ticker=state["ticker"],
                proposal_id=state["trade_proposal"].id if state.get("trade_proposal") else None)
    
    reasoning = "[HITL] Awaiting human approval for trade proposal..."
    
    return {
        "awaiting_approval": True,
        "current_stage": "approval",
        "reasoning_log": [reasoning]
    }


async def execution_node(state: TradingState) -> dict:
    """
    Stage 3: Execute the approved trade.
    """
    proposal = state.get("trade_proposal")
    approval_status = state.get("approval_status")
    
    if approval_status != "approved":
        reasoning = f"[Execution] Trade not approved (status: {approval_status}). Skipping execution."
        return {
            "execution_status": "cancelled",
            "current_stage": "complete",
            "reasoning_log": [reasoning]
        }
    
    logger.info("trade_execution_start",
                ticker=proposal.ticker,
                action=proposal.action,
                quantity=proposal.quantity)
    
    # Simulate trade execution
    # In production, this would connect to a broker API
    
    position = Position(
        ticker=proposal.ticker,
        quantity=proposal.quantity,
        entry_price=100.0,  # Would get actual execution price
        current_price=100.0,
        pnl=0.0,
        pnl_percent=0.0,
        opened_at=datetime.utcnow()
    )
    
    reasoning = f"[Execution] Trade executed: {proposal.action} {proposal.quantity} {proposal.ticker} @ $100.00"
    
    return {
        "execution_status": "completed",
        "active_position": position,
        "current_stage": "complete",
        "reasoning_log": [reasoning],
        "messages": [AIMessage(content=reasoning)]
    }


def should_continue_to_execution(state: TradingState) -> Literal["execute", "end"]:
    """
    Conditional edge: Check if trade was approved.
    """
    if state.get("approval_status") == "approved":
        return "execute"
    return "end"
```

### 4.3 Create backend/agents/graph/trading_graph.py

```python
"""
Main LangGraph Assembly for Trading Agent
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import TradingState
from .nodes import (
    task_decomposition_node,
    technical_analysis_node,
    fundamental_analysis_node,
    sentiment_analysis_node,
    risk_assessment_node,
    strategic_decision_node,
    human_approval_node,
    execution_node,
    should_continue_to_execution
)


def create_trading_graph() -> StateGraph:
    """
    Create the main trading workflow graph.
    
    Flow:
    1. Task Decomposition -> Parallel Analyses
    2. Risk Assessment -> Strategic Decision
    3. Human Approval (INTERRUPT)
    4. Execution (if approved)
    """
    
    # Initialize graph with state schema
    workflow = StateGraph(TradingState)
    
    # Add nodes
    workflow.add_node("decompose", task_decomposition_node)
    workflow.add_node("technical", technical_analysis_node)
    workflow.add_node("fundamental", fundamental_analysis_node)
    workflow.add_node("sentiment", sentiment_analysis_node)
    workflow.add_node("risk", risk_assessment_node)
    workflow.add_node("decision", strategic_decision_node)
    workflow.add_node("approval", human_approval_node)
    workflow.add_node("execute", execution_node)
    
    # Set entry point
    workflow.set_entry_point("decompose")
    
    # Add edges for sequential flow with parallel analysis
    # Note: For true parallel execution, use add_branch or subgraphs
    workflow.add_edge("decompose", "technical")
    workflow.add_edge("technical", "fundamental")
    workflow.add_edge("fundamental", "sentiment")
    workflow.add_edge("sentiment", "risk")
    workflow.add_edge("risk", "decision")
    workflow.add_edge("decision", "approval")
    
    # Conditional edge after approval
    workflow.add_conditional_edges(
        "approval",
        should_continue_to_execution,
        {
            "execute": "execute",
            "end": END
        }
    )
    
    workflow.add_edge("execute", END)
    
    return workflow


def compile_trading_graph(checkpointer=None):
    """
    Compile the trading graph with optional checkpointing.
    
    Args:
        checkpointer: LangGraph checkpointer for state persistence.
                     Uses MemorySaver by default for development.
    """
    workflow = create_trading_graph()
    
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    # Compile with interrupt before approval for HITL
    compiled = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval"]  # Pause before human approval
    )
    
    return compiled


# Singleton compiled graph
_trading_graph = None


def get_trading_graph():
    """Get or create the singleton trading graph."""
    global _trading_graph
    if _trading_graph is None:
        _trading_graph = compile_trading_graph()
    return _trading_graph
```

### 4.4 Create backend/agents/tools/write_todos.py

```python
"""
Task Decomposition Tool (DeepAgents pattern)
Breaks down analysis tasks into subtasks for subagent delegation.
"""

from typing import List, Dict
from langchain_core.messages import SystemMessage, HumanMessage
from ..llm_provider import get_llm_provider


async def decompose_task(ticker: str, query: str) -> List[Dict]:
    """
    Decompose a trading analysis task into subtasks.
    Returns a list of todos for subagent execution.
    
    Args:
        ticker: Stock ticker symbol
        query: User's analysis request
        
    Returns:
        List of task dictionaries with structure:
        {
            "task": str,
            "assigned_to": str,  # subagent type
            "status": str,
            "priority": int
        }
    """
    llm = get_llm_provider()
    
    system_prompt = """You are a task planning agent. Break down the trading analysis request into specific subtasks.
    
Available subagents:
- technical_analyst: Price patterns, indicators, chart analysis
- fundamental_analyst: Financials, valuations, business metrics
- sentiment_analyst: News sentiment, social media, analyst opinions
- risk_assessor: Risk evaluation, position sizing, stop-loss levels

Output format (JSON list):
[
    {"task": "description", "assigned_to": "subagent_name", "priority": 1-5},
    ...
]

Create 3-5 focused tasks that cover all aspects of the analysis."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Ticker: {ticker}\nRequest: {query}")
    ]
    
    response = await llm.generate(messages)
    
    # Parse response (simplified - would use structured output in production)
    # Default todos if parsing fails
    default_todos = [
        {"task": f"Analyze technical indicators for {ticker}", "assigned_to": "technical_analyst", "status": "pending", "priority": 1},
        {"task": f"Review fundamentals and valuation for {ticker}", "assigned_to": "fundamental_analyst", "status": "pending", "priority": 2},
        {"task": f"Assess market sentiment for {ticker}", "assigned_to": "sentiment_analyst", "status": "pending", "priority": 3},
        {"task": f"Evaluate risk and position sizing for {ticker}", "assigned_to": "risk_assessor", "status": "pending", "priority": 4},
    ]
    
    try:
        import json
        # Try to extract JSON from response
        start = response.find('[')
        end = response.rfind(']') + 1
        if start != -1 and end > start:
            todos = json.loads(response[start:end])
            for todo in todos:
                todo["status"] = "pending"
            return todos
    except (json.JSONDecodeError, ValueError):
        pass
    
    return default_todos
```

### 4.5 Create backend/agents/tools/market_data.py

```python
"""
Market Data Tool with yfinance and mock data fallback.
"""

import os
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import structlog

logger = structlog.get_logger()

# Check if we're in mock mode
MARKET_DATA_MODE = os.getenv("MARKET_DATA_MODE", "live")


async def get_market_data(
    ticker: str,
    period: str = "1mo",
    interval: str = "1d"
) -> pd.DataFrame:
    """
    Fetch market data for a ticker.
    
    Args:
        ticker: Stock symbol (e.g., "AAPL")
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
        
    Returns:
        DataFrame with OHLCV data
    """
    if MARKET_DATA_MODE == "mock":
        return _get_mock_data(ticker, period)
    
    try:
        import yfinance as yf
        
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        
        if df.empty:
            logger.warning("yfinance_empty_response", ticker=ticker)
            return _get_mock_data(ticker, period)
        
        logger.info("market_data_fetched", ticker=ticker, rows=len(df))
        return df
        
    except Exception as e:
        logger.error("yfinance_error", ticker=ticker, error=str(e))
        return _get_mock_data(ticker, period)


def _get_mock_data(ticker: str, period: str) -> pd.DataFrame:
    """Generate mock market data for testing."""
    import numpy as np
    
    # Determine number of days based on period
    period_days = {
        "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
        "6mo": 180, "1y": 365, "2y": 730
    }
    days = period_days.get(period, 30)
    
    # Generate dates
    end_date = datetime.now()
    dates = pd.date_range(end=end_date, periods=days, freq='D')
    
    # Generate realistic price data
    np.random.seed(hash(ticker) % 2**32)
    base_price = np.random.uniform(50, 500)
    returns = np.random.normal(0.0005, 0.02, days)
    prices = base_price * np.cumprod(1 + returns)
    
    df = pd.DataFrame({
        'Open': prices * np.random.uniform(0.99, 1.01, days),
        'High': prices * np.random.uniform(1.01, 1.03, days),
        'Low': prices * np.random.uniform(0.97, 0.99, days),
        'Close': prices,
        'Volume': np.random.randint(1000000, 50000000, days)
    }, index=dates)
    
    logger.info("mock_data_generated", ticker=ticker, rows=len(df))
    return df


async def get_ticker_info(ticker: str) -> dict:
    """Get basic ticker information."""
    if MARKET_DATA_MODE == "mock":
        return {
            "symbol": ticker,
            "name": f"Mock Company ({ticker})",
            "sector": "Technology",
            "industry": "Software",
            "marketCap": 1000000000
        }
    
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        return stock.info
    except Exception as e:
        logger.error("ticker_info_error", ticker=ticker, error=str(e))
        return {"symbol": ticker, "name": ticker}
```

---

## 5. FastAPI Backend Implementation

### 5.1 Create backend/app/main.py

```python
"""
FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from .config import settings
from .api.routes import analysis, approval, execution, websocket
from agents.llm_provider import get_llm_provider

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("application_startup", environment=settings.ENVIRONMENT)
    
    # Health check LLM
    llm = get_llm_provider()
    if await llm.health_check():
        logger.info("llm_server_connected", url=llm.config.base_url)
    else:
        logger.warning("llm_server_unavailable", url=llm.config.base_url)
    
    yield
    
    # Shutdown
    logger.info("application_shutdown")
    await llm.close()


app = FastAPI(
    title="Agentic Trading API",
    description="AI-powered trading analysis with human-in-the-loop approval",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])
app.include_router(approval.router, prefix="/api/approval", tags=["Approval"])
app.include_router(execution.router, prefix="/api/execution", tags=["Execution"])
app.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    llm = get_llm_provider()
    llm_status = await llm.health_check()
    
    return {
        "status": "healthy",
        "llm_connected": llm_status,
        "environment": settings.ENVIRONMENT
    }
```

### 5.2 Create backend/app/config.py

```python
"""
Application Configuration
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    # LLM Configuration
    LLM_BASE_URL: str = "http://localhost:8080/v1"
    LLM_MODEL: str = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096
    
    # Market Data
    MARKET_DATA_MODE: str = "live"  # "live" or "mock"
    
    # Redis (for state persistence)
    REDIS_URL: str = "redis://localhost:6379"
    
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

### 5.3 Create backend/app/api/routes/analysis.py

```python
"""
Analysis API Routes
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uuid
import structlog

from agents.graph.trading_graph import get_trading_graph
from agents.graph.state import TradingState

logger = structlog.get_logger()
router = APIRouter()

# In-memory session store (use Redis in production)
active_sessions: dict = {}


class AnalysisRequest(BaseModel):
    """Request to start analysis."""
    ticker: str
    query: Optional[str] = None


class AnalysisResponse(BaseModel):
    """Response with session ID."""
    session_id: str
    ticker: str
    status: str
    message: str


@router.post("/start", response_model=AnalysisResponse)
async def start_analysis(request: AnalysisRequest, background_tasks: BackgroundTasks):
    """
    Start a new trading analysis session.
    Returns immediately with session ID for tracking.
    """
    session_id = str(uuid.uuid4())
    ticker = request.ticker.upper()
    
    logger.info("analysis_started", session_id=session_id, ticker=ticker)
    
    # Initialize state
    initial_state: TradingState = {
        "ticker": ticker,
        "user_query": request.query or f"Analyze {ticker} for trading opportunity",
        "messages": [],
        "todos": [],
        "technical_analysis": None,
        "fundamental_analysis": None,
        "sentiment_analysis": None,
        "risk_assessment": None,
        "trade_proposal": None,
        "awaiting_approval": False,
        "approval_status": None,
        "user_feedback": None,
        "execution_status": None,
        "active_position": None,
        "reasoning_log": [],
        "error": None,
        "current_stage": "analysis"
    }
    
    # Store session
    active_sessions[session_id] = {
        "state": initial_state,
        "ticker": ticker,
        "status": "running"
    }
    
    # Run analysis in background
    background_tasks.add_task(run_analysis, session_id, initial_state)
    
    return AnalysisResponse(
        session_id=session_id,
        ticker=ticker,
        status="started",
        message="Analysis started. Connect to WebSocket for live updates."
    )


async def run_analysis(session_id: str, initial_state: TradingState):
    """Background task to run the analysis graph."""
    graph = get_trading_graph()
    
    try:
        config = {"configurable": {"thread_id": session_id}}
        
        # Run until interrupt (approval node)
        async for event in graph.astream(initial_state, config):
            # Update session state
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    session = active_sessions.get(session_id)
                    if session:
                        session["state"].update(node_output)
                        session["last_node"] = node_name
            
            logger.debug("graph_event", session_id=session_id, event=event)
        
        # Check if we hit the interrupt
        session = active_sessions.get(session_id)
        if session and session["state"].get("awaiting_approval"):
            session["status"] = "awaiting_approval"
        
    except Exception as e:
        logger.error("analysis_failed", session_id=session_id, error=str(e))
        if session_id in active_sessions:
            active_sessions[session_id]["status"] = "error"
            active_sessions[session_id]["error"] = str(e)


@router.get("/status/{session_id}")
async def get_analysis_status(session_id: str):
    """Get the current status of an analysis session."""
    session = active_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    state = session["state"]
    
    return {
        "session_id": session_id,
        "ticker": session["ticker"],
        "status": session["status"],
        "current_stage": state.get("current_stage"),
        "awaiting_approval": state.get("awaiting_approval", False),
        "trade_proposal": state.get("trade_proposal"),
        "reasoning_log": state.get("reasoning_log", [])[-10:],  # Last 10 entries
        "error": session.get("error")
    }


@router.get("/sessions")
async def list_sessions():
    """List all active analysis sessions."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "ticker": data["ticker"],
                "status": data["status"]
            }
            for sid, data in active_sessions.items()
        ]
    }
```

### 5.4 Create backend/app/api/routes/approval.py

```python
"""
HITL Approval API Routes
"""

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

from agents.graph.trading_graph import get_trading_graph
from .analysis import active_sessions

logger = structlog.get_logger()
router = APIRouter()


class ApprovalRequest(BaseModel):
    """Request to approve/reject a trade proposal."""
    session_id: str
    decision: Literal["approved", "rejected", "modified"]
    feedback: Optional[str] = None
    modifications: Optional[dict] = None


class ApprovalResponse(BaseModel):
    """Response after approval decision."""
    session_id: str
    decision: str
    status: str
    message: str


@router.post("/decide", response_model=ApprovalResponse)
async def submit_approval(request: ApprovalRequest):
    """
    Submit approval decision for a pending trade proposal.
    This resumes the LangGraph workflow from the interrupt.
    """
    session = active_sessions.get(request.session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    state = session["state"]
    
    if not state.get("awaiting_approval"):
        raise HTTPException(
            status_code=400,
            detail="Session is not awaiting approval"
        )
    
    logger.info("approval_submitted",
                session_id=request.session_id,
                decision=request.decision)
    
    # Update state with approval decision
    state["approval_status"] = request.decision
    state["user_feedback"] = request.feedback
    state["awaiting_approval"] = False
    
    if request.decision == "modified" and request.modifications:
        # Apply modifications to trade proposal
        proposal = state.get("trade_proposal")
        if proposal:
            for key, value in request.modifications.items():
                if hasattr(proposal, key):
                    setattr(proposal, key, value)
    
    # Resume graph execution
    graph = get_trading_graph()
    config = {"configurable": {"thread_id": request.session_id}}
    
    try:
        # Continue from interrupt with updated state
        async for event in graph.astream(None, config):
            for node_name, node_output in event.items():
                if node_name != "__end__":
                    state.update(node_output)
        
        session["status"] = "completed" if request.decision == "approved" else "cancelled"
        
    except Exception as e:
        logger.error("approval_continuation_failed",
                    session_id=request.session_id,
                    error=str(e))
        session["status"] = "error"
        session["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    
    return ApprovalResponse(
        session_id=request.session_id,
        decision=request.decision,
        status=session["status"],
        message=f"Trade {request.decision}. Workflow {'completed' if request.decision == 'approved' else 'ended'}."
    )


@router.get("/pending")
async def list_pending_approvals():
    """List all sessions awaiting approval."""
    pending = []
    
    for session_id, session in active_sessions.items():
        state = session["state"]
        if state.get("awaiting_approval"):
            pending.append({
                "session_id": session_id,
                "ticker": session["ticker"],
                "trade_proposal": state.get("trade_proposal"),
                "analyses_summary": {
                    "technical": state.get("technical_analysis", {}).get("summary", "N/A")[:100] if state.get("technical_analysis") else "N/A",
                    "fundamental": state.get("fundamental_analysis", {}).get("summary", "N/A")[:100] if state.get("fundamental_analysis") else "N/A",
                    "sentiment": state.get("sentiment_analysis", {}).get("summary", "N/A")[:100] if state.get("sentiment_analysis") else "N/A",
                    "risk": state.get("risk_assessment", {}).get("summary", "N/A")[:100] if state.get("risk_assessment") else "N/A",
                }
            })
    
    return {"pending_approvals": pending}
```

### 5.5 Create backend/app/api/routes/websocket.py

```python
"""
WebSocket Routes for Real-time Updates
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import asyncio
import json
import structlog

from .analysis import active_sessions

logger = structlog.get_logger()
router = APIRouter()

# Connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        logger.info("websocket_connected", session_id=session_id)
    
    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info("websocket_disconnected", session_id=session_id)
    
    async def broadcast(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            dead_connections = set()
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.add(connection)
            
            # Clean up dead connections
            for conn in dead_connections:
                self.active_connections[session_id].discard(conn)


manager = ConnectionManager()


@router.websocket("/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time session updates.
    Streams reasoning log, status changes, and position updates.
    """
    await manager.connect(session_id, websocket)
    
    last_log_index = 0
    last_status = None
    
    try:
        while True:
            session = active_sessions.get(session_id)
            
            if session:
                state = session["state"]
                current_status = session["status"]
                reasoning_log = state.get("reasoning_log", [])
                
                # Send new reasoning log entries
                if len(reasoning_log) > last_log_index:
                    new_entries = reasoning_log[last_log_index:]
                    for entry in new_entries:
                        await websocket.send_json({
                            "type": "reasoning",
                            "data": entry
                        })
                    last_log_index = len(reasoning_log)
                
                # Send status updates
                if current_status != last_status:
                    await websocket.send_json({
                        "type": "status",
                        "data": {
                            "status": current_status,
                            "stage": state.get("current_stage"),
                            "awaiting_approval": state.get("awaiting_approval", False)
                        }
                    })
                    last_status = current_status
                
                # Send trade proposal when available
                if state.get("trade_proposal") and state.get("awaiting_approval"):
                    proposal = state["trade_proposal"]
                    await websocket.send_json({
                        "type": "proposal",
                        "data": proposal.model_dump() if hasattr(proposal, 'model_dump') else proposal
                    })
                
                # Send position updates
                if state.get("active_position"):
                    position = state["active_position"]
                    await websocket.send_json({
                        "type": "position",
                        "data": position.model_dump() if hasattr(position, 'model_dump') else position
                    })
                
                # Check for completion
                if current_status in ["completed", "cancelled", "error"]:
                    await websocket.send_json({
                        "type": "complete",
                        "data": {"status": current_status}
                    })
                    break
            
            # Also check for incoming messages (for heartbeat/ping)
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=1.0
                )
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass
            
            await asyncio.sleep(0.5)
            
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
    except Exception as e:
        logger.error("websocket_error", session_id=session_id, error=str(e))
        manager.disconnect(session_id, websocket)
```

---

## 6. React Frontend Implementation

### 6.1 Create frontend/package.json

```json
{
  "name": "agentic-trading-frontend",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "zustand": "^4.5.0",
    "axios": "^1.6.0",
    "recharts": "^2.10.0",
    "lucide-react": "^0.312.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.2.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0"
  }
}
```

### 6.2 Create frontend/src/App.tsx

```tsx
import React, { useState } from 'react';
import { TickerInput } from './components/TickerInput';
import { AnalysisPanel } from './components/AnalysisPanel';
import { ApprovalDialog } from './components/ApprovalDialog';
import { LiveReasoningLog } from './components/LiveReasoningLog';
import { PositionMonitor } from './components/PositionMonitor';
import { useAnalysisStore } from './store';

export default function App() {
  const { activeSession, status } = useAnalysisStore();

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-800 px-6 py-4">
        <h1 className="text-2xl font-bold">Agentic Trading System</h1>
        <p className="text-gray-400 text-sm">AI-Powered Analysis with Human Oversight</p>
      </header>

      <main className="container mx-auto px-6 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Input & Analysis */}
          <div className="lg:col-span-2 space-y-6">
            <TickerInput />
            {activeSession && <AnalysisPanel />}
          </div>

          {/* Right Column: Live Log & Positions */}
          <div className="space-y-6">
            <LiveReasoningLog />
            <PositionMonitor />
          </div>
        </div>

        {/* Approval Modal */}
        <ApprovalDialog />
      </main>
    </div>
  );
}
```

### 6.3 Create frontend/src/store/index.ts

```typescript
import { create } from 'zustand';

interface TradeProposal {
  id: string;
  ticker: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  quantity: number;
  rationale: string;
  risk_score: number;
}

interface Position {
  ticker: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_percent: number;
}

interface AnalysisState {
  // Session
  activeSession: string | null;
  ticker: string;
  status: 'idle' | 'running' | 'awaiting_approval' | 'completed' | 'error';
  
  // Reasoning
  reasoningLog: string[];
  
  // Proposal
  tradeProposal: TradeProposal | null;
  showApprovalDialog: boolean;
  
  // Position
  activePosition: Position | null;
  
  // Actions
  setActiveSession: (sessionId: string | null) => void;
  setTicker: (ticker: string) => void;
  setStatus: (status: AnalysisState['status']) => void;
  addReasoningEntry: (entry: string) => void;
  setTradeProposal: (proposal: TradeProposal | null) => void;
  setShowApprovalDialog: (show: boolean) => void;
  setActivePosition: (position: Position | null) => void;
  reset: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  activeSession: null,
  ticker: '',
  status: 'idle',
  reasoningLog: [],
  tradeProposal: null,
  showApprovalDialog: false,
  activePosition: null,

  setActiveSession: (sessionId) => set({ activeSession: sessionId }),
  setTicker: (ticker) => set({ ticker }),
  setStatus: (status) => set({ status }),
  addReasoningEntry: (entry) =>
    set((state) => ({ reasoningLog: [...state.reasoningLog, entry] })),
  setTradeProposal: (proposal) => set({ tradeProposal: proposal }),
  setShowApprovalDialog: (show) => set({ showApprovalDialog: show }),
  setActivePosition: (position) => set({ activePosition: position }),
  reset: () =>
    set({
      activeSession: null,
      ticker: '',
      status: 'idle',
      reasoningLog: [],
      tradeProposal: null,
      showApprovalDialog: false,
      activePosition: null,
    }),
}));
```

### 6.4 Create frontend/src/components/TickerInput.tsx

```tsx
import React, { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { useAnalysisStore } from '../store';
import { startAnalysis } from '../api/client';
import { connectWebSocket } from '../api/websocket';

export function TickerInput() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const { status, setActiveSession, setTicker, setStatus, reset } = useAnalysisStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    setLoading(true);
    reset();
    setTicker(input.toUpperCase());

    try {
      const response = await startAnalysis(input);
      setActiveSession(response.session_id);
      setStatus('running');
      
      // Connect WebSocket for live updates
      connectWebSocket(response.session_id);
    } catch (error) {
      console.error('Failed to start analysis:', error);
      setStatus('error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-gray-800 rounded-lg p-6">
      <label className="block text-sm font-medium text-gray-300 mb-2">
        Enter Ticker Symbol
      </label>
      <div className="flex gap-4">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="e.g., AAPL, NVDA, TSLA"
          className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={status === 'running'}
        />
        <button
          type="submit"
          disabled={loading || status === 'running'}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 px-6 py-3 rounded-lg font-medium flex items-center gap-2 transition-colors"
        >
          {loading ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Search className="w-5 h-5" />
          )}
          Analyze
        </button>
      </div>
      {status === 'running' && (
        <p className="mt-2 text-sm text-blue-400">Analysis in progress...</p>
      )}
    </form>
  );
}
```

### 6.5 Create frontend/src/components/LiveReasoningLog.tsx

```tsx
import React, { useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';
import { useAnalysisStore } from '../store';

export function LiveReasoningLog() {
  const { reasoningLog, status } = useAnalysisStore();
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reasoningLog]);

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-4">
        <Terminal className="w-5 h-5 text-green-400" />
        <h2 className="font-semibold">Live Reasoning Log</h2>
        {status === 'running' && (
          <span className="ml-auto flex items-center gap-1">
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            <span className="text-xs text-gray-400">Live</span>
          </span>
        )}
      </div>
      
      <div className="bg-gray-900 rounded-lg p-3 h-96 overflow-y-auto font-mono text-sm">
        {reasoningLog.length === 0 ? (
          <p className="text-gray-500">Waiting for analysis to start...</p>
        ) : (
          reasoningLog.map((entry, index) => (
            <div
              key={index}
              className="py-1 border-b border-gray-800 last:border-0"
            >
              <span className="text-gray-500 mr-2">[{String(index + 1).padStart(2, '0')}]</span>
              <span className={
                entry.includes('[Task Decomposition]') ? 'text-purple-400' :
                entry.includes('[Technical]') ? 'text-blue-400' :
                entry.includes('[Fundamental]') ? 'text-green-400' :
                entry.includes('[Sentiment]') ? 'text-yellow-400' :
                entry.includes('[Risk]') ? 'text-red-400' :
                entry.includes('[Strategic]') ? 'text-cyan-400' :
                entry.includes('[HITL]') ? 'text-orange-400' :
                entry.includes('[Execution]') ? 'text-emerald-400' :
                'text-gray-300'
              }>
                {entry}
              </span>
            </div>
          ))
        )}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}
```

### 6.6 Create frontend/src/components/ApprovalDialog.tsx

```tsx
import React, { useState } from 'react';
import { CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { useAnalysisStore } from '../store';
import { submitApproval } from '../api/client';

export function ApprovalDialog() {
  const {
    showApprovalDialog,
    tradeProposal,
    activeSession,
    setShowApprovalDialog,
    setStatus,
  } = useAnalysisStore();
  
  const [feedback, setFeedback] = useState('');
  const [loading, setLoading] = useState(false);

  if (!showApprovalDialog || !tradeProposal) return null;

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    if (!activeSession) return;
    
    setLoading(true);
    try {
      await submitApproval(activeSession, decision, feedback);
      setShowApprovalDialog(false);
      setStatus(decision === 'approved' ? 'running' : 'completed');
    } catch (error) {
      console.error('Failed to submit approval:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-xl max-w-2xl w-full mx-4 p-6">
        <div className="flex items-center gap-3 mb-6">
          <AlertTriangle className="w-8 h-8 text-yellow-500" />
          <div>
            <h2 className="text-xl font-bold">Trade Approval Required</h2>
            <p className="text-gray-400 text-sm">Review and approve the proposed trade</p>
          </div>
        </div>

        <div className="bg-gray-900 rounded-lg p-4 mb-6">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <span className="text-gray-400 text-sm">Ticker</span>
              <p className="text-xl font-bold">{tradeProposal.ticker}</p>
            </div>
            <div>
              <span className="text-gray-400 text-sm">Action</span>
              <p className={`text-xl font-bold ${
                tradeProposal.action === 'BUY' ? 'text-green-500' :
                tradeProposal.action === 'SELL' ? 'text-red-500' :
                'text-yellow-500'
              }`}>
                {tradeProposal.action}
              </p>
            </div>
            <div>
              <span className="text-gray-400 text-sm">Quantity</span>
              <p className="text-xl font-bold">{tradeProposal.quantity}</p>
            </div>
            <div>
              <span className="text-gray-400 text-sm">Risk Score</span>
              <p className="text-xl font-bold">{(tradeProposal.risk_score * 100).toFixed(0)}%</p>
            </div>
          </div>
          
          <div>
            <span className="text-gray-400 text-sm">Rationale</span>
            <p className="mt-1 text-gray-300 text-sm">{tradeProposal.rationale.slice(0, 500)}...</p>
          </div>
        </div>

        <div className="mb-6">
          <label className="block text-sm text-gray-400 mb-2">Feedback (optional)</label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white"
            rows={2}
            placeholder="Add any notes or modifications..."
          />
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => handleDecision('rejected')}
            disabled={loading}
            className="flex-1 bg-red-600 hover:bg-red-700 disabled:opacity-50 py-3 rounded-lg font-medium flex items-center justify-center gap-2"
          >
            <XCircle className="w-5 h-5" />
            Reject
          </button>
          <button
            onClick={() => handleDecision('approved')}
            disabled={loading}
            className="flex-1 bg-green-600 hover:bg-green-700 disabled:opacity-50 py-3 rounded-lg font-medium flex items-center justify-center gap-2"
          >
            <CheckCircle className="w-5 h-5" />
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
```

### 6.7 Create frontend/src/api/client.ts

```typescript
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

export async function startAnalysis(ticker: string, query?: string) {
  const response = await client.post('/analysis/start', { ticker, query });
  return response.data;
}

export async function getAnalysisStatus(sessionId: string) {
  const response = await client.get(`/analysis/status/${sessionId}`);
  return response.data;
}

export async function submitApproval(
  sessionId: string,
  decision: 'approved' | 'rejected' | 'modified',
  feedback?: string,
  modifications?: Record<string, unknown>
) {
  const response = await client.post('/approval/decide', {
    session_id: sessionId,
    decision,
    feedback,
    modifications,
  });
  return response.data;
}

export async function getPendingApprovals() {
  const response = await client.get('/approval/pending');
  return response.data;
}
```

### 6.8 Create frontend/src/api/websocket.ts

```typescript
import { useAnalysisStore } from '../store';

let ws: WebSocket | null = null;

export function connectWebSocket(sessionId: string) {
  const store = useAnalysisStore.getState();
  
  if (ws) {
    ws.close();
  }

  ws = new WebSocket(`ws://localhost:8000/ws/session/${sessionId}`);

  ws.onopen = () => {
    console.log('WebSocket connected');
  };

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
      case 'reasoning':
        store.addReasoningEntry(message.data);
        break;
      
      case 'status':
        store.setStatus(message.data.status);
        if (message.data.awaiting_approval) {
          store.setShowApprovalDialog(true);
        }
        break;
      
      case 'proposal':
        store.setTradeProposal(message.data);
        store.setShowApprovalDialog(true);
        break;
      
      case 'position':
        store.setActivePosition(message.data);
        break;
      
      case 'complete':
        store.setStatus(message.data.status);
        break;
    }
  };

  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
    store.setStatus('error');
  };

  ws.onclose = () => {
    console.log('WebSocket closed');
  };

  // Heartbeat
  const pingInterval = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, 30000);

  return () => {
    clearInterval(pingInterval);
    ws?.close();
  };
}
```

---

## 7. Environment Setup Scripts

### 7.1 Create scripts/setup_llm.sh

```bash
#!/bin/bash
# LLM Server Setup Script

set -e

MODEL=${1:-"deepseek-ai/DeepSeek-R1-Distill-Llama-70B"}
PORT=${2:-8080}

echo "=== Agentic Trading LLM Setup ==="
echo "Model: $MODEL"
echo "Port: $PORT"

# Check for NVIDIA GPU
if ! nvidia-smi &> /dev/null; then
    echo "ERROR: NVIDIA GPU not detected. This setup requires an RTX 3090 or equivalent."
    exit 1
fi

echo "GPU detected:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

# Option 1: vLLM (Recommended for production)
setup_vllm() {
    echo "Setting up vLLM..."
    
    # Install vLLM
    pip install vllm
    
    # Start server with AWQ quantization for 24GB VRAM
    python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL" \
        --quantization awq \
        --max-model-len 8192 \
        --gpu-memory-utilization 0.95 \
        --host 0.0.0.0 \
        --port "$PORT" &
    
    echo "vLLM server starting on port $PORT..."
}

# Option 2: Ollama (Simpler setup)
setup_ollama() {
    echo "Setting up Ollama..."
    
    # Install Ollama if not present
    if ! command -v ollama &> /dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    
    # Pull model (using smaller quantized version)
    ollama pull deepseek-r1:70b-q4_K_M
    
    # Start server
    OLLAMA_HOST=0.0.0.0:$PORT ollama serve &
    
    echo "Ollama server starting on port $PORT..."
}

# Choose setup method
echo ""
echo "Select LLM server:"
echo "1) vLLM (Recommended - better throughput)"
echo "2) Ollama (Simpler setup)"
read -p "Choice [1]: " choice

case ${choice:-1} in
    1) setup_vllm ;;
    2) setup_ollama ;;
    *) echo "Invalid choice"; exit 1 ;;
esac

# Wait and test
echo "Waiting for server to start..."
sleep 10

# Test endpoint
if curl -s "http://localhost:$PORT/v1/models" > /dev/null; then
    echo "✓ LLM server is running!"
    curl -s "http://localhost:$PORT/v1/models" | python -m json.tool
else
    echo "✗ Server not responding. Check logs for errors."
fi
```

### 7.2 Create .env.example

```bash
# LLM Configuration
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=deepseek-ai/DeepSeek-R1-Distill-Llama-70B
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=4096

# Market Data
MARKET_DATA_MODE=live  # "live" or "mock"

# Redis
REDIS_URL=redis://localhost:6379

# API Settings
API_HOST=0.0.0.0
API_PORT=8000

# Environment
ENVIRONMENT=development
DEBUG=true
```

---

## 8. Quick Start Commands

After Claude Code creates all files, run these commands to start the system:

```bash
# 1. Start LLM server (in separate terminal)
chmod +x scripts/setup_llm.sh
./scripts/setup_llm.sh

# 2. Start backend (in separate terminal)
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
uvicorn app.main:app --reload --port 8000

# 3. Start frontend (in separate terminal)
cd frontend
npm install
npm run dev

# 4. Or use Docker Compose for everything
docker-compose up --build
```

---

## 9. Verification Checklist

After setup, verify:

- [ ] LLM server responds: `curl http://localhost:8080/v1/models`
- [ ] Backend health: `curl http://localhost:8000/health`
- [ ] Frontend loads: `http://localhost:3000`
- [ ] WebSocket connects (check browser console)
- [ ] Analysis starts when ticker submitted
- [ ] Reasoning log streams in real-time
- [ ] Approval dialog appears at HITL checkpoint
- [ ] Trade executes after approval

---

## 10. Important Notes for Claude Code

1. **DeepAgents Integration**: The `write_todos` tool pattern is implemented in `tools/write_todos.py`. If using the actual DeepAgents library, adjust imports accordingly.

2. **LangGraph Checkpointing**: For production, replace `MemorySaver` with `RedisCheckpointer` for persistent state across restarts.

3. **Error Handling**: Add comprehensive try/catch blocks and graceful degradation throughout.

4. **Security**: Before production, add authentication, rate limiting, and input validation.

5. **Testing**: Create unit tests for each subagent and integration tests for the full workflow.

6. **Model Alternatives**: If DeepSeek-R1 doesn't fit in 24GB VRAM, try:
   - Llama 3.1 70B with 4-bit quantization
   - Qwen2.5-72B-Instruct-AWQ
   - Mixtral 8x22B with 4-bit quantization

Now proceed to create all files in the project structure and implement the system.
