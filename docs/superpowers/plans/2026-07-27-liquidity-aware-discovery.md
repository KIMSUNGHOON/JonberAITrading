# 유동성 인지 발굴·사이징 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 발굴 파이프라인이 거래대금(유동성)을 인지하게 만들어, 저유동성 종목을 능동적으로 선호하던 두 구조적 편향을 제거하고 포지션 크기를 유동성에 비례시킨다.

**Architecture:** 키움 일봉 응답에 이미 파싱돼 있으나 DataFrame 변환에서 버려지던 `trde_prica`(거래대금)를 `chart_df["value"]`로 배선하는 것이 모든 것의 전제다. 그 위에 순수 함수 모듈 `services/discovery/liquidity.py`를 신설해 ADTV·참여율·유동성 캡 계산을 단일 진실 소스로 모으고, 발굴 품질필터(A1)·전략스코어(A2/A3)·랭킹가중(B)·사이징(C1)·프롬프트(C2)가 전부 이 모듈을 소비한다.

**Tech Stack:** Python 3.12, pandas, pytest, Pydantic. 신규 의존성 없음. 신규 API 호출 없음(기존 ka10081 응답 필드 재사용).

**Spec:** `docs/superpowers/specs/2026-07-27-liquidity-aware-discovery-design.md`

## Global Constraints

- **참여율 게이트 = 1.0%**, 하드플로어 = **10억원**(어떤 완화에서도 불변). 계좌 5억 기준 `min_adtv = 20억`.
- **사이징 참여율 캡 = 0.5%.** 게이트(1%)와 사이징(0.5%)은 2계층이며 서로 다른 상수다.
- **ADTV는 20일 "중앙값"**(median). 평균 금지 — 모멘텀 전략이 급등일을 포함해 평균이 체계적으로 상향 편향된다.
- **`threshold` 0.55를 변경하지 않는다.** 실측상 재산출 불필요(문턱 0.55에서 17종 통과 = daily_cap 5의 3.4배).
- **"momentum 단독 승격 금지" 규칙을 도입하지 않는다.** 실측 효과 0(17종 → 17종).
- `factors.py`와 `liquidity.py`는 **순수 함수만** — I/O·네트워크·DB 절대 금지(기존 모듈 규약).
- 모든 신규 계산은 데이터 부족 시 `None`을 반환하고, 스코어 함수는 `None`을 0 성분으로 처리한다. **NaN을 절대 전파하지 않는다**(기존 규약).
- 테스트 실행: `conda activate agentic-trading` 후 **`cd backend && python -m pytest`** (레포 루트에서 실행하면 `No module named app`으로 실패).
- 환경변수 충돌 회피: `env -u OPENROUTER_API_KEY` 접두 사용.
- 운용: **15:30~16:35 EOD 발굴 스캔 창 재시작 금지**, 실 포지션 보유 중 **장중 재시작 금지**.

## File Structure

**신규**
- `backend/services/discovery/liquidity.py` — 유동성 계산 순수 함수 단일 진실 소스(ADTV 중앙값, 하방 일관성, 참여율, 유동성 캡, 로그 게이트). T3~T7이 전부 소비.
- `backend/tests/test_services/test_discovery_liquidity.py` — 위 모듈 단위 테스트.

**수정**
- `backend/services/kiwoom/client.py:787-800` — `get_daily_chart_df`에 `value` 컬럼 추가(A0).
- `backend/services/discovery/factors.py` — `passes_quality_filter` 게이트(A1), `_extract_atoms` 거래대금 원자, `_score_momentum` 교체(A2/A3).
- `backend/services/background_scanner/scanner.py:1054` — `min_adtv` 주입 + `factor_json`에 유동성 필드.
- `backend/services/discovery/ranker.py:351-387` — `_effective_weights` 재정규화 폐기(B).
- `backend/services/trading/portfolio_agent.py:279` — 사이징 캡 항 추가(C1).
- `backend/agents/graph/kr_stock_nodes/decision_nodes.py` — 두 번째 사이징 지점(C1).
- 리스크 에이전트 프롬프트(C2).

**테스트 수정**
- `backend/tests/test_services/test_discovery_factors.py` — 신규 게이트/스코어 테스트 추가.
- `backend/tests/test_services/test_discovery_ranker.py` — 재정규화 폐기 테스트.

---

## Task 1: 거래대금 배선 (A0)

`get_daily_chart_df`가 `ChartData.acml_tr_pbmn`을 버리고 있다. 이 한 컬럼이 이후 모든 태스크의 입력이므로 가장 먼저 배선한다.

**Files:**
- Modify: `backend/services/kiwoom/client.py:787-800`
- Test: `backend/tests/test_services/test_kiwoom_chart_value.py` (신규)

**Interfaces:**
- Consumes: `ChartData.acml_tr_pbmn: Optional[int]` (models.py:143, 이미 존재)
- Produces: `get_daily_chart_df()` 반환 DataFrame에 `value` 컬럼(float, 원 단위). 이후 모든 태스크가 `chart_df["value"]`로 소비한다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_kiwoom_chart_value.py`를 새로 만든다:

```python
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
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_kiwoom_chart_value.py -v`
Expected: FAIL — `ImportError: cannot import name '_charts_to_df'`

- [ ] **Step 3: 최소 구현을 작성한다**

`backend/services/kiwoom/client.py`에서 DataFrame 변환부를 모듈 수준 순수 함수로 추출하고 `value`를 추가한다. `get_daily_chart_df` 안의 기존 `data = [...]` / `df = pd.DataFrame(data)` 블록을 아래 호출로 교체한다:

```python
# 모듈 수준(클래스 밖)에 추가
_CHART_DF_COLUMNS = ["date", "open", "high", "low", "close", "volume", "value"]


def _charts_to_df(charts) -> pd.DataFrame:
    """ChartData 리스트 → OHLCV+거래대금 DataFrame (순수 함수, 테스트 가능).

    `value`(거래대금, 원)는 ka10081의 trde_prica를 client._parse_signed_price가
    백만원→원으로 환산해 담은 ChartData.acml_tr_pbmn을 그대로 쓴다. 이 필드가
    None인 구 캐시/미제공 응답에서만 close*volume로 근사한다 — 근사는 폴백일
    뿐이며 정상 경로는 거래소 실측값이다.
    """
    if not charts:
        return pd.DataFrame(columns=_CHART_DF_COLUMNS)

    data = [
        {
            "date": c.dt,
            "open": c.open_prc,
            "high": c.high_prc,
            "low": c.low_prc,
            "close": c.clos_prc,
            "volume": c.acml_vol,
            "value": float(
                c.acml_tr_pbmn
                if c.acml_tr_pbmn is not None
                else (c.clos_prc or 0) * (c.acml_vol or 0)
            ),
        }
        for c in charts
    ]
    return pd.DataFrame(data)
```

그리고 `get_daily_chart_df` 본문에서 기존 빈 반환과 변환 블록을 교체한다:

```python
        charts = await self.get_daily_chart(stk_cd, base_dt, upd_stkpc_tp)
        df = _charts_to_df(charts)
```

(이후 기존의 정렬/인덱스 처리 코드는 그대로 둔다. 빈 DataFrame 조기 반환 분기는 `_charts_to_df`가 흡수했으므로 제거한다.)

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_kiwoom_chart_value.py -v`
Expected: 3 passed

- [ ] **Step 5: 기존 스위트 무회귀를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/ -k "kiwoom or chart or discovery" -q`
Expected: 전부 통과. `value` 컬럼 추가는 additive이므로 기존 소비자(OHLCV 6컬럼만 읽음)에 영향이 없어야 한다.

- [ ] **Step 6: 커밋한다**

```bash
git add backend/services/kiwoom/client.py backend/tests/test_services/test_kiwoom_chart_value.py
git commit -m "feat(kiwoom): 일봉 DataFrame에 거래대금(value) 컬럼 배선 — 유동성 인지 전제"
```

---

## Task 2: 유동성 계산 모듈 (단일 진실 소스)

ADTV·참여율·유동성 캡 계산이 발굴·사이징·프롬프트 3곳에서 필요하다. 중복 구현을 막기 위해 순수 함수 모듈을 먼저 만든다.

**Files:**
- Create: `backend/services/discovery/liquidity.py`
- Test: `backend/tests/test_services/test_discovery_liquidity.py`
- Modify: `backend/services/discovery/__init__.py` (export 추가)

**Interfaces:**
- Consumes: Task 1의 `chart_df["value"]`
- Produces (T3~T7이 전부 이 시그니처에 의존):
  - `HARD_FLOOR_ADTV: float = 1_000_000_000.0`
  - `GATE_PARTICIPATION_PCT: float = 0.01`
  - `SIZING_PARTICIPATION_PCT: float = 0.005`
  - `adtv_median(chart_df, window=20) -> Optional[float]`
  - `downside_consistency_ok(chart_df, min_adtv, window=20, floor_ratio=0.6, max_violations=5) -> bool`
  - `has_zero_volume_day(chart_df, window=20) -> bool`
  - `required_min_adtv(position_notional) -> float`
  - `participation_rate(position_notional, adtv) -> Optional[float]`
  - `liquidity_cap_value(adtv) -> Optional[float]`
  - `liquidity_gate_score(adtv) -> float`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_discovery_liquidity.py`:

