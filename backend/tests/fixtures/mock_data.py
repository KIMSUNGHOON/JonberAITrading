"""
Mock Data Fixtures for Testing

Provides sample data for testing various components.
"""

from datetime import datetime, timedelta
from typing import Any

# -------------------------------------------
# Market Data Mocks
# -------------------------------------------

MOCK_OHLCV_DATA = [
    {
        "timestamp": datetime.now() - timedelta(days=i),
        "open": 150.0 + i * 0.5,
        "high": 152.0 + i * 0.5,
        "low": 148.0 + i * 0.5,
        "close": 151.0 + i * 0.5,
        "volume": 1000000 + i * 10000,
    }
    for i in range(30)
]

MOCK_TICKER_INFO = {
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 2500000000000,
        "pe_ratio": 28.5,
        "dividend_yield": 0.005,
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "sector": "Technology",
        "industry": "Internet Services",
        "market_cap": 1800000000000,
        "pe_ratio": 25.3,
        "dividend_yield": 0.0,
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software",
        "market_cap": 2800000000000,
        "pe_ratio": 32.1,
        "dividend_yield": 0.008,
    },
}


# -------------------------------------------
# Analysis Result Mocks
# -------------------------------------------

MOCK_TECHNICAL_ANALYSIS = {
    "agent": "technical",
    "signal": "buy",
    "confidence": 0.75,
    "summary": "Strong bullish momentum with price above 50-day and 200-day moving averages.",
    "indicators": {
        "sma_50": 148.5,
        "sma_200": 142.3,
        "rsi": 58.2,
        "macd": 1.5,
        "macd_signal": 1.2,
    },
}

MOCK_FUNDAMENTAL_ANALYSIS = {
    "agent": "fundamental",
    "signal": "buy",
    "confidence": 0.68,
    "summary": "Solid fundamentals with strong revenue growth and healthy margins.",
    "metrics": {
        "pe_ratio": 28.5,
        "pb_ratio": 45.2,
        "revenue_growth": 0.12,
        "profit_margin": 0.25,
        "debt_to_equity": 1.8,
    },
}

MOCK_SENTIMENT_ANALYSIS = {
    "agent": "sentiment",
    "signal": "hold",
    "confidence": 0.55,
    "summary": "Mixed sentiment with positive news but cautious analyst outlook.",
    "sentiment_score": 0.15,
    "news_count": 24,
}

MOCK_RISK_ASSESSMENT = {
    "agent": "risk",
    "signal": "buy",
    "confidence": 0.70,
    "summary": "Moderate risk with acceptable volatility levels.",
    "risk_score": 5,
    "max_position_size": 100,
    "suggested_stop_loss": 145.0,
}


# -------------------------------------------
# Trade Proposal Mocks
# -------------------------------------------

MOCK_TRADE_PROPOSAL = {
    "id": "proposal-12345",
    "ticker": "AAPL",
    "action": "buy",
    "quantity": 100,
    "entry_price": 150.00,
    "stop_loss": 145.00,
    "take_profit": 160.00,
    "risk_score": 5,
    "rationale": "Strong technical and fundamental indicators support a bullish position.",
}

MOCK_TRADE_PROPOSAL_SELL = {
    "id": "proposal-67890",
    "ticker": "AAPL",
    "action": "sell",
    "quantity": 50,
    "entry_price": 155.00,
    "stop_loss": 160.00,
    "take_profit": 145.00,
    "risk_score": 6,
    "rationale": "Weakening momentum suggests taking profits.",
}


# -------------------------------------------
# Session State Mocks
# -------------------------------------------

MOCK_SESSION_STATE_INITIAL = {
    "ticker": "AAPL",
    "current_stage": "INITIALIZATION",
    "analyses": [],
    "reasoning_log": [],
    "trade_proposal": None,
    "awaiting_approval": False,
    "active_position": None,
}

MOCK_SESSION_STATE_ANALYZING = {
    "ticker": "AAPL",
    "current_stage": "TECHNICAL_ANALYSIS",
    "analyses": [],
    "reasoning_log": [
        "[Technical] Starting price pattern analysis...",
        "[Technical] Calculating moving averages...",
    ],
    "trade_proposal": None,
    "awaiting_approval": False,
    "active_position": None,
}

MOCK_SESSION_STATE_AWAITING = {
    "ticker": "AAPL",
    "current_stage": "AWAITING_APPROVAL",
    "analyses": [
        MOCK_TECHNICAL_ANALYSIS,
        MOCK_FUNDAMENTAL_ANALYSIS,
        MOCK_SENTIMENT_ANALYSIS,
        MOCK_RISK_ASSESSMENT,
    ],
    "reasoning_log": [
        "[Technical] Starting price pattern analysis...",
        "[Technical] Analysis complete: BUY signal (75% confidence)",
        "[Fundamental] Analyzing financial statements...",
        "[Fundamental] Analysis complete: BUY signal (68% confidence)",
        "[Sentiment] Gathering news and social data...",
        "[Sentiment] Analysis complete: HOLD signal (55% confidence)",
        "[Risk] Calculating risk metrics...",
        "[Risk] Analysis complete: Risk score 5/10",
        "[Strategic] Synthesizing analyses...",
        "[Strategic] Trade proposal generated, awaiting approval",
    ],
    "trade_proposal": MOCK_TRADE_PROPOSAL,
    "awaiting_approval": True,
    "active_position": None,
}


# -------------------------------------------
# Position Mocks
# -------------------------------------------

MOCK_POSITION = {
    "ticker": "AAPL",
    "quantity": 100,
    "entry_price": 150.00,
    "current_price": 155.00,
    "pnl": 500.00,
    "pnl_percent": 3.33,
}

MOCK_POSITION_LOSS = {
    "ticker": "AAPL",
    "quantity": 100,
    "entry_price": 150.00,
    "current_price": 145.00,
    "pnl": -500.00,
    "pnl_percent": -3.33,
}


# -------------------------------------------
# Helper Functions
# -------------------------------------------


def get_mock_analysis_result(agent: str) -> dict[str, Any]:
    """Get mock analysis result for a specific agent."""
    results = {
        "technical": MOCK_TECHNICAL_ANALYSIS,
        "fundamental": MOCK_FUNDAMENTAL_ANALYSIS,
        "sentiment": MOCK_SENTIMENT_ANALYSIS,
        "risk": MOCK_RISK_ASSESSMENT,
    }
    return results.get(agent, MOCK_TECHNICAL_ANALYSIS)


def get_mock_ticker_info(ticker: str) -> dict[str, Any]:
    """Get mock ticker info."""
    return MOCK_TICKER_INFO.get(ticker, MOCK_TICKER_INFO["AAPL"])
