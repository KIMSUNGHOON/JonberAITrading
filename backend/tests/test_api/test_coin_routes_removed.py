"""코인 HTTP 표면이 등록에서 빠졌는지 확인한다.

동결(1단계)은 구현 코드를 지우지 않고 진입점만 끊는다. 그래서 이 테스트는
`routes/coin/` 모듈의 존재 여부가 아니라 **앱에 마운트됐는지**를 본다.
"""
from app.main import app


def _paths() -> set[str]:
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_coin_routes_are_not_mounted():
    coin_paths = [p for p in _paths() if "/coin" in p]
    assert coin_paths == [], f"코인 라우트가 아직 마운트돼 있다: {coin_paths}"


def test_kr_and_trading_routes_survive():
    paths = _paths()
    assert any("/kr_stocks" in p for p in paths)
    assert any("/trading" in p for p in paths)


import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "app.api.routes.coin",
        "app.api.schemas.coin",
        "services.upbit",
        "agents.graph.coin_trading_graph",
        "agents.graph.coin_state",
        "agents.graph.coin_nodes",
    ],
)
def test_coin_modules_are_gone(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_approval_module_imports_without_coin_graph():
    """HITL 승인 경로가 코인 그래프 없이도 import된다."""
    mod = importlib.import_module("app.api.routes.approval")
    assert not hasattr(mod, "get_coin_trading_graph")