```python
"""유동성 계산 순수 함수 테스트.

빅솔론(093190) 실측값을 회귀 픽스처로 고정한다 — ADTV 중앙값 1.2억,
계좌 5억(포지션 2000만원)에서 참여율 16.1%. 이 종목이 반드시 게이트에서
탈락하는 것이 이 아크 전체의 수용 기준이다.
"""

import pandas as pd
import pytest

from services.discovery.liquidity import (
    GATE_PARTICIPATION_PCT,
    HARD_FLOOR_ADTV,
    SIZING_PARTICIPATION_PCT,
    adtv_median,
    downside_consistency_ok,
    has_zero_volume_day,
    liquidity_cap_value,
    liquidity_gate_score,
    participation_rate,
    required_min_adtv,
)

억 = 100_000_000.0


def _df(values, volumes=None):
    n = len(values)
    vols = volumes if volumes is not None else [1000] * n
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "close": [1000] * n,
        "volume": vols,
        "value": [float(v) for v in values],
    })


# --- adtv_median ---

def test_adtv_median_uses_median_not_mean():
    """급등 하루의 스파이크가 평균을 끌어올리는 것을 중앙값이 차단한다."""
    values = [1 * 억] * 19 + [100 * 억]   # 평균 ≈ 5.95억, 중앙값 = 1억
    assert adtv_median(_df(values)) == pytest.approx(1 * 억)


def test_adtv_median_uses_last_20_only():
    values = [50 * 억] * 10 + [2 * 억] * 20   # 최근 20일은 전부 2억
    assert adtv_median(_df(values)) == pytest.approx(2 * 억)


def test_adtv_median_returns_none_when_insufficient():
    assert adtv_median(_df([1 * 억] * 9)) is None


def test_adtv_median_returns_none_without_value_column():
    """구 캐시(value 컬럼 없음)에서 KeyError 대신 None."""
    df = pd.DataFrame({"close": [1000] * 20, "volume": [1] * 20})
    assert adtv_median(df) is None


def test_bixolon_regression_adtv():
    """빅솔론 실측 20일 거래대금 — 중앙값 약 1.2억."""
    values = [0.70, 2.42, 1.09, 0.69, 0.32, 0.90, 1.5, 1.1, 1.3, 0.8,
              1.2, 1.4, 0.95, 1.25, 1.15, 1.35, 1.05, 0.85, 1.45, 1.6]
    adtv = adtv_median(_df([v * 억 for v in values]))
    assert 1.0 * 억 <= adtv <= 1.4 * 억


# --- required_min_adtv / participation_rate ---

def test_required_min_adtv_is_position_over_one_percent():
    assert required_min_adtv(20_000_000) == pytest.approx(20 * 억)


def test_required_min_adtv_respects_hard_floor():
    """소액 포지션이라도 10억 하드플로어는 절대 뚫리지 않는다."""
    assert required_min_adtv(1_000_000) == HARD_FLOOR_ADTV


def test_participation_rate_bixolon():
    assert participation_rate(20_000_000, 1.24 * 억) == pytest.approx(0.1613, abs=1e-3)


def test_participation_rate_none_on_zero_adtv():
    assert participation_rate(20_000_000, 0) is None
    assert participation_rate(20_000_000, None) is None


# --- liquidity_cap_value ---

def test_liquidity_cap_is_half_percent():
    assert liquidity_cap_value(40 * 억) == pytest.approx(20_000_000)
    assert liquidity_cap_value(20 * 억) == pytest.approx(10_000_000)


def test_liquidity_cap_none_when_adtv_missing():
    assert liquidity_cap_value(None) is None


# --- liquidity_gate_score (로그 스케일) ---

def test_gate_score_log_scale_endpoints():
    assert liquidity_gate_score(10 * 억) == pytest.approx(0.0, abs=1e-6)
    assert liquidity_gate_score(100 * 억) == pytest.approx(1.0, abs=1e-6)


def test_gate_score_clamped_outside_range():
    assert liquidity_gate_score(1 * 억) == 0.0
    assert liquidity_gate_score(1000 * 억) == 1.0
    assert liquidity_gate_score(None) == 0.0


def test_gate_score_a1_survivor_floor():
    """A1 게이트(20억)를 통과한 종목은 liq_gate >= 0.30 (스펙 §3.4)."""
    assert liquidity_gate_score(20 * 억) >= 0.30


# --- downside_consistency / zero volume ---

def test_downside_consistency_allows_five_violations():
    values = [20 * 억] * 15 + [5 * 억] * 5      # 위반 5일 = 경계 통과
    assert downside_consistency_ok(_df(values), 20 * 억) is True


def test_downside_consistency_rejects_six_violations():
    values = [20 * 억] * 14 + [5 * 억] * 6
    assert downside_consistency_ok(_df(values), 20 * 억) is False


def test_downside_consistency_floor_ratio_is_60_percent():
    """min_adtv의 60% 이상이면 위반이 아니다 (20억 기준 12억)."""
    values = [12.1 * 억] * 20
    assert downside_consistency_ok(_df(values), 20 * 억) is True


def test_zero_volume_day_detected():
    assert has_zero_volume_day(_df([1 * 억] * 20, volumes=[100] * 19 + [0])) is True
    assert has_zero_volume_day(_df([1 * 억] * 20)) is False
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_liquidity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.discovery.liquidity'`

- [ ] **Step 3: 최소 구현을 작성한다**

`backend/services/discovery/liquidity.py`:

