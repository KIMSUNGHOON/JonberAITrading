"""P5 S1 regression: re_analyze_node must not AttributeError on a bad enum member.

nodes.py:597 returned current_stage=AnalysisStage.DECOMPOSE, but the enum member
is DECOMPOSITION (state.py:43) — so the reject -> re_analyze path crashed.
"""

from agents.graph.nodes import re_analyze_node
from agents.graph.state import AnalysisStage


async def test_re_analyze_node_sets_decomposition_stage():
    state = {
        "ticker": "005930",
        "user_feedback": "다시 분석해줘",
        "re_analyze_count": 0,
        "reasoning_log": [],
    }
    result = await re_analyze_node(state)
    assert result["current_stage"] == AnalysisStage.DECOMPOSITION
    assert result["re_analyze_count"] == 1
    assert result["technical_analysis"] is None
    assert result["awaiting_approval"] is False
