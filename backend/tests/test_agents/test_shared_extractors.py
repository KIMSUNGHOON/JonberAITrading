"""KR extractors keep their Korean-specific logic.

코인 스택 제거(2026-08-01) 이전에는 이 파일이 `agents/graph/shared_extractors.py`
(US+coin 공용 추출기)와 KR 전용 추출기가 동일 입력에 다르게 반응하는지
대조했다. `shared_extractors.py`의 유일한 실사용처(`coin_nodes.py`)가
이번 태스크로 삭제돼 그 모듈 자체가 고아 코드가 됐으므로 모듈과 그 대조
테스트(`test_shared_extractors_behavior`)를 함께 지웠다. 남은
`test_kr_helpers_keep_korean_logic`은 `kr_stock_nodes/helpers.py`(살아있는
KR 경로)의 유일한 커버리지라 파일째 지우지 않고 남긴다."""
import app.api.routes  # noqa: F401  # prime the graph-package circular import

from agents.graph.kr_stock_nodes.helpers import (
    _extract_bull_case as kr_bull, _extract_key_factors as kr_factors,
)


def test_kr_helpers_keep_korean_logic():
    # KR must still match Korean keywords / middle-dot bullets (NOT merged)
    assert kr_bull("종목 상승 기대") != ""
    assert kr_factors("· 한국형 불릿 항목입니다") == ["한국형 불릿 항목입니다"]