```python
"""유동성 계산 순수 함수 (유동성 인지 발굴 아크).

전부 순수 함수 — I/O·네트워크·DB 절대 없음(factors.py와 동일 규약). 입력은
`chart_df`(kiwoom get_daily_chart_df 스키마, `value` 컬럼 = 거래대금 원 단위)와
스칼라뿐이다.

설계 근거는 docs/superpowers/specs/2026-07-27-liquidity-aware-discovery-design.md.
핵심 두 가지:
- **중앙값을 쓴다**: 모멘텀 전략은 정의상 급등일을 포함하므로 평균 거래대금은
  체계적으로 상향 편향된다. MSCI ATVR·FTSE GEIS가 유동성 스크린에 median을
  채택한 근거와 같다.
- **게이트(1%)와 사이징(0.5%)은 다른 상수다**: 전자는 진입 자격, 후자는 실제
  포지션 크기. 2계층 방어이며 하나로 합치면 안 된다.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

# 절대 하한 — 어떤 완화에서도 뚫리지 않는다. KOSPI 종목의 50.5%가 ADTV 10억
# 미만이며(아주경제 2026-06), 이 대역은 참여율과 무관하게 자율봇이 다룰 수
# 있는 시장이 아니다.
HARD_FLOOR_ADTV: float = 1_000_000_000.0  # 10억원

# 진입 자격 게이트: 포지션이 일평균 거래대금의 1.0%를 넘으면 배제.
# 기관 실무 상한(1%)이자 한국 퀀트 표준(0.5%)의 2배 완화선.
GATE_PARTICIPATION_PCT: float = 0.01

# 사이징 캡: 실제 포지션은 ADTV의 0.5%까지. 한국 퀀트 실무 표준
# (《현명한 퀀트 투자자》 "당일 거래대금의 0.5%").
SIZING_PARTICIPATION_PCT: float = 0.005

# liquidity_gate_score의 로그 스케일 양 끝점.
_GATE_SCORE_MIN_ADTV: float = 1_000_000_000.0    # 10억 -> 0.0
_GATE_SCORE_MAX_ADTV: float = 10_000_000_000.0   # 100억 -> 1.0

DEFAULT_WINDOW = 20
MIN_SAMPLES = 10


def _value_series(chart_df: Optional[pd.DataFrame], window: int) -> Optional[pd.Series]:
    """chart_df에서 최근 `window`일 거래대금 시리즈를 뽑는다. 컬럼 부재/표본
    부족/전부 결측이면 None(호출자가 '데이터 없음'으로 처리)."""
    if chart_df is None or len(chart_df) == 0:
        return None
    if "value" not in chart_df.columns:
        return None
    s = pd.to_numeric(chart_df["value"].tail(window), errors="coerce").dropna()
    if len(s) < MIN_SAMPLES:
        return None
    return s


def adtv_median(
    chart_df: Optional[pd.DataFrame], window: int = DEFAULT_WINDOW
) -> Optional[float]:
    """최근 `window`일 거래대금 중앙값(원). 데이터 부족 시 None."""
    s = _value_series(chart_df, window)
    if s is None:
        return None
    med = float(s.median())
    if math.isnan(med) or math.isinf(med):
        return None
    return med


def required_min_adtv(position_notional: float) -> float:
    """이 포지션 규모가 요구하는 최소 ADTV — 참여율 게이트와 하드플로어의 max."""
    if position_notional is None or position_notional <= 0:
        return HARD_FLOOR_ADTV
    return max(position_notional / GATE_PARTICIPATION_PCT, HARD_FLOOR_ADTV)


def participation_rate(
    position_notional: float, adtv: Optional[float]
) -> Optional[float]:
    """포지션이 일평균 거래대금에서 차지하는 비율(0~1). ADTV 결측이면 None."""
    if adtv is None or adtv <= 0:
        return None
    return float(position_notional) / float(adtv)


def liquidity_cap_value(adtv: Optional[float]) -> Optional[float]:
    """유동성이 허용하는 최대 포지션 금액(원). ADTV 결측이면 None(캡 미적용)."""
    if adtv is None or adtv <= 0:
        return None
    return float(adtv) * SIZING_PARTICIPATION_PCT


def liquidity_gate_score(adtv: Optional[float]) -> float:
    """절대 유동성의 0~1 로그 스코어 — 10억=0.0, 100억=1.0.

    momentum 거래량 성분의 곱셈 게이트로 쓰인다. 선형이 아니라 로그인 이유는
    거래대금 분포가 극단적으로 편중돼 있어(상위 6%가 전체의 88%) 선형 스케일이면
    중형주가 전부 0에 붙기 때문이다.
    """
    if adtv is None or adtv <= 0:
        return 0.0
    ratio = float(adtv) / _GATE_SCORE_MIN_ADTV
    if ratio <= 1.0:
        return 0.0
    span = math.log10(_GATE_SCORE_MAX_ADTV / _GATE_SCORE_MIN_ADTV)
    score = math.log10(ratio) / span
    return max(0.0, min(1.0, score))


def downside_consistency_ok(
    chart_df: Optional[pd.DataFrame],
    min_adtv: float,
    window: int = DEFAULT_WINDOW,
    floor_ratio: float = 0.6,
    max_violations: int = 5,
) -> bool:
    """하방 일관성 — 최근 `window`일 중 거래대금이 `min_adtv * floor_ratio`
    미만인 날이 `max_violations`일 이하여야 한다.

    MSCI의 Frequency of Trading(3개월 거래일 비율 80%)을 일간으로 이식한 것.
    중앙값만 보면 '평소 말라 있다가 며칠 폭발'한 종목을 못 거른다.

    데이터가 없으면 False(fail-closed) — 유동성을 확인할 수 없는 종목은
    통과시키지 않는다.
    """
    s = _value_series(chart_df, window)
    if s is None:
        return False
    floor = float(min_adtv) * floor_ratio
    return int((s < floor).sum()) <= max_violations


def has_zero_volume_day(
    chart_df: Optional[pd.DataFrame], window: int = DEFAULT_WINDOW
) -> bool:
    """최근 `window`일 중 거래량 0인 날이 있으면 True(즉시 배제 대상).

    거래량 0은 호가가 아예 성립하지 않은 날이며, KRX 저유동성 단일가매매
    (평균 체결주기 10분 초과) 대역의 지문이다. 컬럼이 없으면 판단 불가이므로
    False(다른 게이트가 걸러낸다)."""
    if chart_df is None or len(chart_df) == 0 or "volume" not in chart_df.columns:
        return False
    v = pd.to_numeric(chart_df["volume"].tail(window), errors="coerce").fillna(0)
    return bool((v <= 0).any())
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_liquidity.py -v`
Expected: 18 passed

- [ ] **Step 5: 패키지 export를 추가한다**

`backend/services/discovery/__init__.py`의 import 블록과 `__all__`에 추가한다(기존 `factors` export 스타일을 그대로 따른다):

```python
from .liquidity import (
    GATE_PARTICIPATION_PCT,
    HARD_FLOOR_ADTV,
    SIZING_PARTICIPATION_PCT,
    adtv_median,
    liquidity_cap_value,
    liquidity_gate_score,
    participation_rate,
    required_min_adtv,
)
```

`__all__` 리스트에도 같은 이름 8개를 문자열로 추가한다.

- [ ] **Step 6: import 스모크와 커밋**

Run: `cd backend && env -u OPENROUTER_API_KEY python -c "from services.discovery import adtv_median, liquidity_cap_value; print('ok')"`
Expected: `ok`

```bash
git add backend/services/discovery/liquidity.py backend/services/discovery/__init__.py backend/tests/test_services/test_discovery_liquidity.py
git commit -m "feat(discovery): 유동성 계산 순수 함수 모듈 신설 — ADTV 중앙값·참여율·2계층 상수"
```

---

## Task 3: 유동성 게이트 (A1)

**Files:**
- Modify: `backend/services/discovery/factors.py:32-37`(사유 코드), `:99-117`(`passes_quality_filter`)
- Modify: `backend/services/background_scanner/scanner.py:1054`(호출부)
- Test: `backend/tests/test_services/test_discovery_factors.py` (테스트 추가)

**Interfaces:**
- Consumes: `liquidity.adtv_median`, `liquidity.downside_consistency_ok`, `liquidity.has_zero_volume_day`, `liquidity.required_min_adtv`
- Produces: `passes_quality_filter(snap, *, min_market_cap=..., min_history=..., min_adtv: Optional[float] = None)` — `min_adtv=None`이면 유동성 게이트를 건너뛴다(하위 호환). 신규 사유 코드 `REASON_LIQUIDITY_LOW`, `REASON_LIQUIDITY_INCONSISTENT`, `REASON_ZERO_VOLUME_DAY`, `REASON_PRICE_TOO_LOW`.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_discovery_factors.py` 끝에 추가한다. 파일 상단 import에 신규 사유 코드 4개를 더한다.

```python
# ---------------------------------------------------------------------------
# A1: 유동성 게이트
# ---------------------------------------------------------------------------

억 = 100_000_000.0


def _liquid_snap(values, closes=None, volumes=None, market_cap=200 * 억):
    """유동성 게이트 테스트용 스냅샷 — 시총/히스토리는 항상 통과하도록 고정."""
    n = len(values)
    cl = closes if closes is not None else [10_000.0] * n
    vol = volumes if volumes is not None else [1000] * n
    df = _make_chart_df(cl, vol)
    df["value"] = [float(v) for v in values]
    return StockSnapshot(
        ticker="000000", name="테스트", price=cl[-1], market_cap=market_cap,
        per=10.0, pbr=1.0, volume=vol[-1], chart_df=df,
    )


def test_liquidity_gate_skipped_when_min_adtv_none():
    """하위 호환 — min_adtv를 안 주면 유동성 검사를 하지 않는다."""
    snap = _liquid_snap([0.5 * 억] * 60)
    passed, reason = passes_quality_filter(snap)
    assert passed is True
    assert reason is None


def test_liquidity_gate_rejects_below_min_adtv():
    snap = _liquid_snap([1.2 * 억] * 60)          # 빅솔론 대역
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_LOW


def test_liquidity_gate_accepts_at_or_above_min_adtv():
    snap = _liquid_snap([20 * 억] * 60)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is True
    assert reason is None


def test_liquidity_gate_rejects_inconsistent_downside():
    """중앙값은 통과하지만 20일 중 6일이 바닥(12억 미만)이면 배제."""
    snap = _liquid_snap([30 * 억] * 54 + [5 * 억] * 6)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_INCONSISTENT


def test_liquidity_gate_rejects_zero_volume_day():
    snap = _liquid_snap([30 * 억] * 60, volumes=[1000] * 59 + [0])
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_ZERO_VOLUME_DAY


def test_liquidity_gate_rejects_penny_stock():
    """종가 2,000원 미만은 호가단위 마찰(0.25%+)로 배제."""
    snap = _liquid_snap([30 * 억] * 60, closes=[1_900.0] * 60)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_PRICE_TOO_LOW


def test_liquidity_gate_rejects_missing_value_column():
    """value 컬럼이 없으면(구 캐시) fail-closed — 통과시키지 않는다."""
    df = _make_chart_df([10_000.0] * 60, [1000] * 60)   # value 없음
    snap = StockSnapshot(
        ticker="000000", name="구캐시", price=10_000.0, market_cap=200 * 억,
        per=10.0, pbr=1.0, volume=1000, chart_df=df,
    )
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_LIQUIDITY_LOW


def test_existing_filters_still_run_first():
    """검사 순서 — 시총 미달이면 유동성 사유가 아니라 시총 사유가 나와야 한다."""
    snap = _liquid_snap([30 * 억] * 60, market_cap=100.0)
    passed, reason = passes_quality_filter(snap, min_adtv=20 * 억)
    assert passed is False
    assert reason == REASON_MARKET_CAP_LOW
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_factors.py -k liquidity -v`
Expected: FAIL — `ImportError: cannot import name 'REASON_LIQUIDITY_LOW'`

- [ ] **Step 3: 사유 코드와 게이트를 구현한다**

`backend/services/discovery/factors.py`의 사유 코드 블록(32-37행 부근)에 추가한다:

```python
REASON_LIQUIDITY_LOW = "liquidity_low"
REASON_LIQUIDITY_INCONSISTENT = "liquidity_inconsistent"
REASON_ZERO_VOLUME_DAY = "zero_volume_day"
REASON_PRICE_TOO_LOW = "price_too_low"

