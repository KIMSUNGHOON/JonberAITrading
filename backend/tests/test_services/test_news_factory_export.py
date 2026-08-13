"""`create_news_service` 팩토리가 실제로 export되는지 -- 목 없이.

2026-08-13 EOD 라이브 로그: `discovery_news_service_unavailable
error="cannot import name 'create_news_service' from 'services.news'..."`.
`services/news/__init__.py`가 `NewsService`만 export하고 팩토리 함수
`create_news_service`(정의는 `services/news/service.py:242`)는 export하지
않아서, 뉴스 주입이 배포 이후 한 번도 작동하지 않았다.

두 호출부(`services/discovery/orchestrator.py::_make_news_fetch`,
`services/reports/collect.py::make_news_fetch`)가 이 import를 지역
try/except로 감싸고 실패하면 `None`을 돌려주는 바람에, 팩토리를 mock으로
주입하는 기존 테스트들은 이 버그를 잡지 못했다(fetch 자체를 갈아끼워서
import 문을 절대 안 탔다).

여기서는 목을 쓰지 않는다 -- import 자체와 두 호출부의 반환값이 `None`이
아님만 확인한다. 팩토리를 실제로 **호출**하면 네이버 API 클라이언트를
띄워 네트워크를 탈 수 있으므로 호출하지 않는다(만들기만 하고 부르지
않는다).
"""


def test_create_news_service_is_importable_from_package_root():
    """회귀 가드 핵심 -- 이 import 문 자체가 라이브에서 실패했던 그것."""
    from services.news import create_news_service

    assert callable(create_news_service)


def test_create_news_service_is_the_real_factory():
    from services.news import create_news_service
    from services.news.service import create_news_service as _direct

    assert create_news_service is _direct


def test_discovery_orchestrator_news_fetch_factory_available():
    """`_make_news_fetch()`가 `None`을 돌려주면 발굴 뉴스 주입이 조용히
    꺼진다 -- import가 살아있으면 `None`이 아닌 콜러블을 돌려줘야 한다."""
    from services.discovery.orchestrator import _make_news_fetch

    fetch = _make_news_fetch()
    assert fetch is not None
    assert callable(fetch)


def test_reports_collect_news_fetch_factory_available():
    """같은 회귀 가드, 리포트 수집 쪽."""
    from services.reports.collect import make_news_fetch

    fetch = make_news_fetch()
    assert fetch is not None
    assert callable(fetch)
