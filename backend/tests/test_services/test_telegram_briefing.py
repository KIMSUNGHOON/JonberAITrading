"""장전 브리핑·조회 명령 포맷터 (2026-08-06).

설계: docs/superpowers/specs/2026-08-06-telegram-briefing-design.md

포맷터는 순수 함수다 — DB도 API도 모른다. 그래서 테스트 대부분이 여기서
끝나고, 수집기 쪽은 "예외가 전파되지 않는가"만 본다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.telegram.briefing import (
    BriefData,
    ExposureData,
    SlotData,
    WhyData,
    format_brief,
    format_exposure,
    format_slots,
    format_why,
)

_NO_DATA = "조회 실패"


def _brief(**over) -> BriefData:
    base = dict(
        trade_date="2026-08-07",
        equity=498_797_526.0,
        stock_value=48_822_900.0,
        positions=[
            dict(ticker="316140", quantity=402, pnl_pct=1.2, stop_gap_pct=7.4),
            dict(ticker="089860", quantity=231, pnl_pct=2.8, stop_gap_pct=7.4),
        ],
        max_positions=5,
        max_single_position_pct=0.03,
        exposure=dict(target_pct=0.12, binding="m_evidence", degraded="index_series_stale",
                      ts="2026-08-06 15:25:00"),
        yesterday=dict(trade_date="2026-08-06", decisions=101, fills=0,
                       realized_pnl=0.0, slot_refusals=16),
        trading=dict(mode="active", is_active=True, daily_trades=0, max_daily_trades=10),
        watch_count=36,
    )
    base.update(over)
    return BriefData(**base)


class TestBriefAllocation:
    """자산 배분 — 사용자가 명시적으로 요청한 항목(포트폴리오 비중·현금 비중)."""

    def test_stock_and_cash_ratios_sum_to_one_hundred(self):
        text = format_brief(_brief())
        assert "9.8%" in text, "주식 비중"
        assert "90.2%" in text, "현금 비중 — 둘의 합이 100%여야 한다"

    def test_shows_structural_ceiling(self):
        """슬롯 수 × 종목당 비중이 실제 천장이라는 것이 브리핑의 요점이다."""
        text = format_brief(_brief())
        assert "15.0%" in text, "5슬롯 × 3% = 15% 천장"

    def test_missing_equity_degrades_only_that_section(self):
        text = format_brief(_brief(equity=None, stock_value=None))
        assert _NO_DATA in text
        assert "316140" in text, "다른 섹션은 살아 있어야 한다"


class TestBriefExposure:
    def test_shows_target_and_binding(self):
        text = format_brief(_brief())
        assert "12.0%" in text
        assert "m_evidence" in text

    def test_absent_observation_says_not_started(self):
        """08:30에는 오늘 행이 없다 — 어제 값을 오늘 값인 척 보여주면 안 된다."""
        text = format_brief(_brief(exposure=None))
        assert "관측 시작 전" in text

    def test_stale_observation_carries_its_timestamp(self):
        text = format_brief(_brief())
        assert "2026-08-06 15:25" in text, "언제 값인지가 붙어야 한다"


class TestBriefReadiness:
    def test_shows_daily_trade_reset(self):
        text = format_brief(_brief())
        assert "0/10" in text

    def test_flags_full_slots(self):
        five = [dict(ticker=f"{i:06d}", quantity=10, pnl_pct=0.0, stop_gap_pct=5.0)
                for i in range(5)]
        text = format_brief(_brief(positions=five, max_positions=5))
        assert "만석" in text, "5/5면 신규 진입 불가라고 말해야 한다"

    def test_does_not_flag_full_when_room_remains(self):
        five = [dict(ticker=f"{i:06d}", quantity=10, pnl_pct=0.0, stop_gap_pct=5.0)
                for i in range(5)]
        text = format_brief(_brief(positions=five, max_positions=8))
        assert "만석" not in text, "5/8이면 자리가 남았다"


class TestBriefFitsTelegram:
    def test_stays_under_the_message_limit(self):
        """_truncate가 잘라 조용히 사라지는 것보다 애초에 들어가는 게 낫다."""
        many = [dict(ticker=f"{i:06d}", quantity=100, pnl_pct=1.0, stop_gap_pct=5.0)
                for i in range(10)]
        text = format_brief(_brief(positions=many))
        assert len(text) < 3900


class TestWhy:
    """이번 세션 전체가 사실상 이 질문 하나였다 — 왜 안 샀나."""

    def _why(self, **over) -> WhyData:
        base = dict(
            ticker="316140",
            last_decision=dict(ts="2026-08-06 15:11:22", action="ADD", consensus=0.82),
            executed=False,
            block_reason="게이트 · max_positions — open positions 5 >= limit 5",
            today_actions={"ADD": 7, "HOLD": 1},
            fills_today=0,
            sizing_lineage_present=False,
        )
        base.update(over)
        return WhyData(**base)

    def test_states_it_did_not_execute(self):
        text = format_why(self._why())
        assert "316140" in text
        assert "ADD" in text

    def test_surfaces_the_block_reason(self):
        text = format_why(self._why())
        assert "max_positions" in text

    def test_missing_lineage_is_explained_not_just_blank(self):
        """계보 부재는 '사이징에 도달조차 못 했다'는 지문이다."""
        text = format_why(self._why())
        assert "사이징" in text

    def test_executed_case_reads_differently(self):
        text = format_why(self._why(executed=True, fills_today=1, block_reason=None,
                                    sizing_lineage_present=True))
        assert "체결" in text

    def test_unknown_ticker_is_not_a_crash(self):
        text = format_why(WhyData(ticker="999999", last_decision=None, executed=False,
                                  block_reason=None, today_actions={}, fills_today=0,
                                  sizing_lineage_present=False))
        assert "999999" in text


class TestSlots:
    def _slots(self, **over) -> SlotData:
        base = dict(
            trade_date="2026-08-06",
            open_positions=5,
            max_positions=5,
            refusals=[
                dict(ticker="028670", count=12, max_consensus=1.0,
                     first="09:15:51", last="15:31:29"),
                dict(ticker="030000", count=3, max_consensus=1.0,
                     first="14:18:22", last="15:24:23"),
            ],
        )
        base.update(over)
        return SlotData(**base)

    def test_lists_refusals_with_consensus(self):
        text = format_slots(self._slots())
        assert "028670" in text and "12" in text

    def test_no_refusals_is_stated_not_blank(self):
        text = format_slots(self._slots(refusals=[]))
        assert "없음" in text

    def test_caps_the_list_and_says_how_many_were_cut(self):
        """많은 날 _truncate가 조용히 자르는 것보다 명시적으로 잘라야 한다.

        리뷰 지적(2026-08-06): 이전 판본은 슬라이싱과 "…외 N종" 줄을 통째로
        지워도 통과했다 — 25행이 3,900자 안에 들어가고 헤더에 이미 "25"가
        있었기 때문이다. 렌더된 종목 줄 수를 직접 세어 캡을 고정한다.
        """
        many = [dict(ticker=f"{i:06d}", count=1, max_consensus=0.8,
                     first="09:00:00", last="09:00:00") for i in range(25)]
        text = format_slots(self._slots(refusals=many))

        rendered = [ln for ln in text.splitlines() if "최고 합의" in ln]
        assert len(rendered) == 10, f"10종만 그려야 하는데 {len(rendered)}종"
        assert "…외 15종" in text, "잘린 수를 명시해야 한다"
        assert len(text) < 3900


class TestExposure:
    def _exp(self, **over) -> ExposureData:
        base = dict(
            ts="2026-08-07 09:05:00",
            target_pct=0.12,
            actual_pct=0.098,
            binding="daily_limit",
            degraded="index_series_stale",
            m_vol=1.0, m_drawdown=1.0,
            index_vol_annualized=112.1, index_vol_n=14,
            n_round_trips=8,
        )
        base.update(over)
        return ExposureData(**base)

    def test_shows_every_component(self):
        text = format_exposure(self._exp())
        for name in ("m_vol", "m_drawdown"):
            assert name in text

    def test_degraded_reason_is_visible(self):
        """중립값이 왜 중립인지가 안 보이면 degraded를 만든 의미가 없다."""
        text = format_exposure(self._exp())
        assert "index_series_stale" in text

    def test_raw_vol_is_shown_even_when_stale(self):
        text = format_exposure(self._exp())
        assert "112.1" in text

    def test_absent_row_says_not_started(self):
        text = format_exposure(None)
        assert "관측 시작 전" in text


class TestExposureRegimeFieldsAreGoneNotFailed:
    """리뷰 발견(2026-08-07): `m_regime`/`m_evidence` 컬럼이
    `insert_exposure_shadow`에서 항상 NULL이 되도록 바뀐 뒤에도
    `collect_exposure`/`format_exposure`가 여전히 그 값을 읽어
    `_pct`/`_NO_DATA` 경로로 렌더링하고 있었다 -- 그래서 관측 행이 있어도
    `/exposure`가 매번 "m_regime 조회 실패"/"m_evidence 조회 실패"를
    표시했다. 개념 자체가 없어진 것이지 조회가 실패한 게 아니므로 이건
    바로 어제(2026-08-06) 고친 "행 없음을 조회 실패로 오보고"하던 버그와
    같은 종류의 거짓말이다.

    이 테스트는 mock이 아니라 `isolated_storage_service`로 진짜 저장소를
    거친다 -- `insert_exposure_shadow`가 실제로 무엇을 저장하고
    `collect_exposure`가 그걸 실제로 어떻게 읽는지까지 검증해야
    `ExposureData`에 `m_regime`/`m_evidence`를 남겨두고 값만 못 채운
    회귀(그러면 `row.get()`이 여전히 `None`을 돌려주고 렌더러가 다시
    `_NO_DATA`를 낸다)도 잡을 수 있다."""

    @pytest.mark.asyncio
    async def test_observed_row_renders_without_failure_markers(
        self, isolated_storage_service
    ):
        import services.telegram.briefing as b
        from services.trading.exposure_target import compute_regime_target

        target = compute_regime_target(
            regime_label="neutral",
            prev_effective_pct=0.65,
            seed_actual_pct=0.0994,
            index_returns=[1.14, -1.14] * 10,
            equity=497_403_042.0,
            equity_peak=497_403_042.0,
        )
        await isolated_storage_service.insert_exposure_shadow(
            trade_date="2026-08-07",
            target=target,
            equity=497_403_042.0,
            stock_value=49_426_800.0,
            actual_pct=0.0994,
            n_round_trips=None,
        )

        async def fake_storage():
            return isolated_storage_service

        b._storage = fake_storage
        try:
            data = await b.collect_exposure()
        finally:
            import importlib
            importlib.reload(b)

        text = format_exposure(data)
        assert _NO_DATA not in text, (
            f"관측 행이 있는데도 '조회 실패'가 나온다 -- 없어진 성분을 "
            f"여전히 조회 실패처럼 렌더링하고 있다:\n{text}"
        )
        assert "m_regime" not in text, "없어진 개념을 렌더링에 남겨두면 안 된다"
        assert "m_evidence" not in text, "없어진 개념을 렌더링에 남겨두면 안 된다"


class TestBlockReasonScanner:
    """차단 사유 스캔은 best-effort다 — 못 찾으면 아무 말도 하지 않아야 한다."""

    @pytest.mark.asyncio
    async def test_finds_the_last_block_event(self, tmp_path, monkeypatch):
        import services.telegram.briefing as b

        log = tmp_path / "2026-08-07-09.log"
        log.write_text(
            "2026-08-07 09:10:00 | INFO | add_gate_denied check=max_positions "
            "gate_reason='open positions 5 >= limit 5' ticker=316140\n"
            "2026-08-07 09:20:00 | INFO | add_blocked_by_position_cap ticker=316140\n"
        )
        monkeypatch.setattr(b, "_log_dir", lambda: tmp_path)

        r = await b._scan_block_reason("316140")
        assert r is not None
        assert "단일 종목 상한" in r, "마지막 이벤트를 잡아야 한다"

    @pytest.mark.asyncio
    async def test_carries_the_gate_reason_text(self, tmp_path, monkeypatch):
        import services.telegram.briefing as b

        (tmp_path / "a.log").write_text(
            "add_gate_denied check=max_positions "
            "gate_reason='open positions 5 >= limit 5' ticker=316140\n"
        )
        monkeypatch.setattr(b, "_log_dir", lambda: tmp_path)

        r = await b._scan_block_reason("316140")
        assert "5 >= limit 5" in r

    @pytest.mark.asyncio
    async def test_other_ticker_is_not_claimed(self, tmp_path, monkeypatch):
        import services.telegram.briefing as b

        (tmp_path / "a.log").write_text("add_gate_denied ticker=316140\n")
        monkeypatch.setattr(b, "_log_dir", lambda: tmp_path)

        assert await b._scan_block_reason("999999") is None

    @pytest.mark.asyncio
    async def test_missing_log_dir_is_not_a_crash(self, tmp_path, monkeypatch):
        import services.telegram.briefing as b

        monkeypatch.setattr(b, "_log_dir", lambda: tmp_path / "없는디렉터리")
        assert await b._scan_block_reason("316140") is None

    def test_unknown_reason_draws_no_line(self):
        """찾지 못했으면 '막은 것' 줄 자체가 없어야 한다 — 빈 값으로 그리면
        '막힌 게 없다'로 오독된다."""
        text = format_why(WhyData(ticker="316140", executed=False, block_reason=None))
        assert "막은 것" not in text


class TestHolidayServiceContract:
    """휴장일 판단이 조용히 실패하면 주말 아침에도 브리핑이 날아간다.

    리뷰가 실측으로 잡았다(2026-08-06): `is_business_day`는 존재하지 않는
    메서드였고(실제는 `is_trading_day`), 호출부가 broad except 안이라
    AttributeError가 매번 삼켜져 휴장일 스킵이 **한 번도 동작하지 않았다.**
    """

    def test_holiday_service_exposes_the_method_we_call(self):
        from services.krx_holiday.service import KRXHolidayService

        assert hasattr(KRXHolidayService, "is_trading_day"), (
            "이 이름이 바뀌면 브리핑의 휴장일 스킵이 조용히 죽는다"
        )

    def test_sync_accessor_exists_for_non_async_callers(self):
        """`_prev_business_day`는 동기 함수라 async 접근자를 쓸 수 없다."""
        from services.krx_holiday.service import get_holiday_service_sync

        assert callable(get_holiday_service_sync)

    @pytest.mark.asyncio
    async def test_morning_brief_skips_non_trading_day(self, monkeypatch):
        import services.telegram.briefing as b

        sent = []

        class FakeSvc:
            def is_trading_day(self, d):
                return False

        async def fake_get_svc():
            return FakeSvc()

        monkeypatch.setattr("services.krx_holiday.get_holiday_service", fake_get_svc,
                            raising=False)
        monkeypatch.setattr(b, "collect_brief",
                            lambda *a, **k: sent.append("collected"))

        result = await b.send_morning_brief()
        assert result is False
        assert not sent, "휴장일엔 수집조차 하지 않아야 한다"


class TestScanPicksTheNewestEvent:
    """리뷰가 실측으로 잡았다 — grep 인자 순서 때문에 오래된 사유를 집었다."""

    @pytest.mark.asyncio
    async def test_newest_file_wins(self, tmp_path, monkeypatch):
        import os
        import time

        import services.telegram.briefing as b

        old = tmp_path / "old.log"
        old.write_text("add_gate_denied ticker=316140\n")
        new = tmp_path / "new.log"
        new.write_text("add_blocked_by_position_cap ticker=316140\n")

        # mtime을 명시적으로 벌린다 -- 같은 초에 쓰이면 정렬이 흔들린다.
        past = time.time() - 3600
        os.utime(old, (past, past))

        monkeypatch.setattr(b, "_log_dir", lambda: tmp_path)
        r = await b._scan_block_reason("316140")
        assert "단일 종목 상한" in r, f"최신 파일의 사유를 집어야 하는데: {r}"


class TestExposureFailureIsNotAbsence:
    """조회 실패와 '아직 행 없음'을 뭉개면 장애가 영구히 정상으로 보고된다."""

    def test_unavailable_renders_as_failure_not_not_started(self):
        from services.telegram.briefing import ExposureUnavailable

        text = format_exposure(ExposureUnavailable())
        assert _NO_DATA in text
        assert "관측 시작 전" not in text

    def test_none_still_renders_as_not_started(self):
        text = format_exposure(None)
        assert "관측 시작 전" in text


class TestExposureAbsentIsNotFailure:
    """라이브에서 실제로 걸린 버그(2026-08-07 07:3x).

    `/exposure`가 "조회 실패"를 냈는데 로그에 예외가 하나도 없었다. 원인은
    `get_latest_exposure_shadow`가 "행 없음"과 "조회 실패"를 **둘 다 None**으로
    돌려준 것 — 포맷터 계층에서 갈라 놓고 스토리지 계층에서 다시 합쳐 버렸다.

    계약: None = 행 없음(정상) / 예외 = 조회 실패(비정상).
    """

    @pytest.mark.asyncio
    async def test_empty_table_is_not_started_not_failure(self, isolated_storage_service):
        import services.telegram.briefing as b

        async def fake_storage():
            return isolated_storage_service

        b._storage = fake_storage
        try:
            result = await b.collect_exposure()
        finally:
            import importlib
            importlib.reload(b)

        assert result is None, "행이 없으면 None -- ExposureUnavailable이 아니다"
        assert "관측 시작 전" in format_exposure(result)

    @pytest.mark.asyncio
    async def test_storage_raising_is_a_failure(self, monkeypatch):
        import services.telegram.briefing as b

        class Boom:
            async def get_latest_exposure_shadow(self):
                raise RuntimeError("db down")

        async def fake_storage():
            return Boom()

        monkeypatch.setattr(b, "_storage", fake_storage)
        result = await b.collect_exposure()

        assert isinstance(result, b.ExposureUnavailable)
        assert _NO_DATA in format_exposure(result)

    @pytest.mark.asyncio
    async def test_storage_method_raises_instead_of_swallowing(self, isolated_storage_service):
        """스토리지가 예외를 삼키면 위 구별이 원천적으로 불가능하다."""
        import aiosqlite

        async with aiosqlite.connect(str(isolated_storage_service.db_path)) as conn:
            await conn.execute("DROP TABLE IF EXISTS exposure_shadow")
            await conn.commit()

        with pytest.raises(Exception):
            await isolated_storage_service.get_latest_exposure_shadow()


# ---------------------------------------------------------------------------
# 레짐 판정 블록 (Task 8, 2026-08-07) — /brief와 /exposure 앞에 붙는다.
# ---------------------------------------------------------------------------


class TestFormatBriefPrependsRegime:
    def test_regime_block_appears_before_allocation(self):
        from services.telegram.briefing import format_regime

        d = _brief(regime={
            "regime": "bear", "confidence": 0.7,
            "anchor_target_pct": 0.55, "effective_target_pct": 0.26,
            "key_drivers": ["EWY -2.97%"], "degraded": [],
        })
        text = format_brief(d)
        assert format_regime(d.regime).splitlines()[0] in text
        assert text.index("레짐: bear") < text.index("[자산 배분]")

    def test_absent_regime_shows_no_judgment_not_a_crash(self):
        text = format_brief(_brief(regime=None))
        assert "판정 없음" in text
        assert "316140" in text, "레짐 행이 없어도 나머지 섹션은 살아있어야 한다"


class TestCollectBriefRegimeIsIndependentSection:
    """`storage.get_latest_regime_judgment()`는 DB 오류를 raise한다(계약).
    이 실패가 `collect_brief` 전체를 삼키면(바깥 `_safe("brief", ...)`가
    받아 브리핑 전 섹션이 함께 '데이터 없음'으로 접힌다) 레짐 하나 때문에
    포지션·어제·준비 섹션까지 전부 사라진다 -- exposure_shadow 조회와
    동일한 섹션-독립 실패 패턴을 지켜야 한다."""

    @pytest.mark.asyncio
    async def test_regime_row_is_collected(self, isolated_storage_service):
        import services.telegram.briefing as b

        await isolated_storage_service.insert_regime_judgment(
            trade_date="2026-08-07", regime="bear", confidence=0.7,
            rationale="EWY -2.97%", key_drivers=["EWY -2.97%"],
            anchor_target_pct=0.55, effective_target_pct=0.26,
            prev_effective_pct=0.30, degraded=[],
        )

        async def fake_storage():
            return isolated_storage_service

        b._storage = fake_storage
        try:
            data = await b.collect_brief("2026-08-07")
        finally:
            import importlib
            importlib.reload(b)

        assert data.regime is not None
        assert data.regime["regime"] == "bear"

    @pytest.mark.asyncio
    async def test_regime_fetch_failure_does_not_lose_other_sections(self, monkeypatch):
        """직접 try/except 없이 이 실패가 전파되면 바깥 `_safe`가
        `collect_brief(...)` 전체를 삼켜 브리핑이 통째로 사라진다 --
        이 테스트는 그 회귀를 잡는다."""
        import services.telegram.briefing as b

        class Boom:
            async def get_latest_regime_judgment(self):
                raise RuntimeError("db down")

            async def get_latest_exposure_shadow(self):
                return None

            async def get_day_rollup(self, trade_date):
                return {"trade_date": trade_date, "decisions": 3, "fills": 1}

        async def fake_storage():
            return Boom()

        monkeypatch.setattr(b, "_storage", fake_storage)
        data = await b.collect_brief("2026-08-07", prev_date="2026-08-06")

        assert isinstance(data.regime, b.RegimeUnavailable), (
            "조회 실패는 '행 없음'(None)이 아니라 조회 실패로 남아야 한다 (I-3)"
        )
        assert data.yesterday is not None, (
            "레짐 조회 실패가 다른 섹션(어제)까지 삼켰다 -- 직접 try/except가 "
            "빠졌다는 신호"
        )


class TestCollectRegimeRow:
    """`/exposure`가 쓰는 독립 수집기. 직접 try/except -- `_safe`를 쓰면
    '행 없음'과 '조회 실패'가 다시 합쳐진다."""

    @pytest.mark.asyncio
    async def test_row_present(self, isolated_storage_service):
        import services.telegram.briefing as b

        await isolated_storage_service.insert_regime_judgment(
            trade_date="2026-08-07", regime="neutral", confidence=None,
            rationale="", key_drivers=[], anchor_target_pct=0.45,
            effective_target_pct=0.30, prev_effective_pct=None, degraded=[],
        )

        async def fake_storage():
            return isolated_storage_service

        b._storage = fake_storage
        try:
            row = await b.collect_regime_row()
        finally:
            import importlib
            importlib.reload(b)

        assert row is not None
        assert row["regime"] == "neutral"

    @pytest.mark.asyncio
    async def test_no_row_returns_none(self, isolated_storage_service):
        import services.telegram.briefing as b

        async def fake_storage():
            return isolated_storage_service

        b._storage = fake_storage
        try:
            row = await b.collect_regime_row()
        finally:
            import importlib
            importlib.reload(b)

        assert row is None

    @pytest.mark.asyncio
    async def test_storage_raising_never_propagates(self, monkeypatch):
        import services.telegram.briefing as b

        class Boom:
            async def get_latest_regime_judgment(self):
                raise RuntimeError("db down")

        async def fake_storage():
            return Boom()

        monkeypatch.setattr(b, "_storage", fake_storage)
        row = await b.collect_regime_row()  # 예외가 나가면 이 테스트가 실패한다

        assert isinstance(row, b.RegimeUnavailable)


class TestRegimeThreeStates:
    """I-3 (2026-08-07 최종 리뷰) — "행 없음"과 "조회 실패"를 절대 합치지 않는다.

    배포 다음날 아침 검증이 전적으로 이 화면을 통해 이뤄진다. DB 오류가
    "아직 안 돌았음"으로 읽히면 정상/비정상 판별 자체가 불가능해진다 --
    2026-08-06에 사용자가 폰에서 실제로 신고한 사고와 같은 계열이다.
    """

    def test_format_regime_distinguishes_absent_from_unavailable(self):
        from services.telegram.briefing import RegimeUnavailable, format_regime

        absent = format_regime(None)
        unavailable = format_regime(RegimeUnavailable())

        assert "판정 없음" in absent
        assert _NO_DATA not in absent
        assert _NO_DATA in unavailable
        assert "판정 없음" not in unavailable

    @pytest.mark.asyncio
    async def test_collect_regime_row_failure_renders_as_a_failure(self, monkeypatch):
        """수집기와 포맷터를 이어서 확인한다 -- 둘 중 하나만 3-상태여도
        화면에는 여전히 "아직 안 돌았음"이 나간다."""
        import services.telegram.briefing as b

        class Boom:
            async def get_latest_regime_judgment(self):
                raise RuntimeError("db down")

        async def fake_storage():
            return Boom()

        monkeypatch.setattr(b, "_storage", fake_storage)
        text = b.format_regime(await b.collect_regime_row())

        assert _NO_DATA in text
        assert "판정 없음" not in text

    @pytest.mark.asyncio
    async def test_brief_regime_failure_is_not_reported_as_no_judgment(
        self, monkeypatch
    ):
        """`/brief`도 같은 구별을 해야 한다 -- 08:30 자동 발송이 검증의
        1차 창구다."""
        import services.telegram.briefing as b

        class Boom:
            async def get_latest_regime_judgment(self):
                raise RuntimeError("db down")

            async def get_latest_exposure_shadow(self):
                return None

            async def get_day_rollup(self, d):
                return None

        async def fake_storage():
            return Boom()

        async def no_coordinator():
            return None

        monkeypatch.setattr(b, "_storage", fake_storage)
        monkeypatch.setattr(b, "_coordinator", no_coordinator)
        d = await b.collect_brief("2026-08-07")

        assert isinstance(d.regime, b.RegimeUnavailable)
        text = b.format_brief(d)
        assert _NO_DATA in b.format_regime(d.regime)
        assert "판정 없음" not in text


class TestHandleExposurePrependsRegime:
    """commands.py의 `/exposure` 핸들러 — `format_exposure`/`collect_exposure`
    의 기존 계약(ExposureData/None/ExposureUnavailable, 위 테스트들이 잠근
    삼중 상태)은 건드리지 않고 앞에 레짐 블록만 얹는다."""

    @pytest.mark.asyncio
    async def test_regime_and_exposure_both_render(self, monkeypatch):
        import services.telegram.briefing as briefing_module
        from services.telegram import commands

        monkeypatch.setattr(
            briefing_module, "collect_regime_row",
            AsyncMock(return_value={
                "regime": "bear", "confidence": 0.7,
                "anchor_target_pct": 0.55, "effective_target_pct": 0.26,
                "key_drivers": [], "degraded": [],
            }),
        )
        monkeypatch.setattr(
            briefing_module, "collect_exposure", AsyncMock(return_value=None)
        )

        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=AsyncMock()),
            message=None,
        )
        await commands.handle_exposure(update, SimpleNamespace(args=[]))

        sent = update.effective_message.reply_text.call_args[0][0]
        assert "레짐: bear" in sent
        assert "관측 시작 전" in sent, "기존 /exposure 본문(None 케이스)이 그대로 붙어야 한다"

    @pytest.mark.asyncio
    async def test_exposure_failure_does_not_hide_regime(self, monkeypatch):
        """레짐과 노출도는 서로 다른 테이블 — 하나가 죽어도 다른 하나는 나간다."""
        import services.telegram.briefing as briefing_module
        from services.telegram import commands
        from services.telegram.briefing import ExposureUnavailable

        monkeypatch.setattr(
            briefing_module, "collect_regime_row",
            AsyncMock(return_value={
                "regime": "neutral", "confidence": None,
                "anchor_target_pct": 0.45, "effective_target_pct": 0.30,
                "key_drivers": [], "degraded": [],
            }),
        )
        monkeypatch.setattr(
            briefing_module, "collect_exposure",
            AsyncMock(return_value=ExposureUnavailable()),
        )

        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=AsyncMock()),
            message=None,
        )
        await commands.handle_exposure(update, SimpleNamespace(args=[]))

        sent = update.effective_message.reply_text.call_args[0][0]
        assert "레짐: neutral" in sent
        assert _NO_DATA in sent