# 호가단위 마찰 하한 — 2,000원 미만 구간은 최소 스프레드만으로 0.25%를 넘는다
# (KRX 통합 호가단위: 2,000원 미만 1원). 동전주 퇴출 리스크도 함께 회피한다.
DEFAULT_MIN_CLOSE_PRICE = 2_000.0
```

파일 상단 import에 추가한다:

```python
from services.discovery.liquidity import (
    adtv_median,
    downside_consistency_ok,
    has_zero_volume_day,
)
```

`passes_quality_filter`를 교체한다(기존 3검사는 순서·동작 그대로 유지하고 뒤에 유동성 검사를 덧붙인다):

```python
def passes_quality_filter(
    snap: StockSnapshot,
    *,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    min_history: int = DEFAULT_MIN_HISTORY,
    min_adtv: Optional[float] = None,
    min_close_price: float = DEFAULT_MIN_CLOSE_PRICE,
) -> tuple[bool, Optional[str]]:
    """공통 품질 필터. (통과여부, 실패사유) 반환 — 통과 시 사유는 None.

    검사 순서: 가격>0 → 시총 하한 → 히스토리 길이 → (min_adtv가 주어졌을 때만)
    유동성 4종. 관리종목 제외 등은 수집 단계(DS-2, exclude_warnings)의 몫이다.

    `min_adtv=None`이면 유동성 검사를 건너뛴다 — 이 함수를 유동성 맥락 없이
    호출하는 기존 경로(테스트·구 스캔 재현)의 하위 호환을 위해서다. 발굴
    스캐너는 반드시 값을 주입한다(scanner.py).

    유동성 검사는 fail-closed다: `value` 컬럼이 없거나 표본이 부족해 ADTV를
    계산할 수 없으면 통과가 아니라 배제한다. 유동성을 확인할 수 없는 종목에
    2000만원을 넣는 것이 이 아크가 막으려는 바로 그 일이다.
    """
    if snap.price is None or snap.price <= 0:
        return False, REASON_PRICE_ZERO
    if snap.market_cap is None or snap.market_cap < min_market_cap:
        return False, REASON_MARKET_CAP_LOW
    history_len = 0 if snap.chart_df is None else len(snap.chart_df)
    if history_len < min_history:
        return False, REASON_INSUFFICIENT_HISTORY

    if min_adtv is None:
        return True, None

    if snap.price < min_close_price:
        return False, REASON_PRICE_TOO_LOW

    adtv = adtv_median(snap.chart_df)
    if adtv is None or adtv < min_adtv:
        return False, REASON_LIQUIDITY_LOW

    if has_zero_volume_day(snap.chart_df):
        return False, REASON_ZERO_VOLUME_DAY

    if not downside_consistency_ok(snap.chart_df, min_adtv):
        return False, REASON_LIQUIDITY_INCONSISTENT

    return True, None
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_factors.py -v`
Expected: 기존 24 + 신규 8 = 32 passed

- [ ] **Step 5: 스캐너에서 `min_adtv`를 주입한다**

`backend/services/background_scanner/scanner.py`의 `passes_quality_filter(snap)` 호출(1054행)을 교체한다. 계좌 평가액은 스캔 시작 시 한 번 조회해 스캐너 인스턴스에 보관한다(종목마다 조회하면 2,650회 API 호출이 된다).

스캐너 클래스에 필드와 헬퍼를 추가한다:

```python
    # 발굴 스캔 1회 동안 고정되는 유동성 임계값(원). 스캔 시작 시 1회 산출.
    _discovery_min_adtv: Optional[float] = None

    async def _resolve_min_adtv(self) -> float:
        """계좌 평가액 기반 유동성 임계값. 조회 실패 시 설정 폴백(fail-closed).

        min_adtv = max(equity * 0.04 / 0.01, 10억) — 포지션이 일평균 거래대금의
        1%를 넘지 않게 하는 최소 ADTV. 계좌가 커지면 자동으로 올라간다.
        """
        from services.discovery.liquidity import required_min_adtv

        fallback = float(
            getattr(settings, "DISCOVERY_MIN_ADTV_FALLBACK", 2_000_000_000.0)
        )
        try:
            coordinator = get_trading_coordinator_sync()
            equity = float(coordinator._state.account.total_equity)
            if equity <= 0:
                raise ValueError("equity<=0")
            return required_min_adtv(equity * 0.04)
        except Exception as e:
            logger.warning(
                "discovery_min_adtv_fallback", error=str(e), fallback=fallback
            )
            return fallback
```

스캔 진입점(발굴 모드로 유니버스를 돌기 직전)에서 1회 산출한다:

```python
        self._discovery_min_adtv = await self._resolve_min_adtv()
        logger.info("discovery_min_adtv_resolved", min_adtv=self._discovery_min_adtv)
```

그리고 호출부를 바꾼다:

```python
                passed, reason = passes_quality_filter(
                    snap, min_adtv=self._discovery_min_adtv
                )
```

`factor_json`의 `quality_filter_passed: True` 분기에 유동성 필드를 추가한다(C1/C2가 소비):

```python
                    from services.discovery.liquidity import adtv_median

                    _adtv = adtv_median(snap.chart_df)

                    factor_json = {
                        "quality_filter_passed": True,
                        ...
                        # 유동성 인지 아크: 사이징 캡(C1)과 토론 프롬프트(C2)가
                        # 이 값을 소비한다. None이면 소비자가 캡/문구를 생략한다.
                        "adtv20_med": _adtv,
                        ...
                    }
```

`backend/app/config.py`에 설정을 추가한다:

```python
    # 발굴 유동성 게이트 폴백(원) — 계좌 조회 실패 시 사용. 계좌 5억·포지션
    # 4%·참여율 1% 기준값(20억)과 동일하게 둔다.
    DISCOVERY_MIN_ADTV_FALLBACK: float = 2_000_000_000.0
```

- [ ] **Step 6: import 스모크로 부팅 안전을 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -c "import app.main; print('boot ok')"`
Expected: `boot ok`

- [ ] **Step 7: 커밋한다**

```bash
git add backend/services/discovery/factors.py backend/services/background_scanner/scanner.py backend/app/config.py backend/tests/test_services/test_discovery_factors.py
git commit -m "feat(discovery): 유동성 게이트 A1 — 참여율 1% + 하드플로어 10억, 하방일관성·거래량0·저가주 배제"
```

---

## Task 4: momentum 거래량 성분 교체 + 고가근접 재스케일 (A2/A3)

편향의 첫 번째 원인을 제거한다. 두 수정 모두 `_score_momentum` 한 함수 안이라 한 태스크로 묶는다.

**Files:**
- Modify: `backend/services/discovery/factors.py` — `_extract_atoms`(거래대금 원자 추가), `_score_momentum`(성분 2개 교체)
- Test: `backend/tests/test_services/test_discovery_factors.py`

**Interfaces:**
- Consumes: `liquidity.adtv_median`, `liquidity.liquidity_gate_score`
- Produces: `atoms` dict에 신규 키 `adtv20_med`, `value_ratio`, `value_surge`. `_score_momentum(atoms)` 시그니처는 불변.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# ---------------------------------------------------------------------------
# A2/A3: momentum 거래량 성분 + 고가근접
# ---------------------------------------------------------------------------


def _momentum_snap(values, closes, volumes=None):
    n = len(closes)
    vol = volumes if volumes is not None else [1000] * n
    df = _make_chart_df(closes, vol)
    df["value"] = [float(v) for v in values]
    return StockSnapshot(
        ticker="000000", name="테스트", price=closes[-1], market_cap=200 * 억,
        per=10.0, pbr=1.0, volume=vol[-1], chart_df=df,
    )


def test_momentum_volume_component_zero_when_illiquid():
    """빅솔론 구조 — 거래대금이 10억 미만이면 상대 확장이 커도 vol 성분 0.

    구 수식(vol5/vol20)에서는 만점을 받던 패턴이다."""
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]   # 완만한 상승(정배열)
    values = [1 * 억] * 55 + [3 * 억] * 5                        # 상대 3배 확장, 절대는 빈약
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["adtv20_med"] is not None
    # liq_gate=0 -> 곱셈 게이트로 vol 성분이 0 -> momentum 상한 0.75
    assert scores["momentum"] <= 0.76


def test_momentum_volume_component_rewards_liquid_expansion():
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]
    values = [100 * 억] * 55 + [200 * 억] * 5   # 절대 유동성 충분 + 상대 2배
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    assert scores["momentum"] > 0.85


def test_momentum_volume_component_blocked_by_surge_cap():
    """5일 평균이 60일 평균의 5배 이상이면 펌프로 보고 vol 성분 0."""
    closes = [10_000.0 * (1 + 0.002 * i) for i in range(60)]
    values = [100 * 억] * 55 + [600 * 억] * 5   # surge >= 5.0
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["value_surge"] >= 5.0
    assert scores["momentum"] <= 0.76


