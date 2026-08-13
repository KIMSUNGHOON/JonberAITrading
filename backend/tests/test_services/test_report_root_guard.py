"""`guard_live_report_root`(tests/conftest.py) 자체를 검증한다.

Task 7 리뷰 Critical 1: `_notify_eod_summary`가 `build_and_send_report`를
배선하면서 기존 테스트들이 `services.reports.delivery.REPORT_ROOT`
(`backend/data/reports/`, 하드코딩)를 실제로 건드리는 부작용을 물려받았다
-- 실측: `postmarket-2026-08-13.html`이 가짜 데이터("보유 0종")로 덮어써짐.
이 파일은 그걸 막는 autouse 가드가 ①실제로 리다이렉트하는지 ②이탈을
실제로 잡아내는지 둘 다 확인한다.

⚠️ ②를 확인한다고 실제 `backend/data/reports/`에 파일을 만들었다 지우면
안 된다(막으려는 바로 그 사고를 재현하는 셈이다) -- `_assert_no_report_drift`
를 가짜 frozenset으로 직접 호출해 판정 로직만 검증한다. 실제 디렉터리는
한 바이트도 건드리지 않는다.
"""
import pytest

from services.reports import delivery
from tests.conftest import _LIVE_REPORT_ROOT, _assert_no_report_drift, _report_snapshot


def test_report_root_is_redirected_away_from_live_path():
    """가드가 걸려 있으면 REPORT_ROOT는 절대 실제 backend/data/reports/가
    아니다 -- 모든 테스트에 autouse로 적용되므로 이 assert 자체가 그
    적용을 증명한다."""
    assert delivery.REPORT_ROOT != _LIVE_REPORT_ROOT
    assert delivery.REPORT_ROOT.resolve() != _LIVE_REPORT_ROOT.resolve()


def test_save_report_lands_in_sandbox_not_live_dir():
    """리다이렉트된 REPORT_ROOT로 실제 저장 함수를 불러 파일이 샌드박스에만
    생기고 라이브 디렉터리는 그대로인지 확인한다."""
    before = _report_snapshot(_LIVE_REPORT_ROOT)

    path = delivery.save_report(
        delivery.REPORT_ROOT, "premarket", "2099-01-01", "<html>guard-test</html>"
    )

    assert path.parent == delivery.REPORT_ROOT
    assert path.read_text(encoding="utf-8") == "<html>guard-test</html>"
    # 라이브 디렉터리는 이 저장으로 전혀 변하지 않아야 한다.
    assert _report_snapshot(_LIVE_REPORT_ROOT) == before
    assert not (_LIVE_REPORT_ROOT / "premarket-2099-01-01.html").exists()


def test_drift_detector_raises_on_added_file():
    """`_assert_no_report_drift`가 판정 핵심 로직이다 -- 실제 디렉터리를
    건드리지 않고 가짜 frozenset만으로 '새 파일이 생겼다' 상황을 재현해
    실제로 예외를 던지는지 확인한다."""
    before = frozenset({"postmarket-2026-08-13.html"})
    after = frozenset({"postmarket-2026-08-13.html", "postmarket-2026-08-14.html"})
    with pytest.raises(AssertionError, match="guard_live_report_root가 뚫렸다"):
        _assert_no_report_drift(before, after, nodeid="fake::test")


def test_drift_detector_raises_on_removed_file():
    """prune_old_reports가 라이브 디렉터리에서 실제로 파일을 지워버리는
    경우(리다이렉트가 안 걸렸을 때)도 잡아야 한다."""
    before = frozenset({"postmarket-2026-07-01.html", "postmarket-2026-08-13.html"})
    after = frozenset({"postmarket-2026-08-13.html"})
    with pytest.raises(AssertionError, match="guard_live_report_root가 뚫렸다"):
        _assert_no_report_drift(before, after, nodeid="fake::test")


def test_drift_detector_is_silent_when_unchanged():
    """정상 케이스(가드가 제대로 리다이렉트해 라이브 디렉터리가 안 변함)에서
    는 예외가 없어야 한다 -- 그렇지 않으면 가드 자체가 모든 테스트를
    거짓 실패시킨다."""
    snap = frozenset({"postmarket-2026-08-13.html"})
    _assert_no_report_drift(snap, snap, nodeid="fake::test")  # raises면 실패


def test_report_snapshot_missing_dir_is_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert _report_snapshot(missing) == frozenset()


def test_report_snapshot_only_counts_html(tmp_path):
    (tmp_path / "postmarket-2026-08-13.html").write_text("x")
    (tmp_path / "notes.txt").write_text("y")
    assert _report_snapshot(tmp_path) == frozenset({"postmarket-2026-08-13.html"})
