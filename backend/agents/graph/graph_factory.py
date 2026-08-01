"""Shared builder for market trading graphs (P4 consolidation).

Originally shared by 3 stacks (KR / US / coin) that all assembled the SAME
topology — entry -> 4 sequential analyses -> decision -> approval (HITL
interrupt) -> {execute | re_analyze | end}; only the state type, node
functions, entry-node name and the 2nd-analysis label differed. The US stack
(R2, 2026-07-11) and coin stack (2026-08-01 Upbit 제거) were both removed,
so `kr_stock_graph.py` is the sole caller now — kept generic rather than
inlined, since nothing about the remaining call site requires collapsing it.
This is a leaf module: it imports ONLY langgraph (no stack-specific modules)
so it never introduces an import cycle.
"""

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph


def build_analysis_graph(
    state_type,
    *,
    entry_node,       # (name, fn) — "data_collection" for the surviving KR stack
                      # (was "decompose" for the now-removed US stack; coin used
                      # "data_collection" too before its 2026-08-01 removal)
    analysis_nodes,   # [(name, fn), ...] in order: technical, 2nd, sentiment, risk
    decision_node,
    approval_node,
    re_analyze_node,
    execute_node,
    cond_fn,          # should_continue_*_execution -> "execute" | "re_analyze" | "end"
) -> StateGraph:
    """Assemble the shared analysis -> approval -> execute StateGraph (uncompiled)."""
    workflow = StateGraph(state_type)

    entry_name, entry_fn = entry_node
    workflow.add_node(entry_name, entry_fn)
    for name, fn in analysis_nodes:
        workflow.add_node(name, fn)
    workflow.add_node("decision", decision_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("re_analyze", re_analyze_node)
    workflow.add_node("execute", execute_node)

    workflow.set_entry_point(entry_name)

    # entry -> technical -> 2nd -> sentiment -> risk -> decision -> approval
    prev = entry_name
    for name, _ in analysis_nodes:
        workflow.add_edge(prev, name)
        prev = name
    workflow.add_edge(prev, "decision")
    workflow.add_edge("decision", "approval")

    workflow.add_conditional_edges(
        "approval",
        cond_fn,
        {"execute": "execute", "re_analyze": "re_analyze", "end": END},
    )

    # Re-analysis loops back to the entry node for a fresh pass; execute -> END
    workflow.add_edge("re_analyze", entry_name)
    workflow.add_edge("execute", END)

    return workflow


def compile_analysis_graph(
    workflow: StateGraph,
    checkpointer: Optional[MemorySaver] = None,
    *,
    interrupt_before_approval: bool = True,
) -> StateGraph:
    """Compile a built graph with a checkpointer and the HITL interrupt."""
    if checkpointer is None:
        checkpointer = MemorySaver()
    interrupt_before = ["approval"] if interrupt_before_approval else []
    return workflow.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