def test_high20_proximity_rescaled_no_free_points():
    """20일 고가의 90% 미만이면 고가근접 성분이 0 — 무상 바닥점수 제거."""
    closes = [10_000.0] * 40 + [12_000.0] + [10_000.0] * 19   # 현재가/high20 ≈ 0.833
    values = [100 * 억] * 60
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    atoms = scores["_atoms"]
    assert atoms["high20_proximity"] < 0.90
    assert atoms["high20_prox_score"] == 0.0


def test_high20_prox_score_full_at_new_high():
    closes = [10_000.0 * (1 + 0.003 * i) for i in range(60)]   # 매일 신고가
    values = [100 * 억] * 60
    scores = compute_strategy_scores(_momentum_snap(values, closes), None)
    assert scores["_atoms"]["high20_prox_score"] == pytest.approx(1.0, abs=0.01)


def test_high20_prox_halved_without_volume_confirmation():
    """거래량 확장(value_ratio>=1.2) 없는 고가근접은 절반 페널티."""
    closes = [10_000.0 * (1 + 0.003 * i) for i in range(60)]
    flat = [100 * 억] * 60                       # value_ratio ≈ 1.0
    s_flat = compute_strategy_scores(_momentum_snap(flat, closes), None)
    expanding = [100 * 억] * 55 + [150 * 억] * 5   # value_ratio >= 1.2
    s_exp = compute_strategy_scores(_momentum_snap(expanding, closes), None)
    assert s_flat["_atoms"]["high20_prox_score"] < s_exp["_atoms"]["high20_prox_score"]


def test_atoms_none_safe_without_value_column():
    """value 컬럼이 없어도 NaN 전파 없이 0 성분으로 수렴한다."""
    closes = [10_000.0] * 60
    df = _make_chart_df(closes, [1000] * 60)     # value 없음
    snap = StockSnapshot(
        ticker="000000", name="구캐시", price=10_000.0, market_cap=200 * 억,
        per=10.0, pbr=1.0, volume=1000, chart_df=df,
    )
    scores = compute_strategy_scores(snap, None)
    assert scores["_atoms"]["adtv20_med"] is None
    assert not math.isnan(scores["momentum"])
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_factors.py -k "momentum_volume or high20_prox or atoms_none" -v`
Expected: FAIL — `KeyError: 'adtv20_med'`

- [ ] **Step 3: `_extract_atoms`에 거래대금 원자를 추가한다**

`atoms` 초기화 dict에 키 4개를 추가한다:

```python
        "adtv20_med": None,
        "value_ratio": None,
        "value_surge": None,
        "high20_prox_score": None,
```

`_extract_atoms` 본문 끝(`return atoms` 직전)에 계산을 추가한다:

```python
    # 유동성 인지 아크(A2): 거래'대금' 기준 원자. `value` 컬럼이 없는 구 캐시
    # DataFrame에서는 전부 None으로 남고, 스코어 함수가 0 성분으로 처리한다.
    if chart_df is not None and "value" in chart_df.columns:
        atoms["adtv20_med"] = adtv_median(chart_df)
        vals = pd.to_numeric(chart_df["value"], errors="coerce").dropna()
        if len(vals) >= 20:
            v5 = _safe(vals.tail(5).mean())
            v20 = _safe(vals.tail(20).mean())
            if v5 is not None and v20:
                atoms["value_ratio"] = v5 / v20
            v60 = _safe(vals.tail(min(60, len(vals))).mean())
            if v5 is not None and v60:
                atoms["value_surge"] = v5 / v60

    # A3: 고가근접 재스케일 + 거래량 확인. 구 high20_proximity는 관측용으로
    # 남기고(다른 소비자·로그 호환), 스코어는 이 파생값을 쓴다.
    prox = atoms["high20_proximity"]
    if prox is not None:
        base = _clamp01((prox - 0.90) / 0.10)
        vr = atoms["value_ratio"]
        confirm = 1.0 if (vr is not None and vr >= 1.2) else 0.5
        atoms["high20_prox_score"] = _clamp01(base * confirm)
```

파일 상단 import에 `liquidity_gate_score`를 추가한다(`adtv_median`은 Task 3에서 이미 추가됨):

```python
from services.discovery.liquidity import (
    adtv_median,
    downside_consistency_ok,
    has_zero_volume_day,
    liquidity_gate_score,
)
```

- [ ] **Step 4: `_score_momentum`의 두 성분을 교체한다**

```python
def _score_momentum(atoms: dict) -> float:
    """MA 정배열 + MACD>시그널 + 20일 고가근접(재스케일·거래량확인) + 유동성
    인지 거래대금 성분.

    거래대금 성분(A2)이 곱셈 게이트인 것이 핵심이다 — 절대 유동성(liq_gate)이
    0이면 상대 확장이 아무리 커도 0점이다. 구 수식 clamp01(vol5/vol20 - 1.0)은
    스케일 불변이라 ADTV 3억 종목과 3000억 종목을 동일하게 채점했고, 분모가
    작을수록 만점을 받기 쉬워 저유동성을 능동적으로 선호했다.
    """
    sma5, sma20, sma60 = atoms["sma5"], atoms["sma20"], atoms["sma60"]
    align_checks = []
    if sma5 is not None and sma20 is not None:
        align_checks.append(1.0 if sma5 > sma20 else 0.0)
    if sma20 is not None and sma60 is not None:
        align_checks.append(1.0 if sma20 > sma60 else 0.0)
    if sma5 is not None and sma60 is not None:
        align_checks.append(1.0 if sma5 > sma60 else 0.0)
    ma_alignment = (sum(align_checks) / len(align_checks)) if align_checks else 0.0

    macd_diff = atoms["macd_diff"]
    macd_bullish = 1.0 if (macd_diff is not None and macd_diff > 0) else 0.0

    high20_component = _clamp01(atoms.get("high20_prox_score"))

    liq_gate = liquidity_gate_score(atoms.get("adtv20_med"))
    value_ratio = atoms.get("value_ratio")
    rel = _clamp01(value_ratio - 1.0) if value_ratio is not None else 0.0
    surge = atoms.get("value_surge")
    surge_ok = 0.0 if (surge is not None and surge >= 5.0) else 1.0
    vol_component = _clamp01(liq_gate * rel * surge_ok)

    return _clamp01((ma_alignment + macd_bullish + high20_component + vol_component) / 4.0)
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_factors.py -v`
Expected: 전부 통과. 기존 momentum 테스트가 새 수식과 충돌하면, 기존 테스트의 픽스처에 `value` 컬럼을 더해 의도를 유지하도록 고친다(수식 롤백이 아니라 픽스처 갱신 — 구 수식이 결함이므로).

- [ ] **Step 6: 커밋한다**

```bash
git add backend/services/discovery/factors.py backend/tests/test_services/test_discovery_factors.py
git commit -m "feat(discovery): momentum 거래량 성분을 곱셈 유동성 게이트로 교체 + 고가근접 무상점수 제거(A2/A3)"
```

---

## Task 5: flow 결측 재정규화 폐기 (B)

편향의 두 번째이자 더 결정적인 원인을 제거한다. 소형주에서만 momentum 가중이 33% 증폭되던 메커니즘이다.

**Files:**
- Modify: `backend/services/discovery/ranker.py:351-387`
- Test: `backend/tests/test_services/test_discovery_ranker.py`

**Interfaces:**
- Consumes: 없음(순수 수정)
- Produces: `_effective_weights(base_weights, flow_present)` 시그니처 불변. `flow_present=True` 경로 동작 불변, `False`일 때 재분배 없이 `flow=0.0`만 세팅.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_discovery_ranker.py`에 추가한다:

