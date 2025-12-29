"""
Korean Stock Trading Graph Tests

Tests for:
- KRStockTradingState
- KRStockAnalysisStage
- Graph node functions
- State helpers
- Technical indicator calculation
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

import numpy as np
import pandas as pd

from agents.graph.kr_stock_state import (
    KRStockTradingState,
    KRStockAnalysisStage,
    KRStockAnalysisResult,
    KRStockTradeProposal,
    KRStockPosition,
    SignalType,
    TradeAction,
    create_kr_stock_initial_state,
    add_kr_stock_reasoning_log,
    get_all_kr_stock_analyses,
    kr_stock_analysis_dict_to_context_string,
    calculate_kr_stock_consensus_signal,
)


class TestKRStockTradingState:
    """Tests for KRStockTradingState."""

    def test_state_has_required_fields(self):
        """KRStockTradingState should have required fields."""
        state = KRStockTradingState(
            stk_cd="005930",
            current_stage=KRStockAnalysisStage.DATA_COLLECTION,
        )

        assert state["stk_cd"] == "005930"
        assert state["current_stage"] == KRStockAnalysisStage.DATA_COLLECTION

    def test_create_initial_state(self):
        """create_kr_stock_initial_state should create valid state."""
        state = create_kr_stock_initial_state(
            stk_cd="005930",
            stk_nm="삼성전자",
            user_query="삼성전자 분석",
        )

        assert state["stk_cd"] == "005930"
        assert state["stk_nm"] == "삼성전자"
        assert state["user_query"] == "삼성전자 분석"
        assert state["current_stage"] == KRStockAnalysisStage.DATA_COLLECTION
        assert state["awaiting_approval"] is False
        assert state["reasoning_log"] == []

    def test_create_initial_state_with_default_query(self):
        """create_kr_stock_initial_state should create default query."""
        state = create_kr_stock_initial_state(
            stk_cd="005930",
            stk_nm="삼성전자",
        )

        assert "삼성전자" in state["user_query"]


class TestKRStockAnalysisStage:
    """Tests for KRStockAnalysisStage enum."""

    def test_all_stages_exist(self):
        """All expected analysis stages should exist."""
        expected_stages = [
            "DATA_COLLECTION",
            "TECHNICAL",
            "FUNDAMENTAL",
            "SENTIMENT",
            "RISK",
            "SYNTHESIS",
            "APPROVAL",
            "EXECUTION",
            "COMPLETE",
        ]

        for stage_name in expected_stages:
            assert hasattr(KRStockAnalysisStage, stage_name), f"Missing stage: {stage_name}"

    def test_stages_are_strings(self):
        """Analysis stages should be string values."""
        for stage in KRStockAnalysisStage:
            assert isinstance(stage.value, str)


class TestSignalType:
    """Tests for SignalType enum."""

    def test_all_signals_exist(self):
        """All expected signal types should exist."""
        expected_signals = [
            "STRONG_BUY",
            "BUY",
            "HOLD",
            "SELL",
            "STRONG_SELL",
        ]

        for signal_name in expected_signals:
            assert hasattr(SignalType, signal_name), f"Missing signal: {signal_name}"


class TestTradeAction:
    """Tests for TradeAction enum."""

    def test_all_actions_exist(self):
        """All expected trade actions should exist."""
        expected_actions = ["BUY", "SELL", "HOLD"]

        for action_name in expected_actions:
            assert hasattr(TradeAction, action_name), f"Missing action: {action_name}"


class TestKRStockAnalysisResult:
    """Tests for KRStockAnalysisResult model."""

    def test_analysis_result_creation(self):
        """Should create analysis result with required fields."""
        result = KRStockAnalysisResult(
            agent_type="technical",
            stk_cd="005930",
            stk_nm="삼성전자",
            signal=SignalType.BUY,
            confidence=0.75,
            summary="기술적 분석 요약",
            reasoning="상세 분석 내용",
        )

        assert result.agent_type == "technical"
        assert result.stk_cd == "005930"
        assert result.stk_nm == "삼성전자"
        assert result.signal == SignalType.BUY
        assert result.confidence == 0.75

    def test_analysis_result_to_context_string(self):
        """to_context_string should format result properly."""
        result = KRStockAnalysisResult(
            agent_type="technical",
            stk_cd="005930",
            stk_nm="삼성전자",
            signal=SignalType.BUY,
            confidence=0.75,
            summary="기술적 분석 요약",
            key_factors=["RSI 과매도", "골든크로스"],
        )

        context = result.to_context_string()

        assert "TECHNICAL" in context
        assert "삼성전자" in context
        assert "005930" in context
        assert "buy" in context.lower()

    def test_analysis_result_default_values(self):
        """Should have sensible default values."""
        result = KRStockAnalysisResult(
            agent_type="technical",
            stk_cd="005930",
        )

        assert result.signal == SignalType.HOLD
        assert result.confidence == 0.5
        assert result.key_factors == []
        assert result.signals == {}


class TestKRStockTradeProposal:
    """Tests for KRStockTradeProposal model."""

    def test_proposal_creation(self):
        """Should create trade proposal with required fields."""
        proposal = KRStockTradeProposal(
            id="test-123",
            stk_cd="005930",
            stk_nm="삼성전자",
            action=TradeAction.BUY,
            quantity=100,
            entry_price=55000,
            stop_loss=52000,
            take_profit=60000,
        )

        assert proposal.id == "test-123"
        assert proposal.stk_cd == "005930"
        assert proposal.action == TradeAction.BUY
        assert proposal.quantity == 100
        assert proposal.entry_price == 55000

    def test_proposal_default_values(self):
        """Should have sensible default values."""
        proposal = KRStockTradeProposal(
            id="test-123",
            stk_cd="005930",
            action=TradeAction.HOLD,
            quantity=0,
        )

        assert proposal.risk_score == 0.5
        assert proposal.position_size_pct == 5.0
        assert proposal.analyses == []


class TestKRStockPosition:
    """Tests for KRStockPosition model."""

    def test_position_creation(self):
        """Should create position with required fields."""
        position = KRStockPosition(
            stk_cd="005930",
            stk_nm="삼성전자",
            quantity=100,
            entry_price=55000,
            current_price=57000,
        )

        assert position.stk_cd == "005930"
        assert position.quantity == 100

    def test_position_pnl_calculation(self):
        """Should calculate PnL correctly."""
        position = KRStockPosition(
            stk_cd="005930",
            quantity=100,
            entry_price=55000,
            current_price=57000,
        )

        assert position.pnl == 200000  # (57000 - 55000) * 100

    def test_position_pnl_percent_calculation(self):
        """Should calculate PnL percentage correctly."""
        position = KRStockPosition(
            stk_cd="005930",
            quantity=100,
            entry_price=55000,
            current_price=57000,
        )

        assert abs(position.pnl_percent - 3.636) < 0.01  # ~3.64%

    def test_position_negative_pnl(self):
        """Should handle negative PnL correctly."""
        position = KRStockPosition(
            stk_cd="005930",
            quantity=100,
            entry_price=55000,
            current_price=52000,
        )

        assert position.pnl == -300000
        assert position.pnl_percent < 0


class TestStateHelpers:
    """Tests for state helper functions."""

    def test_add_reasoning_log(self):
        """Should add message to reasoning log."""
        state = {"reasoning_log": ["Previous log"]}
        new_log = add_kr_stock_reasoning_log(state, "New message")

        assert len(new_log) == 2
        assert "New message" in new_log[1]

    def test_add_reasoning_log_empty_state(self):
        """Should handle empty reasoning log."""
        state = {}
        new_log = add_kr_stock_reasoning_log(state, "First message")

        assert len(new_log) == 1
        assert "First message" in new_log[0]

    def test_get_all_analyses(self):
        """Should get all completed analyses."""
        state = {
            "technical_analysis": {"agent_type": "technical", "signal": "buy"},
            "fundamental_analysis": {"agent_type": "fundamental", "signal": "hold"},
            "sentiment_analysis": None,
            "risk_assessment": {"agent_type": "risk", "signal": "hold"},
        }

        analyses = get_all_kr_stock_analyses(state)

        assert len(analyses) == 3
        assert any(a["agent_type"] == "technical" for a in analyses)
        assert any(a["agent_type"] == "fundamental" for a in analyses)
        assert any(a["agent_type"] == "risk" for a in analyses)

    def test_analysis_dict_to_context_string(self):
        """Should convert analysis dict to context string."""
        analysis = {
            "agent_type": "technical",
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "signal": "buy",
            "confidence": 0.75,
            "summary": "기술적 분석 요약",
            "key_factors": ["RSI 과매도"],
            "reasoning": "상세 분석",
        }

        context = kr_stock_analysis_dict_to_context_string(analysis)

        assert "TECHNICAL" in context
        assert "삼성전자" in context
        assert "buy" in context.lower()
        assert "75%" in context

    def test_calculate_consensus_signal_buy(self):
        """Should calculate buy consensus."""
        analyses = [
            {"signal": "buy", "confidence": 0.8},
            {"signal": "buy", "confidence": 0.7},
            {"signal": "hold", "confidence": 0.6},
        ]

        consensus, confidence = calculate_kr_stock_consensus_signal(analyses)

        assert consensus == SignalType.BUY
        assert confidence > 0.6

    def test_calculate_consensus_signal_hold(self):
        """Should calculate hold consensus for mixed signals."""
        analyses = [
            {"signal": "buy", "confidence": 0.7},
            {"signal": "sell", "confidence": 0.7},
            {"signal": "hold", "confidence": 0.7},
        ]

        consensus, confidence = calculate_kr_stock_consensus_signal(analyses)

        assert consensus == SignalType.HOLD

    def test_calculate_consensus_signal_empty(self):
        """Should return HOLD for empty analyses."""
        consensus, confidence = calculate_kr_stock_consensus_signal([])

        assert consensus == SignalType.HOLD
        assert confidence == 0.0


class TestGraphNodes:
    """Tests for Korean stock graph node functions existence."""

    @pytest.mark.asyncio
    async def test_data_collection_node_exists(self):
        """Data collection node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_data_collection_node
        assert callable(kr_stock_data_collection_node)

    @pytest.mark.asyncio
    async def test_technical_analysis_node_exists(self):
        """Technical analysis node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_technical_analysis_node
        assert callable(kr_stock_technical_analysis_node)

    @pytest.mark.asyncio
    async def test_fundamental_analysis_node_exists(self):
        """Fundamental analysis node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_fundamental_analysis_node
        assert callable(kr_stock_fundamental_analysis_node)

    @pytest.mark.asyncio
    async def test_sentiment_analysis_node_exists(self):
        """Sentiment analysis node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_sentiment_analysis_node
        assert callable(kr_stock_sentiment_analysis_node)

    @pytest.mark.asyncio
    async def test_risk_assessment_node_exists(self):
        """Risk assessment node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_risk_assessment_node
        assert callable(kr_stock_risk_assessment_node)

    @pytest.mark.asyncio
    async def test_strategic_decision_node_exists(self):
        """Strategic decision node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_strategic_decision_node
        assert callable(kr_stock_strategic_decision_node)

    @pytest.mark.asyncio
    async def test_human_approval_node_exists(self):
        """Human approval node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_human_approval_node
        assert callable(kr_stock_human_approval_node)

    @pytest.mark.asyncio
    async def test_execution_node_exists(self):
        """Execution node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_execution_node
        assert callable(kr_stock_execution_node)

    @pytest.mark.asyncio
    async def test_re_analyze_node_exists(self):
        """Re-analyze node function should exist."""
        from agents.graph.kr_stock_nodes import kr_stock_re_analyze_node
        assert callable(kr_stock_re_analyze_node)


class TestGraphCreation:
    """Tests for graph creation functions."""

    def test_create_kr_stock_trading_graph(self):
        """Should create trading graph."""
        from agents.graph.kr_stock_graph import create_kr_stock_trading_graph
        graph = create_kr_stock_trading_graph()
        assert graph is not None

    def test_compile_kr_stock_trading_graph(self):
        """Should compile trading graph."""
        from agents.graph.kr_stock_graph import compile_kr_stock_trading_graph
        compiled = compile_kr_stock_trading_graph()
        assert compiled is not None

    def test_get_kr_stock_trading_graph_singleton(self):
        """Should return singleton graph."""
        from agents.graph.kr_stock_graph import get_kr_stock_trading_graph, reset_kr_stock_trading_graph

        reset_kr_stock_trading_graph()
        graph1 = get_kr_stock_trading_graph()
        graph2 = get_kr_stock_trading_graph()

        assert graph1 is graph2


class TestTechnicalIndicators:
    """Tests for Korean stock technical indicator calculation."""

    def test_calculate_indicators_with_valid_data(self):
        """Should calculate indicators from valid data."""
        from agents.tools.kr_market_data import calculate_kr_technical_indicators

        # Create mock price data
        dates = pd.date_range(end=datetime.now(), periods=100, freq="B")
        np.random.seed(42)
        prices = 50000 + np.cumsum(np.random.randn(100) * 500)

        df = pd.DataFrame({
            "open": prices * 0.998,
            "high": prices * 1.01,
            "low": prices * 0.99,
            "close": prices,
            "volume": np.random.randint(100000, 1000000, 100),
        }, index=dates)

        indicators = calculate_kr_technical_indicators(df)

        assert "current_price" in indicators
        assert "rsi" in indicators
        assert "sma_20" in indicators
        assert "trend" in indicators
        assert "macd" in indicators
        assert "bollinger" in indicators

    def test_calculate_indicators_with_empty_data(self):
        """Should return empty dict for empty data."""
        from agents.tools.kr_market_data import calculate_kr_technical_indicators

        df = pd.DataFrame()
        indicators = calculate_kr_technical_indicators(df)

        assert indicators == {}

    def test_calculate_indicators_with_insufficient_data(self):
        """Should return empty dict for insufficient data."""
        from agents.tools.kr_market_data import calculate_kr_technical_indicators

        df = pd.DataFrame({
            "close": [50000, 51000, 52000],
            "volume": [100000, 110000, 120000],
        })
        indicators = calculate_kr_technical_indicators(df)

        assert indicators == {}


class TestKRMarketData:
    """Tests for Korean market data functions."""

    def test_format_kr_market_data_for_llm(self):
        """Should format market data for LLM."""
        from agents.tools.kr_market_data import format_kr_market_data_for_llm

        stock_info = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_prc": 55000,
            "prdy_vrss": 1000,
            "prdy_ctrt": 1.85,
            "acml_vol": 10000000,
            "strt_prc": 54000,
            "high_prc": 56000,
            "low_prc": 53500,
        }

        df = pd.DataFrame()
        result = format_kr_market_data_for_llm(stock_info, df)

        assert "삼성전자" in result
        assert "005930" in result
        assert "55,000" in result or "55000" in result

    def test_mock_kr_stock_info(self):
        """Mock stock info should have required fields."""
        from agents.tools.kr_market_data import _get_mock_kr_stock_info

        info = _get_mock_kr_stock_info("005930")

        assert info["stk_cd"] == "005930"
        assert "stk_nm" in info
        assert "cur_prc" in info
        assert "per" in info
        assert "pbr" in info

    def test_mock_kr_chart_generation(self):
        """Mock chart should generate valid DataFrame."""
        from agents.tools.kr_market_data import _generate_mock_kr_chart

        df = _generate_mock_kr_chart("005930", days=50)

        assert len(df) == 50
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

        # High should be >= Open, Close
        assert (df["high"] >= df["open"]).all()
        assert (df["high"] >= df["close"]).all()
        # Low should be <= Open, Close
        assert (df["low"] <= df["open"]).all()
        assert (df["low"] <= df["close"]).all()


class TestKRStockPrompts:
    """Tests for Korean stock prompts."""

    def test_technical_analyst_prompt_exists(self):
        """Korean technical analyst prompt should exist."""
        from agents.prompts import KR_STOCK_TECHNICAL_ANALYST_PROMPT
        assert len(KR_STOCK_TECHNICAL_ANALYST_PROMPT) > 100
        assert "기술적" in KR_STOCK_TECHNICAL_ANALYST_PROMPT

    def test_fundamental_analyst_prompt_exists(self):
        """Korean fundamental analyst prompt should exist."""
        from agents.prompts import KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT
        assert len(KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT) > 100
        assert "기본적" in KR_STOCK_FUNDAMENTAL_ANALYST_PROMPT

    def test_sentiment_analyst_prompt_exists(self):
        """Korean sentiment analyst prompt should exist."""
        from agents.prompts import KR_STOCK_SENTIMENT_ANALYST_PROMPT
        assert len(KR_STOCK_SENTIMENT_ANALYST_PROMPT) > 100
        assert "심리" in KR_STOCK_SENTIMENT_ANALYST_PROMPT

    def test_risk_assessor_prompt_exists(self):
        """Korean risk assessor prompt should exist."""
        from agents.prompts import KR_STOCK_RISK_ASSESSOR_PROMPT
        assert len(KR_STOCK_RISK_ASSESSOR_PROMPT) > 100
        assert "리스크" in KR_STOCK_RISK_ASSESSOR_PROMPT

    def test_strategic_decision_prompt_exists(self):
        """Korean strategic decision prompt should exist."""
        from agents.prompts import KR_STOCK_STRATEGIC_DECISION_PROMPT
        assert len(KR_STOCK_STRATEGIC_DECISION_PROMPT) > 100
        assert "결정" in KR_STOCK_STRATEGIC_DECISION_PROMPT
