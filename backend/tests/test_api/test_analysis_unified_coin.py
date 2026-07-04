"""Regression: the coin branch of unified analysis must import a real module."""
import importlib
import inspect

import pytest


def test_coin_branch_imports_real_graph_module():
    # app.api.routes must load first to resolve the graph package circular import
    import app.api.routes  # noqa: F401

    # The WRONG module the bug used must not exist...
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agents.graph.coin_graph")

    # ...and the REAL one must import and expose the callable.
    mod = importlib.import_module("agents.graph.coin_trading_graph")
    assert hasattr(mod, "get_coin_trading_graph")


def test_analysis_unified_source_uses_correct_module():
    import app.api.routes.analysis_unified as m

    src = inspect.getsource(m)
    assert "agents.graph.coin_graph import" not in src
    assert "agents.graph.coin_trading_graph import get_coin_trading_graph" in src
    # coin branch should build state via the canonical factory, like coin/analysis.py
    assert "create_coin_initial_state" in src