```python
# ---------------------------------------------------------------------------
# B: flow 결측 재정규화 폐기
# ---------------------------------------------------------------------------

BULLISH = {"momentum": 0.40, "pullback": 0.25, "flow": 0.25, "meanrev": 0.10,
           "threshold": 0.55, "daily_cap": 5}


def test_flow_present_weights_unchanged():
    """수급 랭킹에 있는 종목은 base 가중 그대로 — 기존 동작 유지."""
    w = _effective_weights(BULLISH, True)
    assert w["momentum"] == pytest.approx(0.40)
    assert w["flow"] == pytest.approx(0.25)


def test_flow_missing_no_redistribution():
    """핵심 회귀 — flow 결측이어도 momentum 가중이 증폭되지 않는다.

    구 동작: scale=1/0.75=1.333 -> momentum 0.40 -> 0.533 (33% 증폭).
    신 동작: momentum 0.40 유지, flow 자리만 0."""
    w = _effective_weights(BULLISH, False)
    assert w["momentum"] == pytest.approx(0.40)
    assert w["pullback"] == pytest.approx(0.25)
    assert w["meanrev"] == pytest.approx(0.10)
    assert w["flow"] == 0.0


def test_flow_missing_weights_sum_below_one():
    """수급 미확인은 '정보 부재'가 아니라 '검증 실패' — composite가 자연히 낮아진다."""
    w = _effective_weights(BULLISH, False)
    total = sum(w[k] for k in ("momentum", "pullback", "flow", "meanrev"))
    assert total == pytest.approx(0.75)


def test_non_strategy_keys_pass_through():
    w = _effective_weights(BULLISH, False)
    assert w["threshold"] == 0.55
    assert w["daily_cap"] == 5


def test_bixolon_regression_composite_drops():
    """빅솔론 실측 재현 — 재정규화 폐기로 0.636 -> 0.477 대역."""
    raw = {"momentum": 0.7411, "pullback": 0.7223, "flow": 0.0, "meanrev": 0.0}
    w = _effective_weights(BULLISH, False)
    composite = sum(raw[k] * w[k] for k in raw)
    assert composite == pytest.approx(0.477, abs=0.01)
    assert composite < 0.55          # 문턱 미달 = 승격 안 됨


def test_flow_present_high_scorer_unchanged():
    """자이에스앤디 실측 재현 — flow_present 종목은 점수가 전혀 변하지 않는다."""
    raw = {"momentum": 1.0, "pullback": 0.50, "flow": 0.67, "meanrev": 0.0}
    w = _effective_weights(BULLISH, True)
    composite = sum(raw[k] * w[k] for k in raw)
    assert composite == pytest.approx(0.6925, abs=0.01)
    assert composite >= 0.55
```

파일 상단 import에 `_effective_weights`를 추가한다(비공개 함수지만 같은 패키지 테스트이므로 직접 import 한다 — 기존 ranker 테스트 관용구를 따를 것).

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_ranker.py -k "flow_missing or bixolon" -v`
Expected: FAIL — `test_flow_missing_no_redistribution`에서 `0.533 != 0.40`

- [ ] **Step 3: 재정규화를 폐기한다**

`backend/services/discovery/ranker.py`의 `_effective_weights`를 교체한다:

```python
def _effective_weights(base_weights: dict, flow_present: bool) -> dict:
    """랭킹에 실제로 적용할 전략 가중.

    **유동성 인지 아크(B, 2026-07-27): 구 DQ-2 재정규화를 폐기했다.**

    구 동작은 `flow_present=False`일 때 flow 가중을 나머지 3전략에 재분배했다.
    의도는 "수급 데이터가 없는 종목을 부당하게 벌하지 않는다"였으나, ka10131
    수급 랭킹이 상위 약 100행만 수집되므로 사실상 **소형주 전체**가 결측이 되고,
    그 집단에서만 선택적으로 momentum 가중이 증폭됐다(bullish 실측: 0.40 ->
    0.533, +33%). momentum은 구 수식에서 저유동성을 선호했으므로, 두 편향이
    곱해져 "승격 종목이 전부 저유동성 momentum"이라는 결과를 만들었다.

    신 동작: flow 결측은 **검증 실패**로 취급한다. 재분배 없이 flow 자리만
    0으로 두면 composite가 그만큼 자연히 낮아진다. 실측(2026-07-23 배치)상
    threshold 0.55를 유지해도 17종이 통과해 daily_cap 5를 채우고 남는다 —
    문턱 재산출은 불필요하다.

    `flow_present=True` 경로와 STRATEGIES 밖 키(threshold/daily_cap) 통과
    규약은 불변이다.
    """
    result = dict(base_weights)
    if flow_present:
        return result
    result["flow"] = 0.0
    return result
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_discovery_ranker.py -v`
Expected: 전부 통과. 구 재분배 동작을 검증하던 기존 테스트가 있으면 삭제하지 말고 **신 동작으로 갱신**하고, 주석에 "DQ-2 재정규화는 2026-07-27 아크에서 폐기됨"을 남긴다.

- [ ] **Step 5: 커밋한다**

```bash
git add backend/services/discovery/ranker.py backend/tests/test_services/test_discovery_ranker.py
git commit -m "feat(discovery): flow 결측 가중 재정규화 폐기 — 소형주 momentum 33% 증폭 제거(B)"
```

---

## Task 6: 유동성 반응형 사이징 캡 (C1)

**Files:**
- Modify: `backend/services/trading/r_sizing.py` (캡 결합 헬퍼 추가)
- Modify: `backend/services/trading/portfolio_agent.py:279`(`_calculate_max_position_value`)
- Modify: `backend/agents/graph/kr_stock_nodes/decision_nodes.py`(두 번째 사이징 지점)
- Test: `backend/tests/test_services/test_r_sizing_liquidity.py` (신규)

**Interfaces:**
- Consumes: `liquidity.liquidity_cap_value`, `liquidity.participation_rate`
- Produces: `r_sizing.apply_liquidity_cap(base_cap, adtv, equity) -> tuple[float, Optional[str]]` — (적용된 캡, 바인딩 사유 또는 None). 사유 문자열은 로깅/프롬프트용.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_r_sizing_liquidity.py`:

```python
"""C1: 유동성 반응형 사이징 캡.

게이트(참여율 1%)를 통과한 종목도 유동성에 비례해 포지션을 줄인다. 게이트가
'진입 자격', 이 캡이 '실제 크기'다."""

import pytest

from services.trading.r_sizing import SKIP_MIN_EQUITY_PCT, apply_liquidity_cap

억 = 100_000_000.0
EQUITY = 500_000_000.0


def test_no_cap_when_adtv_missing():
    """ADTV를 모르면 캡을 적용하지 않는다 — 이미 A1 게이트를 통과한 종목이고,
    R-cap과 4% 캡은 여전히 작동한다(fail-open, 단 경고 사유 반환)."""
    cap, reason = apply_liquidity_cap(20_000_000, None, EQUITY)
    assert cap == 20_000_000
    assert reason == "adtv_unknown"


def test_cap_binds_for_thin_stock():
    """ADTV 20억 -> 0.5% = 1000만원으로 축소."""
    cap, reason = apply_liquidity_cap(20_000_000, 20 * 억, EQUITY)
    assert cap == pytest.approx(10_000_000)
    assert reason == "liquidity_cap"


def test_cap_does_not_bind_for_liquid_stock():
    """ADTV 400억 -> 0.5% = 2억 > 기존 캡 2000만원이므로 기존 캡 유지."""
    cap, reason = apply_liquidity_cap(20_000_000, 400 * 억, EQUITY)
    assert cap == 20_000_000
    assert reason is None


def test_skip_when_cap_below_one_percent_of_equity():
    """캡이 계좌의 1%(500만원) 미만이면 0을 반환해 진입을 포기한다.

    소액 포지션은 체결단위 미달과 고정 수수료·호가단위 마찰로 실효 비용률이
    오히려 올라간다."""
    cap, reason = apply_liquidity_cap(20_000_000, 5 * 억, EQUITY)   # 0.5% = 250만원
    assert cap == 0.0
    assert reason == "liquidity_too_thin"


def test_skip_threshold_is_one_percent_of_equity():
    assert SKIP_MIN_EQUITY_PCT == pytest.approx(0.01)


def test_zero_equity_is_safe():
    cap, reason = apply_liquidity_cap(20_000_000, 20 * 억, 0.0)
    assert cap >= 0.0
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_r_sizing_liquidity.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_liquidity_cap'`

- [ ] **Step 3: 캡 결합 헬퍼를 구현한다**

`backend/services/trading/r_sizing.py` 끝에 추가한다:

```python
# 유동성 캡이 계좌의 이 비율 미만으로 포지션을 밀어내면 진입 자체를 포기한다.
# 소액 포지션은 체결단위 미달 + 고정 수수료·호가단위 마찰로 실효 비용률이
# 오히려 올라간다.
SKIP_MIN_EQUITY_PCT = 0.01


def apply_liquidity_cap(
    base_cap: float,
    adtv: Optional[float],
    equity: float,
) -> tuple[float, Optional[str]]:
    """유동성 참여율 캡을 기존 캡에 결합한다.

    포지션은 일평균 거래대금의 `SIZING_PARTICIPATION_PCT`(0.5%)를 넘지 않는다 —
    한국 퀀트 실무 표준. 계좌 5억 기준 ADTV 40억이면 풀사이즈(2000만원), 20억이면
    1000만원으로 자동 축소된다.

    Returns (적용 캡, 사유):
    - `adtv`가 None이면 캡 미적용 + "adtv_unknown"(fail-open). 이미 발굴 A1
      게이트를 통과한 종목이고 R-cap·4% 캡이 여전히 작동하므로, 여기서
      fail-closed로 막으면 조회 실패가 곧 매매 정지가 된다.
    - 캡이 계좌의 1% 미만이면 0.0 + "liquidity_too_thin"(진입 포기).
    - 캡이 실제로 바인딩하면 "liquidity_cap", 아니면 None.
    """
    from services.discovery.liquidity import liquidity_cap_value

    liq_cap = liquidity_cap_value(adtv)
    if liq_cap is None:
        return base_cap, "adtv_unknown"

    if equity > 0 and liq_cap < equity * SKIP_MIN_EQUITY_PCT:
        return 0.0, "liquidity_too_thin"

    if liq_cap < base_cap:
        return liq_cap, "liquidity_cap"

    return base_cap, None
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_r_sizing_liquidity.py -v`
Expected: 6 passed

