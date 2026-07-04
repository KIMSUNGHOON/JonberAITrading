"""Phase 1: flatten_messages — the single LangChain<->CLI seam."""
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agents.llm.messages import flatten_messages


def test_flatten_splits_system_and_renders_history():
    sys, user = flatten_messages([
        SystemMessage(content="S1"), SystemMessage(content="S2"),
        HumanMessage(content="H1"), AIMessage(content="A1"), HumanMessage(content="H2"),
    ])
    assert "S1" in sys and "S2" in sys
    assert "H1" in user and "A1" in user and "H2" in user
    # roles are labeled so the CLI model can follow the turn structure
    assert "Human:" in user and "Assistant:" in user


def test_flatten_no_system():
    sys, user = flatten_messages([HumanMessage(content="hi")])
    assert sys == ""
    assert "hi" in user


def test_flatten_coerces_nonstring_content():
    sys, user = flatten_messages([HumanMessage(content=["a", "b"])])
    assert "a" in user  # str(list) rendered, no crash
