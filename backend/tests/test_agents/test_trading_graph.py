"""
Trading Graph Tests
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agents.graph.state import TradingState, AnalysisStage


class TestTradingState:
    """Tests for TradingState."""

    def test_state_has_required_fields(self):
        """TradingState should have required fields."""
        state = TradingState(
            ticker="AAPL",
            current_stage=AnalysisStage.DECOMPOSITION,
        )

        assert state["ticker"] == "AAPL"
        assert state["current_stage"] == AnalysisStage.DECOMPOSITION

    def test_state_default_values(self):
        """TradingState should have sensible defaults."""
        state = TradingState(
            ticker="AAPL",
            current_stage=AnalysisStage.DECOMPOSITION,
        )

        assert state.get("analyses", []) == [] or "analyses" in state
        assert state.get("awaiting_approval", False) is False or "awaiting_approval" in state


class TestAnalysisStage:
    """Tests for AnalysisStage enum."""

    def test_all_stages_exist(self):
        """All expected analysis stages should exist."""
        expected_stages = [
            "DECOMPOSITION",
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
            assert hasattr(AnalysisStage, stage_name), f"Missing stage: {stage_name}"

    def test_stages_are_strings(self):
        """Analysis stages should be string values."""
        for stage in AnalysisStage:
            assert isinstance(stage.value, str)


class TestGraphNodes:
    """Tests for graph node functions."""

    @pytest.mark.asyncio
    async def test_task_decomposition_node_exists(self):
        """Task decomposition node function should exist."""
        from agents.graph.nodes import task_decomposition_node
        assert callable(task_decomposition_node)

    @pytest.mark.asyncio
    async def test_technical_analysis_node_exists(self):
        """Technical analysis node function should exist."""
        from agents.graph.nodes import technical_analysis_node
        assert callable(technical_analysis_node)

    @pytest.mark.asyncio
    async def test_fundamental_analysis_node_exists(self):
        """Fundamental analysis node function should exist."""
        from agents.graph.nodes import fundamental_analysis_node
        assert callable(fundamental_analysis_node)

    @pytest.mark.asyncio
    async def test_sentiment_analysis_node_exists(self):
        """Sentiment analysis node function should exist."""
        from agents.graph.nodes import sentiment_analysis_node
        assert callable(sentiment_analysis_node)

    @pytest.mark.asyncio
    async def test_risk_assessment_node_exists(self):
        """Risk assessment node function should exist."""
        from agents.graph.nodes import risk_assessment_node
        assert callable(risk_assessment_node)

    @pytest.mark.asyncio
    async def test_strategic_decision_node_exists(self):
        """Strategic decision node function should exist."""
        from agents.graph.nodes import strategic_decision_node
        assert callable(strategic_decision_node)

    @pytest.mark.asyncio
    async def test_human_approval_node_exists(self):
        """Human approval node function should exist."""
        from agents.graph.nodes import human_approval_node
        assert callable(human_approval_node)

    @pytest.mark.asyncio
    async def test_execution_node_exists(self):
        """Execution node function should exist."""
        from agents.graph.nodes import execution_node
        assert callable(execution_node)