- [ ] **Step 5: 두 사이징 지점에 배선한다**

`portfolio_agent._calculate_max_position_value`에 `adtv` 인자를 추가하고, 기존 `min()` 결과에 캡을 결합한다. 시그니처를 바꾼다:

```python
    def _calculate_max_position_value(
        self,
        total_equity: float,
        risk_score: int,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        adtv: Optional[float] = None,
    ) -> float:
```

기존 R-cap `min()` 결합 직후에 추가한다:

```python
        # C1(유동성 인지): 유동성 참여율 캡을 마지막에 결합한다. adtv=None이면
        # 캡 미적용(fail-open) — A1 게이트를 이미 통과한 종목이다.
        max_value, liq_reason = apply_liquidity_cap(max_value, adtv, total_equity)
        if liq_reason in ("liquidity_cap", "liquidity_too_thin"):
            logger.info(
                f"[PortfolioAgent] 유동성 캡 적용: reason={liq_reason} "
                f"adtv={adtv} max_value={max_value:,.0f}"
            )
```

`portfolio_agent.py` 상단 import에 `from services.trading.r_sizing import apply_liquidity_cap`을 추가한다(기존 `r_cap_value` import 옆).

**ADTV 출처와 주문 직전 재계산** — `_calculate_max_position_value` 호출부(142행)에 넘길 `adtv`는 다음 순서로 구한다. 이 조회 헬퍼를 `portfolio_agent`에 추가한다:

```python
    async def _resolve_adtv(self, ticker: str) -> Optional[float]:
        """사이징 시점의 ADTV. 승격(EOD)과 진입(수일 후) 사이 유동성이 변하므로
        최신 일봉으로 재계산하고, 실패 시에만 승격 당시 저장값으로 폴백한다.

        never-raise: 둘 다 실패하면 None을 반환하고 apply_liquidity_cap이
        캡 미적용(fail-open)으로 처리한다."""
        from services.discovery.liquidity import adtv_median

        try:
            client = await get_shared_kiwoom_client_async()
            df = await client.get_daily_chart_df(ticker)
            adtv = adtv_median(df)
            if adtv is not None:
                return adtv
        except Exception as e:
            logger.warning(f"[PortfolioAgent] ADTV 재계산 실패 {ticker}: {e}")

        try:
            return self._stored_adtv(ticker)   # factor_json.adtv20_med 폴백
        except Exception:
            return None
```

`_stored_adtv`는 `discovery_candidates`/워치 레코드에 저장된 `adtv20_med`를 읽는 얇은 조회다(Task 3에서 `factor_json`에 넣었다). 조회 경로가 없으면 `None`을 반환하도록 두고, 폴백 부재가 곧 캡 미적용이 되게 한다.

**두 번째 사이징 지점** — `backend/agents/graph/kr_stock_nodes/decision_nodes.py:357`의 `r_cap_value` 결합 **직후**에 같은 캡을 적용한다. 이 경로의 자본 베이스는 계좌 총평가액이 아니라 `orderable_amount`(가용현금)이므로 그대로 넘긴다(기존 주석의 의도적 차이를 유지):

```python
from services.trading.r_sizing import apply_liquidity_cap, r_cap_value
```

```python
            # C1(유동성 인지): R-cap 결합 직후 유동성 참여율 캡을 적용한다.
            # equity 베이스는 이 경로가 원래 쓰는 orderable_amount 그대로 —
            # r_cap_value와 동일한 기준을 쓴다.
            _adtv = None
            try:
                from services.discovery.liquidity import adtv_median
                _adtv = adtv_median(await client.get_daily_chart_df(stk_cd))
            except Exception as e:
                logger.warning("liquidity_adtv_fetch_failed", stk_cd=stk_cd, error=str(e))

            investment_amount, _liq_reason = apply_liquidity_cap(
                investment_amount, _adtv, orderable_amount
            )
            if _liq_reason in ("liquidity_cap", "liquidity_too_thin"):
                logger.info(
                    "liquidity_cap_applied",
                    stk_cd=stk_cd, reason=_liq_reason,
                    adtv=_adtv, investment_amount=investment_amount,
                )
```

`investment_amount`가 `0.0`이 되면 이후 수량 계산이 0이 되어 주문이 나가지 않는다 — 이것이 "진입 포기"의 실제 구현이며, 별도 분기를 추가하지 않는다(기존 `quantity <= 0` 경로가 이미 이를 처리한다).

- [ ] **Step 6: 무회귀와 부팅을 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/ -k "sizing or portfolio_agent or r_cap" -q`
Expected: 전부 통과(기존 사이징 테스트는 `adtv` 기본값 `None`이라 동작 불변).

Run: `cd backend && env -u OPENROUTER_API_KEY python -c "import app.main; print('boot ok')"`

- [ ] **Step 7: 커밋한다**

```bash
git add backend/services/trading/r_sizing.py backend/services/trading/portfolio_agent.py backend/agents/graph/kr_stock_nodes/decision_nodes.py backend/tests/test_services/test_r_sizing_liquidity.py
git commit -m "feat(trading): 유동성 반응형 사이징 캡(ADTV 0.5%) + 과소포지션 진입포기(C1)"
```

---

## Task 7: 유동성 사실 프롬프트 전파 (C2)

하드 게이트 **뒤에 놓는 보조 방어선**이다. 단독 방어선으로 취급하지 않는다.

US 신호 전파(`us_market_context`)와 **완전히 동일한 배선 패턴**을 재사용한다 — 라이브 소비 확증(402340 사례)을 받은 검증된 경로다.

**Files:**
- Create: `backend/services/agent_chat/liquidity_note.py` (한 줄 요약 빌더, 순수 함수)
- Modify: `backend/services/agent_chat/models.py` — `MarketContext`에 `liquidity_context: Optional[str] = None` 필드 추가(`us_market_context` 바로 옆)
- Modify: `backend/services/agent_chat/agents/risk_agent.py:83, :135` — 프롬프트 템플릿 2곳에 `{liquidity_context}` 추가, `:186` 부근 `.format(...)`에 인자 추가
- Modify: `backend/services/agent_chat/coordinator.py` — `MarketContext` 생성 시 `liquidity_context` 채움(`us_market_context`를 채우는 지점과 동일)
- Test: `backend/tests/test_services/test_agent_chat_liquidity_note.py` (신규)

**Interfaces:**
- Consumes: `factor_json.adtv20_med`(Task 3), `liquidity.participation_rate`(Task 2)
- Produces: `build_liquidity_note(adtv: Optional[float], position_notional: Optional[float]) -> str` — 값이 없으면 빈 문자열.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_services/test_agent_chat_liquidity_note.py`:

```python
"""C2: 리스크 에이전트 유동성 한 줄 주입.

하드 게이트(A1/C1) 뒤의 보조 방어선이다. LLM 판단은 결정론적이지 않으므로
이 테스트는 '문자열이 올바르게 만들어지는지'만 검증한다."""

import pytest

from services.agent_chat.liquidity_note import build_liquidity_note

억 = 100_000_000.0


def test_note_present_when_adtv_known():
    text = build_liquidity_note(20 * 억, 20_000_000)
    assert "20.0억" in text
    assert "1.0%" in text


def test_note_omitted_when_adtv_missing():
    assert build_liquidity_note(None, 20_000_000) == ""


def test_note_omitted_when_notional_missing():
    assert build_liquidity_note(20 * 억, None) == ""
    assert build_liquidity_note(20 * 억, 0) == ""


def test_note_flags_high_participation():
    text = build_liquidity_note(5 * 억, 20_000_000)   # 참여율 4.0%
    assert "4.0%" in text
    assert "초과" in text


def test_note_no_warning_at_or_below_one_percent():
    text = build_liquidity_note(20 * 억, 20_000_000)   # 정확히 1.0%
    assert "초과" not in text


def test_note_never_raises_on_zero_adtv():
    assert build_liquidity_note(0, 20_000_000) == ""
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_agent_chat_liquidity_note.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.agent_chat.liquidity_note'`

- [ ] **Step 3: 한 줄 요약 빌더를 구현한다**

`backend/services/agent_chat/liquidity_note.py`. 로컬 LLM(deepseek-r1) 컨텍스트 부담을 고려해 6개 필드를 나열하지 않고 **한 문장으로 압축**한다:

