"""장시간 서비스의 타임존 정확성 — pytz `tzinfo=` 함정 회귀 방지.

`KST`가 `pytz.timezone("Asia/Seoul")`이던 시절, `datetime.combine(..., tzinfo=KST)`와
`.replace(tzinfo=KST)`는 그 존의 **최초 역사적 오프셋**인 LMT `+08:28`을 붙였다.
pytz는 이 용법을 지원하지 않으며 `KST.localize(dt)`를 요구한다. 그래서
`current_time`(= `datetime.now(KST)`, pytz가 `fromutc`는 제대로 구현)만 `+09:00`이고
`next_open`/`next_close`는 32분 어긋난 값이 나갔다 — 2026-08-03 라이브에서
`next_close: 2026-08-03T15:30:00+08:28`, 카운트다운 32분 초과로 관측됐다.

수정은 정의 한 줄을 stdlib 고정 오프셋으로 바꾼 것이다(형제 파일
`services/kiwoom/auth.py:23`·`services/kiwoom/models.py:15`가 이미 쓰는 관용구).
이 테스트는 그 관용구가 되돌아가는 것을 막는다.

`is_open`은 애초에 `now.time()` naive 비교라 이 버그의 영향을 받지 않았다 —
매매 게이트가 영향받지 않았다는 사실 자체를 아래에서 함께 고정한다.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services.trading import market_hours as mh
from services.trading.market_hours import MarketHoursService, MarketType

KST_EXPECTED = timedelta(hours=9)


def _svc() -> MarketHoursService:
    return MarketHoursService()


def _at(y, m, d, hh, mm) -> datetime:
    """KST 기준 특정 시각을 `datetime.now(KST)` 자리에 끼워넣는다."""
    return datetime(y, m, d, hh, mm, tzinfo=timezone(KST_EXPECTED))


class TestKstOffset:
    def test_module_kst_is_plus_nine_not_lmt(self):
        """정의부 자체가 +09:00이어야 한다. pytz 객체면 LMT(+08:28)가 샌다."""
        probe = datetime(2026, 8, 3, 15, 30, tzinfo=mh.KST)
        assert probe.utcoffset() == KST_EXPECTED

    def test_naive_replace_gets_plus_nine(self):
        """`.replace(tzinfo=KST)` 관용구도 안전해야 한다 — pytz면 여기서 깨진다."""
        naive = datetime(2026, 8, 3, 18, 0)
        assert naive.replace(tzinfo=mh.KST).utcoffset() == KST_EXPECTED


class TestSessionBoundaryOffsets:
    """세션이 돌려주는 경계 시각들이 전부 +09:00인지."""

    def test_next_close_during_open_hours(self):
        now = _at(2026, 8, 3, 9, 15)  # 월요일 장중
        with patch.object(mh, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            with patch.object(_svc(), "_is_krx_holiday", return_value=False):
                session = _svc().get_market_session(MarketType.KRX)

        assert session.is_open is True
        assert session.next_close is not None
        assert session.next_close.utcoffset() == KST_EXPECTED
        assert session.next_close.hour == 15 and session.next_close.minute == 30

    def test_next_open_before_market_opens(self):
        now = _at(2026, 8, 3, 8, 40)  # 월요일 개장 전
        with patch.object(mh, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            with patch.object(_svc(), "_is_krx_holiday", return_value=False):
                session = _svc().get_market_session(MarketType.KRX)

        assert session.is_open is False
        assert session.next_open is not None
        assert session.next_open.utcoffset() == KST_EXPECTED

    def test_next_open_on_weekend(self):
        now = _at(2026, 8, 1, 12, 0)  # 토요일
        with patch.object(mh, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            session = _svc().get_market_session(MarketType.KRX)

        assert session.is_open is False
        assert session.next_open is not None
        assert session.next_open.utcoffset() == KST_EXPECTED
        assert session.next_open.weekday() == 0  # 월요일


class TestCountdownArithmetic:
    """경계 시각이 틀리면 카운트다운이 32분 어긋난다 — 라이브에서 관측된 증상."""

    def test_remaining_until_close_is_exact(self):
        now = _at(2026, 8, 3, 9, 15)
        with patch.object(mh, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            with patch.object(_svc(), "_is_krx_holiday", return_value=False):
                session = _svc().get_market_session(MarketType.KRX)

        # 09:15 → 15:30 은 정확히 6시간 15분이다. LMT 버그가 있으면 6시간 47분이 나온다.
        assert session.next_close - now == timedelta(hours=6, minutes=15)


class TestGateUnaffected:
    """`is_open`은 naive `.time()` 비교라 이 버그와 무관했다 — 그 사실을 고정한다."""

    @pytest.mark.parametrize(
        "hh,mm,expected",
        [(8, 59, False), (9, 0, True), (15, 30, True), (15, 31, False)],
    )
    def test_open_gate_boundaries(self, hh, mm, expected):
        now = _at(2026, 8, 3, hh, mm)
        with patch.object(mh, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            with patch.object(_svc(), "_is_krx_holiday", return_value=False):
                session = _svc().get_market_session(MarketType.KRX)

        assert session.is_open is expected
