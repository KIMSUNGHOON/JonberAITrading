"""Shared US+coin extractors behave identically; KR keeps its Korean logic."""
import app.api.routes  # noqa: F401  # prime the graph-package circular import

from agents.graph.shared_extractors import (
    extract_key_factors, extract_bull_case, extract_bear_case,
)
from agents.graph.kr_stock_nodes.helpers import (
    _extract_bull_case as kr_bull, _extract_key_factors as kr_factors,
)


def test_shared_extractors_behavior():
    r = "- alpha factor is strong\n2. beta momentum rising\nshort"
    assert extract_key_factors(r) == ["alpha factor is strong", "beta momentum rising"]
    assert extract_bull_case("X bull thesis here").startswith("bull thesis here")
    assert extract_bear_case("no keyword here") == ""


def test_kr_helpers_keep_korean_logic():
    # KR must still match Korean keywords / middle-dot bullets (NOT merged)
    assert kr_bull("종목 상승 기대") != ""
    assert kr_factors("· 한국형 불릿 항목입니다") == ["한국형 불릿 항목입니다"]
