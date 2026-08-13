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
import pytest


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


# ---------------------------------------------------------------------------
# 2026-08-13 최종 브랜치 리뷰 Critical 1: 위 export 수정(40d3043)은 실패
# 지점을 import(어차피 항상 성공했다) -> `search()`로 옮겼을 뿐이다.
# 두 호출부(`services/discovery/orchestrator.py::_make_news_fetch`,
# `services/reports/collect.py::make_news_fetch`)가 여전히
# `create_news_service()`를 **인자 없이** 부르고 있었다 --
# `naver_client_id`/`naver_client_secret`이 없으면(`services/news/
# service.py:242-275`) 프로바이더를 하나도 등록하지 않은 `NewsService`가
# 조용히 반환되고, 뒤이은 `search()`가 첫 줄에서
# `NewsProviderError("none", "No providers registered")`로 죽는다.
#
# `app/dependencies.py::get_news_service()`가 이미 `settings.
# NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`(`.env`에 실재 -- 컨트롤러 확인)과
# 캐시 매니저를 제대로 붙이는 싱글턴이다. 아래 테스트는 두 fetch 팩토리가
# 실제로 그 경로를 타는지 목 없이 확인한다 -- `search()`는 절대 호출하지
# 않는다(네트워크 금지, `.providers`가 비어 있지 않음만 본다).
# ---------------------------------------------------------------------------


def test_discovery_orchestrator_news_fetch_references_get_news_service():
    """구조 가드 -- `_make_news_fetch`가 프로바이더 0개로 귀결되는
    `create_news_service()`가 아니라 `app.dependencies.get_news_service()`를
    참조하는지 소스로 확인한다."""
    import inspect

    from services.discovery.orchestrator import _make_news_fetch

    src = inspect.getsource(_make_news_fetch)
    assert "get_news_service" in src
    assert "create_news_service" not in src


def test_reports_collect_news_fetch_references_get_news_service():
    """같은 구조 가드, 리포트 수집 쪽."""
    import inspect

    from services.reports.collect import make_news_fetch

    src = inspect.getsource(make_news_fetch)
    assert "get_news_service" in src
    assert "create_news_service" not in src


@pytest.mark.asyncio
async def test_news_service_singleton_has_providers_registered(monkeypatch):
    """행동 가드 -- 위 구조 가드가 가리키는 그 함수(`app.dependencies.
    get_news_service`)가, NAVER 자격증명이 있을 때 실제로 프로바이더를
    등록하는지. `search()`는 호출하지 않는다(네트워크 없음) --
    `.providers`가 비어 있지 않음만 본다.

    자격증명 유무는 gitignore된 `.env`에 달려 있고 `git worktree`는
    `.env`를 복사하지 않는다 -- 이 프로젝트 규칙("전체 스위트는
    워크트리에서 돌린다", `gotcha-tests-write-live-storage-db` 참고)을
    따르면 실 `.env`에 의존하는 단언은 매번 실패해 C1과 무관한 노이즈를
    기준선에 남긴다. C1의 본질은 "자격증명이 있을 때 실제로 등록되는가"
    이지 "이 머신에 `.env`가 있는가"가 아니므로, `get_settings()`를
    가짜 자격증명으로 monkeypatch해 그 본질만 검증한다."""
    import app.dependencies as deps

    class _FakeSettings:
        NAVER_CLIENT_ID = "test-client-id"
        NAVER_CLIENT_SECRET = "test-client-secret"
        REDIS_URL = None

    monkeypatch.setattr(deps, "get_settings", lambda: _FakeSettings())
    # 싱글턴 캐시를 리셋 -- 안 하면 이 프로세스에서 먼저 만들어진(혹은
    # 프로바이더 0개인) 인스턴스가 그대로 반환되어 monkeypatch가
    # 무의미해진다. monkeypatch가 테스트 종료 시 원래 값으로 되돌려주므로
    # 다른 테스트를 오염시키지 않는다.
    monkeypatch.setattr(deps, "_news_service_instance", None)

    svc = await deps.get_news_service()
    assert svc.providers, "뉴스 서비스에 프로바이더가 하나도 등록되지 않았다 (C1)"


@pytest.mark.asyncio
async def test_news_service_singleton_empty_credentials_yields_no_providers(
    monkeypatch,
):
    """대조군 -- 자격증명이 없으면(워크트리의 진짜 상태) 프로바이더가
    0개인 것 자체는 정상이라는 것을 문서화한다. 이 테스트가 검증하는
    관계(있으면 등록/없으면 미등록)가 바로 위 테스트가 자격증명 유무와
    무관하게 C1을 잡는 근거다."""
    import app.dependencies as deps

    class _FakeSettingsNoCreds:
        NAVER_CLIENT_ID = None
        NAVER_CLIENT_SECRET = None
        REDIS_URL = None

    monkeypatch.setattr(deps, "get_settings", lambda: _FakeSettingsNoCreds())
    monkeypatch.setattr(deps, "_news_service_instance", None)

    svc = await deps.get_news_service()
    assert not svc.providers
