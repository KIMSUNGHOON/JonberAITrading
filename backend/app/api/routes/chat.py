"""
Chat API Routes

Endpoints for Trading Assistant Discussion feature.
Provides conversational AI for trading-related questions.

Phase 13: Enhanced context support for better conversation continuity.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

import structlog
from fastapi import APIRouter, HTTPException, status

from agents.llm_provider import get_llm_provider
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = structlog.get_logger()
router = APIRouter()


# -------------------------------------------
# Request/Response Models
# -------------------------------------------


class ChatMessage(BaseModel):
    """Single chat message."""
    role: str  # "user" or "assistant"
    content: str


class ActiveAnalysis(BaseModel):
    """Currently active or most recent analysis."""
    ticker: str
    displayName: str
    marketType: str  # "kiwoom" (2026-08-01 Upbit 제거: "stock"/"coin"는 더 이상 오지 않는다)
    status: str  # "running", "completed", "cancelled", "error"
    recommendation: Optional[str] = None  # "BUY", "SELL", "HOLD"
    confidence: Optional[float] = None  # 0-100
    currentPrice: Optional[float] = None
    entryPrice: Optional[float] = None
    stopLoss: Optional[float] = None
    takeProfit: Optional[float] = None
    keySignals: Optional[List[str]] = None


class TradeDecision(BaseModel):
    """A trade decision made by the user."""
    ticker: str
    displayName: str
    action: str  # "approved" or "rejected"
    tradeAction: str  # "BUY", "SELL", "HOLD"
    timestamp: str
    quantity: Optional[int] = None
    price: Optional[float] = None
    rationale: Optional[str] = None


class TradingContext(BaseModel):
    """Structured trading context for enhanced conversation."""
    activeAnalysis: Optional[ActiveAnalysis] = None
    recentDecisions: List[TradeDecision] = Field(default_factory=list)
    positions: Optional[List[Dict[str, Any]]] = None  # Current portfolio positions


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    context: Optional[str] = None  # Legacy: Simple string context
    tradingContext: Optional[TradingContext] = None  # Phase 13: Structured context
    history: Optional[List[ChatMessage]] = None  # Previous conversation history


class ChatResponse(BaseModel):
    """Chat response model."""
    message: str
    role: str = "assistant"


# -------------------------------------------
# System Prompts
# -------------------------------------------


TRADING_ASSISTANT_PROMPT = """You are a helpful Trading Assistant AI for an automated trading platform.
You help users understand market analysis, trading strategies, and their portfolio.

Your capabilities:
- Answer questions about technical analysis, fundamental analysis, and market sentiment
- Explain trading concepts and strategies
- Provide insights about specific Korean stocks
- Help users understand risk management
- Clarify trade proposals and rationale

Guidelines:
- Be concise but informative
- Match the user's language
- Don't provide specific financial advice or guarantees
- If you don't know something, say so honestly
- When discussing prices, use KRW (₩)
- Reference the trading context provided to give relevant, personalized responses
- When the user asks about "this stock" or "the analysis", refer to the active analysis context"""


# -------------------------------------------
# Context Formatting
# -------------------------------------------


def _format_trading_context(ctx: TradingContext) -> str:
    """Format structured trading context into human-readable text."""
    sections = []

    # Active Analysis
    # (2026-08-01 Upbit 제거: marketType은 이제 프론트에서 'kiwoom'만 보낸다
    # — "stock"(US, R2 제거)·"coin"(Upbit, 이번 아크 제거) 분기는 죽은 코드라
    # market_label·currency 둘 다 단일 시장으로 단순화했다. 방어적으로
    # .get() fallback은 남겨 예상 밖 값이 와도 그대로 표시되게 한다.)
    if ctx.activeAnalysis:
        a = ctx.activeAnalysis
        market_label = {"kiwoom": "KR Stock"}.get(a.marketType, a.marketType)
        lines = [
            "## 현재 분석 중인 종목",
            f"- 종목: {a.displayName} ({a.ticker})",
            f"- 시장: {market_label}",
            f"- 상태: {a.status}",
        ]
        if a.recommendation:
            lines.append(f"- 추천: {a.recommendation}" + (f" (신뢰도: {a.confidence:.0f}%)" if a.confidence else ""))
        currency = "₩"
        if a.currentPrice:
            lines.append(f"- 현재가: {currency}{a.currentPrice:,.0f}")
        if a.entryPrice:
            lines.append(f"- 진입가: {currency}{a.entryPrice:,.0f}")
        if a.stopLoss:
            lines.append(f"- 손절가: {currency}{a.stopLoss:,.0f}")
        if a.takeProfit:
            lines.append(f"- 목표가: {currency}{a.takeProfit:,.0f}")
        if a.keySignals:
            lines.append("- 주요 시그널: " + ", ".join(a.keySignals[:3]))
        sections.append("\n".join(lines))

    # Recent Decisions
    if ctx.recentDecisions:
        lines = ["## 최근 거래 결정"]
        for d in ctx.recentDecisions[:5]:
            action_kr = "승인" if d.action == "approved" else "거절"
            # (2026-08-01 Upbit 제거 전에는 가격대로 KRW/USD를 추정하는
            # 휴리스틱이었다 — 저가 KR 종목을 오분류할 수 있는 버그였고,
            # 이제 시장이 KR 하나뿐이라 애초에 불필요.)
            currency = "₩"
            line = f"- {d.displayName} ({d.ticker}): {d.tradeAction} {action_kr}"
            if d.quantity and d.price:
                line += f" - {d.quantity}주 @ {currency}{d.price:,.0f}"
            lines.append(line)
        sections.append("\n".join(lines))

    # Positions
    if ctx.positions:
        lines = ["## 현재 보유 포지션"]
        for p in ctx.positions[:5]:
            ticker = p.get("ticker") or p.get("stk_cd", "")
            name = p.get("displayName") or p.get("stk_nm", ticker)
            qty = p.get("quantity", 0)
            if qty != 0:
                lines.append(f"- {name}: {qty}주")
        if len(lines) > 1:  # Has at least one position
            sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else ""


# -------------------------------------------
# Endpoints
# -------------------------------------------


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message to the Trading Assistant.

    Args:
        request: Chat request with message and optional context/history

    Returns:
        Assistant's response
    """
    try:
        llm = get_llm_provider()

        # Build message history
        messages = [SystemMessage(content=TRADING_ASSISTANT_PROMPT)]

        # Add structured trading context (Phase 13)
        if request.tradingContext:
            formatted_context = _format_trading_context(request.tradingContext)
            if formatted_context:
                messages.append(SystemMessage(content=f"## 현재 트레이딩 상황\n\n{formatted_context}"))
                logger.debug("chat_with_trading_context", has_analysis=bool(request.tradingContext.activeAnalysis))

        # Add legacy simple context if provided (backwards compatibility)
        elif request.context:
            messages.append(SystemMessage(content=f"Current analysis context:\n{request.context}"))

        # Add conversation history if provided
        if request.history:
            for msg in request.history[-10:]:  # Keep last 10 messages for context
                if msg.role == "user":
                    messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    messages.append(AIMessage(content=msg.content))

        # Add current message
        messages.append(HumanMessage(content=request.message))

        logger.debug("chat_request", message_count=len(messages))

        # Generate response
        response = await llm.generate(messages)

        logger.info("chat_response_generated", response_length=len(response))

        return ChatResponse(
            message=response.strip(),
            role="assistant",
        )

    except Exception as e:
        logger.error("chat_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {str(e)}",
        )
