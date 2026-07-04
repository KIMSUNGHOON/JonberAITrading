"""Phase 1: the /api/llm/stats route is registered (both prefixes)."""
from app.main import app


def test_llm_stats_routes_registered():
    paths = {r.path for r in app.routes}
    assert "/api/llm/stats" in paths
    assert "/api/v1/llm/stats" in paths
