"""
Korean Stock Trading Nodes Package

This package provides LangGraph node functions for Korean stock trading workflow.

Modules:
- helpers: Signal determination, confidence calculation, utility functions
- data_collection: Market data collection node
- analysis_nodes: Technical, Fundamental, Sentiment analysis nodes
- parallel_analysis: Parallel analysis node (combined)
- decision_nodes: Risk Assessment, Strategic Decision, Human Approval, Re-analyze nodes
- execution: Execution node and conditional edge
"""

# Import all node functions for backwards compatibility
from .data_collection import kr_stock_data_collection_node
from .analysis_nodes import (
    kr_stock_technical_analysis_node,
    kr_stock_fundamental_analysis_node,
    kr_stock_sentiment_analysis_node,
)
from .parallel_analysis import kr_stock_parallel_analysis_node
from .decision_nodes import (
    kr_stock_risk_assessment_node,
    kr_stock_strategic_decision_node,
    kr_stock_human_approval_node,
    kr_stock_re_analyze_node,
)
from .execution import (
    kr_stock_execution_node,
    should_continue_kr_stock_execution,
    # Execution helper functions
    _normalize_action,
    _is_buy_action,
    _is_sell_action,
    _is_no_trade_action,
    _get_action_korean,
    _calculate_position_quantity_change,
    _calculate_average_price,
)

# Re-export helper functions if needed externally
from .helpers import (
    _get_stk_cd_safely,
    _determine_kr_stock_technical_signal,
    _determine_kr_stock_technical_signal_enhanced,
    _calculate_technical_confidence,
    _determine_kr_fundamental_signal,
    _calculate_kr_stock_risk_score,
    _format_kr_fundamental_data,
    _signal_to_action,
    _signal_to_action_with_position,
    _extract_key_factors,
    _extract_bull_case,
    _extract_bear_case,
    # Core analysis functions (shared between sequential and parallel)
    analyze_technical_core,
    analyze_fundamental_core,
    analyze_sentiment_core,
)

__all__ = [
    # Main node functions
    "kr_stock_data_collection_node",
    "kr_stock_technical_analysis_node",
    "kr_stock_fundamental_analysis_node",
    "kr_stock_sentiment_analysis_node",
    "kr_stock_parallel_analysis_node",
    "kr_stock_risk_assessment_node",
    "kr_stock_strategic_decision_node",
    "kr_stock_human_approval_node",
    "kr_stock_re_analyze_node",
    "kr_stock_execution_node",
    # Conditional edge
    "should_continue_kr_stock_execution",
    # Execution helper functions
    "_normalize_action",
    "_is_buy_action",
    "_is_sell_action",
    "_is_no_trade_action",
    "_get_action_korean",
    "_calculate_position_quantity_change",
    "_calculate_average_price",
    # Analysis helper functions
    "_get_stk_cd_safely",
    "_determine_kr_stock_technical_signal",
    "_determine_kr_stock_technical_signal_enhanced",
    "_calculate_technical_confidence",
    "_determine_kr_fundamental_signal",
    "_calculate_kr_stock_risk_score",
    "_format_kr_fundamental_data",
    "_signal_to_action",
    "_signal_to_action_with_position",
    "_extract_key_factors",
    "_extract_bull_case",
    "_extract_bear_case",
    # Core analysis functions
    "analyze_technical_core",
    "analyze_fundamental_core",
    "analyze_sentiment_core",
]