```python
"""리스크 에이전트 프롬프트용 유동성 한 줄 (순수 함수).

US 신호 전파(`us_market_context`, 라이브 소비 확증 402340)와 동일한 패턴이다.
이것은 하드 게이트(A1 발굴 게이트·C1 사이징 캡) **뒤의 보조 방어선**이며,
LLM 판단은 결정론적이지 않으므로 유일한 방어선으로 삼지 않는다.
"""

from __future__ import annotations

from typing import Optional


def build_liquidity_note(
    adtv: Optional[float], position_notional: Optional[float]
) -> str:
    """유동성 한 줄. 값이 없으면 빈 문자열(프롬프트에서 줄 자체가 사라진다).

    never-raise — 프롬프트 조립이 이 함수 때문에 실패하면 안 된다."""
    from services.discovery.liquidity import participation_rate

    if not adtv or not position_notional:
        return ""

    rate = participation_rate(position_notional, adtv)
    if rate is None:
        return ""

    warn = " ⚠️ 참여율 1% 초과 — 손절 시 하락일 호가가 얇아 청산 위험" if rate > 0.01 else ""
    return (
        f"\n### 유동성\n"
        f"- 일평균 거래대금(20일 중앙값): {adtv / 1e8:,.1f}억원\n"
        f"- 이 포지션의 참여율: {rate * 100:.1f}%{warn}"
    )
```

`backend/services/agent_chat/models.py`의 `MarketContext`에 필드를 추가한다(`us_market_context` 바로 아래):

```python
    # C2(유동성 인지): 리스크 에이전트 프롬프트에 주입할 유동성 한 줄.
    # None/빈 문자열이면 프롬프트에서 해당 섹션이 사라진다(us_market_context 패턴).
    liquidity_context: Optional[str] = None
```

`backend/services/agent_chat/agents/risk_agent.py`의 프롬프트 템플릿 **2곳**(발표용 83행 부근, 투표용 135행 부근)에서 `{us_market_context}` 바로 아래에 `{liquidity_context}`를 추가하고, 발표용 템플릿의 "반드시 포함할 내용" 앞에 판정 기준을 명문화한다:

```
**유동성 판정 기준: 위 참여율이 1%를 초과하면 반대표(SELL 또는 HOLD)를 던지십시오.**
저유동성 종목은 손절이 발동하는 하락일에 매수호가가 증발해 설계된 손절가에
체결되지 않습니다.
```

`.format(...)` 호출 2곳에 인자를 추가한다(186행 패턴 그대로):

```python
            liquidity_context=context.liquidity_context or "",
```

`backend/services/agent_chat/coordinator.py`에서 `MarketContext`를 만들 때 채운다 — `us_market_context`를 채우는 지점 바로 옆에 두어 배선이 흩어지지 않게 한다:

```python
        # C2: 유동성 한 줄. adtv는 워치 레코드/factor_json의 adtv20_med,
        # 없으면 최신 일봉으로 재계산(never-raise, 실패 시 빈 문자열).
        _liq_note = ""
        try:
            from services.agent_chat.liquidity_note import build_liquidity_note
            _liq_note = build_liquidity_note(_adtv, _position_notional)
        except Exception as e:
            logger.warning("liquidity_note_failed", error=str(e))
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/test_services/test_agent_chat_liquidity_note.py -v`
Expected: 6 passed

- [ ] **Step 5: 프롬프트 조립 무회귀를 확인한다**

`{liquidity_context}` 플레이스홀더를 템플릿에 추가하고 `.format()` 인자를 빠뜨리면 `KeyError`로 **토론 전체가 죽는다**. 기존 risk_agent 테스트를 돌려 확인한다:

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest tests/ -k "risk_agent or agent_chat" -q`
Expected: 전부 통과

- [ ] **Step 6: 커밋한다**

```bash
git add backend/services/agent_chat/liquidity_note.py backend/services/agent_chat/models.py backend/services/agent_chat/agents/risk_agent.py backend/services/agent_chat/coordinator.py backend/tests/test_services/test_agent_chat_liquidity_note.py
git commit -m "feat(agent-chat): 리스크 에이전트에 유동성 사실 주입 — 참여율>1% 반대표 기준(C2)"
```

---

## Task 8: 통합 검증 — 실측 재현

배포 전 마지막 게이트. 라이브 DB의 실제 후보로 새 파이프라인이 의도대로 작동하는지 확인한다.

**Files:**
- Create: `backend/scripts/verify_liquidity_arc.py` (일회성 검증 스크립트)

- [ ] **Step 1: 전체 스위트를 돌린다**

Run: `cd backend && env -u OPENROUTER_API_KEY python -m pytest -q`
Expected: 전부 통과. 실패가 있으면 그 테스트가 구 동작을 검증하던 것인지 판단하고, 구 동작이면 신 동작으로 갱신, 아니면 회귀이므로 수정한다.

- [ ] **Step 2: 실측 재현 스크립트를 작성한다**

`backend/scripts/verify_liquidity_arc.py` — 2026-07-23 배치(`discovery_candidates`)의 저장된 `strategy_scores_json`으로 신규 `_effective_weights`를 적용해 composite를 재계산하고, 승격 5종의 운명이 설계 문서 §2.2와 일치하는지 확인한다.

```python
"""유동성 인지 아크 배포 전 실측 재현 검증(일회성).

설계 문서 §2.2의 표를 실제 코드로 재현한다. 기대:
- 자이에스앤디/롯데렌탈(flow_present=True): 점수 무변화
- 슈프리마HQ/라파스/빅솔론(flow 결측): 0.55 미만으로 하락 = 승격 안 됨
"""
import json
import sqlite3
import sys

from services.discovery.ranker import _effective_weights

BULLISH = {"momentum": 0.40, "pullback": 0.25, "flow": 0.25, "meanrev": 0.10}
EXPECT_SURVIVE = {"317400", "089860"}
EXPECT_DROP = {"094840", "214260", "093190"}

db = sqlite3.connect("data/storage.db")
rows = db.execute(
    "SELECT ticker, name, composite_score, strategy_scores_json "
    "FROM discovery_candidates WHERE trade_date='2026-07-23' AND promoted=1"
).fetchall()

failures = []
for ticker, name, old, sj in rows:
    s = json.loads(sj)
    raw = {k: (s.get(k) or 0.0) for k in BULLISH}
    flow_present = (s.get("_weights", {}) or {}).get("flow", 0.0) > 0
    w = _effective_weights(dict(BULLISH), flow_present)
    new = sum(raw[k] * w[k] for k in BULLISH)
    status = "생존" if new >= 0.55 else "탈락"
    print(f"{ticker} {name:<12} {old:.4f} -> {new:.4f}  flow={flow_present}  {status}")

    if ticker in EXPECT_SURVIVE and new < 0.55:
        failures.append(f"{ticker} 생존 기대했으나 탈락")
    if ticker in EXPECT_DROP and new >= 0.55:
        failures.append(f"{ticker} 탈락 기대했으나 생존")

if failures:
    print("\n검증 실패:", *failures, sep="\n  ")
    sys.exit(1)
print("\n✅ 실측 재현 일치 — 설계 문서 §2.2와 동일")
```

- [ ] **Step 3: 검증을 실행한다**

Run: `cd backend && env -u OPENROUTER_API_KEY python scripts/verify_liquidity_arc.py`
Expected: 5행 출력 후 `✅ 실측 재현 일치`

- [ ] **Step 4: 커밋한다**

```bash
git add backend/scripts/verify_liquidity_arc.py
git commit -m "test: 유동성 인지 아크 실측 재현 검증 스크립트"
```

---

## 배포 절차 (구현 완료 후)

Task 1~5까지가 **A+B**다. Task 6~7이 **C**다. 스펙 §6에 따라 A → B → C 순차 배포하되, 코드는 한 브랜치에 쌓고 **배포 시점만 나눈다**(A/B는 발굴 경로라 EOD 1회로 함께 검증된다).

1. **안전창 확인**: 15:30~16:35가 아니고, 실 포지션 보유 중이면 장 마감 후일 것.
2. FF 병합 → `bash /Users/sunghoonk/.claude/jobs/73bb8bdd/tmp/restart-backend.sh`
3. `POST /trading/start` + `POST /agent-chat/start` 재발행.
4. 스모크: `python scripts/verify_liquidity_arc.py`로 배포된 코드 재확인.
5. **첫 EOD 관측**: `[Discovery]` 로그에서 `discovery_min_adtv_resolved` 값(계좌 5억이면 20억)과 `skip_reason` 분포(`liquidity_low` 건수)를 확인한다. 승격이 0건이면 문턱이 아니라 **유동성 게이트가 과했는지** 먼저 의심하고, `DISCOVERY_MIN_ADTV_FALLBACK`이 아니라 실측 분포를 다시 뽑아 판단한다(하드플로어 10억 밑으로는 절대 내리지 않는다).
6. 승격 종목의 ADTV가 전부 20억 이상인지 확인 — 이것이 이 아크의 수용 기준이다.

## 롤백

- **A1 게이트만**: `DISCOVERY_MIN_ADTV_FALLBACK`을 낮추는 것이 아니라, `scanner._resolve_min_adtv`가 `None`을 반환하게 하면 게이트가 꺼진다(스코어 수식 A2/A3와 B는 유지).
- **B**: `_effective_weights`에 구 재분배 블록을 되돌린다(단일 함수, 커밋 revert로 충분).
- A2/A3는 수식 변경이라 revert 단위가 Task 4 커밋 하나다.
