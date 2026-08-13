"""라이브 DB 가드 — conftest의 autouse 방어가 실제로 작동하는지.

2026-08-03과 2026-08-11에 **같은 키가 두 번** 오염됐다:
메인 체크아웃에서 전체 스위트를 돌리자 라이브 `storage.db`의
`app_settings['agent_chat:coordinator_state']`가 테스트 픽스처 값
`{"running": false, "check_interval": 5, "max_concurrent": 3}`으로 덮였다.
08-11 오염은 **3거래일 뒤** 재기동에서야 발현해 자율 토론 엔진이
그동안 꺼져 있었다.

기존 트립와이어(`pytest_sessionstart/finish`)는 이것을 **구조적으로 못 잡는다** —
`agent_chat_decisions`의 *행 수 증가*만 보는데, `app_settings` 오염은
`UPDATE`라 행 수가 변하지 않는다. 게다가 경고만 하고 실패시키지 않는다.

여기서는 탐지가 아니라 **차단**을 검증한다: 라이브 경로를 열려고 하면
tmp로 리다이렉트되어 실제 파일에 도달하지 못한다.
"""
from pathlib import Path

import pytest

import services.storage_service as storage_service_module
from services.krx_holiday.storage import HolidayStorage
from services.storage_service import DEFAULT_DB_PATH, StorageService

_LIVE_STORAGE = DEFAULT_DB_PATH.resolve()
_LIVE_HOLIDAYS = (Path(__file__).resolve().parent.parent / "data" / "holidays.db")


def test_explicit_live_storage_path_is_redirected():
    svc = StorageService(db_path=_LIVE_STORAGE)
    assert Path(svc.db_path).resolve() != _LIVE_STORAGE


def test_default_storage_path_is_redirected():
    """`db_path=None`이 가장 흔한 경로다 — `get_storage_service()` 싱글턴이
    이렇게 만들어진다. 명시적 경로만 막으면 정작 실제 사고 경로를 놓친다."""
    svc = StorageService()
    assert Path(svc.db_path).resolve() != _LIVE_STORAGE


def test_live_holiday_db_is_redirected():
    """2026-08-11에 `holidays.db`도 같은 실행에서 오염됐다 —
    `isolated_storage_service`는 `storage_service`만 덮고 `HolidayStorage`는
    자기 기본 경로를 따로 갖는다."""
    store = HolidayStorage(db_path=str(_LIVE_HOLIDAYS))
    assert Path(store.db_path).resolve() != _LIVE_HOLIDAYS.resolve()


def test_tmp_paths_are_left_alone(tmp_path):
    """가드가 무차별이면 격리된 테스트까지 엉뚱한 곳으로 보낸다."""
    target = tmp_path / "mine.db"
    svc = StorageService(db_path=target)
    assert Path(svc.db_path).resolve() == target.resolve()


@pytest.mark.asyncio
async def test_writing_through_the_singleton_never_touches_the_live_file():
    """실제 사고 경로: `get_storage_service()` 싱글턴으로 `app_settings`에 쓴다.

    ⚠️ **검사 순서가 중요하다.** 경로 확인을 쓰기 **앞에** 둔다 — 뒤에 두면
    가드가 없는 RED 단계에서 이 테스트가 **실제로 라이브 DB를 오염시킨다.**
    2026-08-12에 실제로 그렇게 썼다가 `agent_chat:coordinator_state`를
    08-11과 똑같은 값으로 덮어버렸다(백업에서 복구). 파괴적 부작용이 있는
    RED는 안전장치를 먼저 단언하고, 그것이 통과할 때만 부작용을 실행한다.
    """
    storage_service_module._storage_service = None
    try:
        storage = await storage_service_module.get_storage_service()

        # 먼저 안전을 단언한다. 가드가 없으면 여기서 멈춰 아래 쓰기에 닿지 않는다.
        assert Path(storage.db_path).resolve() != _LIVE_STORAGE

        await storage.set_app_setting(
            "agent_chat:coordinator_state",
            '{"running": false, "check_interval": 5, "max_concurrent": 3}',
        )
        assert Path(storage.db_path).resolve() != _LIVE_STORAGE
    finally:
        storage_service_module._storage_service = None
