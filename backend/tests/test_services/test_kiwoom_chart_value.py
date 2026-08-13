"""A0: get_daily_chart_df가 거래대금(value) 컬럼을 배선하는지 검증.

client.py:687-690이 ka10081의 trde_prica를 이미 ChartData.acml_tr_pbmn(원 단위)로
파싱하는데, DataFrame 변환이 이 필드를 버리고 있었다. 이 테스트가 그 회귀를 막는다.
"""

import pandas as pd
import pytest

from services.kiwoom.models import ChartData


def _chart(dt, close, vol, tr_pbmn):
    return ChartData(
        stk_cd="093190", dt=dt, open_prc=close, high_prc=close,
        low_prc=close, clos_prc=close, acml_vol=vol, acml_tr_pbmn=tr_pbmn,
    )


def _to_df(charts):
    """client.get_daily_chart_df의 DataFrame 변환부만 떼어낸 것과 동일해야 한다."""
    from services.kiwoom.client import _charts_to_df
    return _charts_to_df(charts)


def test_value_column_present_and_in_won():
    charts = [_chart("20260727", 8800, 8063, 70_000_000)]
    df = _to_df(charts)
    assert "value" in df.columns
    assert df["value"].iloc[0] == 70_000_000.0


def test_value_falls_back_to_close_times_volume_when_missing():
    """구 캐시/미제공 응답 호환 — acml_tr_pbmn이 None이면 close*volume 근사."""
    charts = [_chart("20260727", 8800, 8063, None)]
    df = _to_df(charts)
    assert df["value"].iloc[0] == pytest.approx(8800 * 8063)


def test_empty_charts_returns_value_column():
    """빈 응답도 value 컬럼을 가진 빈 DataFrame이어야 소비자가 KeyError를 안 만난다."""
    df = _to_df([])
    assert "value" in df.columns
    assert len(df) == 0
