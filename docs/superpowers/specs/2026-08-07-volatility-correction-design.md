# 변동성 방어 정정 — 설계

- 날짜: 2026-08-07 (장 마감 후, 시스템 정지 상태에서 작업. 개장까지 약 62시간)
- 범위: 변동성 배수의 **입력·게이트·상수 소유권**을 바로잡는다. 레짐 판정 로직·앵커·일일 한도·게이트 검사 8은 건드리지 않는다.
- 상태: 사용자 승인 완료
- 선행: `d6d6905`(레짐 인지 노출도 제어 배포분) 위에서 작업

## 1. 문제 — 전제가 틀렸다

2026-08-07에 배포한 레짐 인지 노출도 제어는 **"국내 시세가 합성 데이터다"**라는 전제 위에 세워졌다. **그 전제가 틀렸다.**

### 반증

독립 출처(Yahoo Finance, `yfinance` — 이미 설치돼 있다)와 **행 단위로 일치**했다.

```
종목:  yfinance 005930.KS = 231,000    키움 = 231,000
       yfinance 000660.KS = 1,422,000  키움 = 1,422,000

지수:  Yahoo ^KS11        우리 DB
       07-28  −10.84%  =  −10.84%
       07-31  +17.91%  =  +17.91%
       08-07  −0.60%   =  −0.60%
```

`KIWOOM_IS_MOCK=true`는 **주문 실행만** 모의투자 서버로 보낸다. 시세·지수·재무는 실제 시장이다.

### 실제 KOSPI 변동성 (Yahoo `^KS11`, 2년)

```
20일 롤링 실현 연변동성
   5분위  13.4%      75분위  36.5%
  25분위  17.1%      95분위  75.9%
  중앙값  20.6%      최대   103.2%
  현재   101.7%  ← 2년 중 상위 1.1%
```

### 무엇이 잘못돼 있나

**① 위생 게이트가 실제 시장을 거부한다.** `[5.0, 60.0]`은 **2년 중 15.5%의 날**을, 그것도 변동성 상위 구간만 골라 `m_vol=1.0`으로 만든다. **방어가 가장 필요한 날에 정확히 꺼진다.** 지금이 그 상태다.

**② `M_vol` 입력이 SPY다.** "국내 지수가 모의라서" 내린 결정이었다. 우리는 한국 주식을 산다. `TARGET_VOL_PCT=18.0`은 KOSPI 중앙값 20.6%와 맞물리는 값이고, SPY(9~15%)에서는 `18/11`이 상한으로 클램프돼 배수가 영원히 논다.

**③ 상수의 소유자가 사람이다.** `[5, 60]`은 2026-08-06에 손으로 고른 값이고 두 달도 안 돼 틀렸다.

**④ 🔴 변동성 입력 시계열에 구멍이 있다.** `regime_snapshot`은 **EOD 체인이 돌 때만** 쓰인다. 그 체인은 장 마감 스케줄 틱이고 **따라잡기가 없다** — 그 순간 프로세스가 내려가 있으면 그날 데이터가 영구히 유실된다.

```
실제 거래일 16일 (07-16~08-07)  vs  regime_snapshot 15행
누락: 2026-07-21, 2026-08-06   ← 둘 다 재시작이 있던 날
```

`annualized_vol`은 최근 20**행**을 쓴다. 행과 거래일이 1:1이 아니면 **20일 창이 실제로는 22·23일**이 되고, 누락이 쌓일수록 벌어진다.

### 유효한 것 (버리지 말 것)

`agent_calibration`(40행) · `agent_chat_votes`(4,524표) · `agent_chat_decisions`(1,141건) ·
`discovery_candidates`(39,743행) · `kr_realized_pnl` · 성과 기록(왕복 11건, 승6/패5).
**전부 실제 시장에 대한 학습 데이터다.**

## 2. 사용자 결정

1. **`M_evidence`는 복원하지 않는다** — "표본이 작다"는 근거는 유효하나, 변동성 배수를 고치면 `m_vol=0.5`가 이미 절반을 줄이므로 중첩하지 않는다.
2. **위험 취향 상수를 전략 패널에 연다** — `target_vol_pct`, `vol_multiplier_min`.
3. **`vol_multiplier_min` 상한은 0.8** — 1.0을 허용하면 전략이 변동성 방어를 통째로 끌 수 있다.
4. **누락일 문제를 먼저 고치고 그 위에 검사를 얹는다.**

## 3. 핵심 판단 — 출처를 분리하니 검사가 필요 없어졌다

처음 제안은 "레벨↔등락률 정합성 검사"였다. **실제 데이터로 검증했더니 14쌍 중 3쌍이 오탐(21%)이었다** — 거래일이 빠지면 역산은 2일치, 보고값은 1일치라 어긋난다.

근본 원인은 **레벨과 등락률을 서로 다른 경로로 받아 대조**하려 한 것이다. 종가 하나만 저장하고 수익률을 우리가 계산하면 **어긋날 대상이 자체가 없다.**

그래서 검사를 추가하는 대신 **입력 자체를 구멍 없는 전용 시계열로 바꾼다.**

## 4. 만드는 것

| 유닛 | 파일 | 책임 |
|---|---|---|
| U0 | `services/trading/index_series.py` (신규) · `storage_service.py` | KOSPI 일별 종가 전용 시계열 + 자가치유 백필 |
| U1 | `services/trading/exposure_target.py` | 위생 게이트 제거 + 신선도 검사 |
| U2 | `strategy.py` · `models.py` · `strategy_apply.py` · `strategy_panel.py` · `exposure_target.py` | 두 상수를 전략 노브로 |
| U3 | `regime_judge.py` · `coordinator.py` | `M_vol` 입력을 `index_daily`로 |
| U4 | `docs/superpowers/specs/2026-08-07-regime-aware-exposure-design.md` | 정정 |

### U0 · 지수 시계열 전용 테이블

```sql
CREATE TABLE IF NOT EXISTS index_daily (
    trade_date TEXT PRIMARY KEY,   -- UNIQUE라 upsert가 구멍을 메운다
    close      REAL NOT NULL,
    source     TEXT NOT NULL,      -- 'yfinance:^KS11'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**등락률은 저장하지 않는다.** 종가에서 계산한다 — 두 값을 따로 받으면 어긋날 수 있다.

```python
INDEX_TICKER: str = "^KS11"
INDEX_SOURCE: str = "yfinance:^KS11"
INDEX_LOOKBACK_DAYS: int = 40

async def refresh_index_daily(lookback_days: int = INDEX_LOOKBACK_DAYS) -> Optional[int]:
    """최근 `lookback_days`의 KOSPI 종가를 upsert한다. 쓴 행 수를 돌려준다.
    never-raise -- 실패는 None.

    **매 실행이 창 전체를 다시 쓴다.** 프로세스가 며칠 내려가 있어도 다음
    실행이 구멍을 자동으로 메운다 -- 따라잡기 로직이 필요 없다.
    2026-08-07 이전 방식(`regime_snapshot`)은 EOD 체인이 도는 날에만
    행이 생겨 재시작 날마다 영구 유실이 발생했다.
    """
```

- `yfinance.Ticker("^KS11").history(period=f"{lookback_days}d")` — 동기 호출이므로
  `asyncio.to_thread`로 감싼다(EOD 오케스트레이터가 `compute_regime_snapshot`에 쓰는 패턴과 동일).
- 빈 결과·예외 → `None`. 부분 성공은 없다(받은 만큼 전부 upsert).
- `trade_date`는 `YYYY-MM-DD` 문자열. tz-aware 인덱스는 날짜만 취한다.

**저장소 함수**

```python
async def upsert_index_daily(rows: list[tuple[str, float]], source: str) -> int
    # INSERT OR REPLACE. 쓴 행 수 반환. 실패-무해(0 반환).

async def get_recent_index_closes(limit: int = 21) -> list[tuple[str, float]]
    # (trade_date, close) 시간 **오름차순**. 행 없으면 []. **DB 오류는 raise.**
    # 기본 21인 이유: 20개 수익률을 만들려면 종가가 21개 필요하다.
```

### U1 · 게이트 제거 + 신선도 검사

**제거**: `VOL_GATE_MIN_PCT`, `VOL_GATE_MAX_PCT`, 그리고 `compute_regime_target`의 게이트 분기.
변동성 값은 **있는 그대로** 쓴다 — 98%면 98%.

**신설(순수 함수 2개 — `index_series.py`에 둔다.** 시계열에 관한 함수이므로 시계열 모듈이 소유한다. `exposure_target`은 **이미 준비된 입력**만 받는 순수 계산으로 남긴다):

```python
INDEX_SERIES_MAX_AGE_DAYS: int = 7

def closes_to_returns(closes: list[float]) -> list[float]:
    """종가 시계열 → 일간 등락률(%). 시간 오름차순 입력, 길이 n-1 출력.
    0·비유한 종가가 끼면 그 쌍을 건너뛴다."""

def is_series_stale(latest_trade_date: str, today: date) -> bool:
    """최신 행이 `INDEX_SERIES_MAX_AGE_DAYS` 역일보다 오래됐으면 True.

    7역일인 이유: 설·추석 연휴(최대 5거래일 공백)에서 오탐이 나지 않으면서
    수집이 죽은 것은 일주일 안에 잡는다. 거래일 계산이 필요 없어
    휴장일 서비스에 의존하지 않는다(순수 함수 유지).

    `latest_trade_date` 파싱이 실패하면 **True**(=노후로 취급) --
    모르는 것을 신선하다고 보면 안 된다.
    """
```

`compute_regime_target`은 **새 인자 `series_stale: bool = False`**를 받는다.
호출자가 위 두 함수로 준비해 넘긴다.

변동성 분기:

| 상황 | `m_vol` | `degraded` |
|---|---|---|
| 표본 < `VOL_MIN_SAMPLES`(5) | 1.0 | `index_vol_insufficient` |
| 시계열이 오래됨 | 1.0 | `index_series_stale` |
| 정상 | `clamp(target_vol_pct/vol_ann, vol_multiplier_min, 1.0)` | — |

원값(`index_vol_annualized`)은 어느 경우에도 그대로 싣는다.

⚠️ **"변동성이 크다"는 저하 사유가 아니다.** 그것이 이번 사고의 전부였다.

### U2 · 위험 취향을 전략 노브로

| 노브 | 기본값 | 하드 바운드 | 근거 |
|---|---|---|---|
| `target_vol_pct` | 18.0 | **(10.0, 40.0)** | KOSPI 5분위 13.4% ~ 75분위 36.5%를 감싼다 |
| `vol_multiplier_min` | 0.5 | **(0.2, 0.8)** | 1.0을 허용하면 전략이 방어를 통째로 끈다 |

- `strategy.PositionSizingRules`에 두 필드(같은 기본값, `ge`/`le`는 하드 바운드와 동일)
- `models.RiskParameters`에 두 필드
- `strategy_apply.STRATEGY_MAPPED_FIELDS`에 두 항목, `_source_values()`에 두 줄
- `strategy_panel._SCHEMA_INSTRUCTION`에 설명 — **단위를 명시할 것**
  (`target_vol_pct`는 **퍼센트** 10~40, `vol_multiplier_min`은 **분율** 0.2~0.8)
- `compute_regime_target()`이 모듈 상수 대신 **인자로 받는다**:
  `target_vol_pct: float = TARGET_VOL_PCT_DEFAULT`, `vol_multiplier_min: float = VOL_MULTIPLIER_MIN_DEFAULT`

**`VOL_MULTIPLIER_MAX = 1.0`은 상수로 남긴다.** "앵커가 상한이고 배수는 깎기만 한다"는 계약이지 취향이 아니다.

### U3 · `M_vol` 입력 환원

`get_recent_macro_returns("SPY")` → `get_recent_index_closes()` + `closes_to_returns()`.

호출자는 `regime_judge.judge_regime`과 `coordinator._record_exposure_shadow` 둘이다.

**두 노브를 어디서 읽는가 — 서로 다르다:**
- `_record_exposure_shadow`는 코디네이터 메서드이므로 `self.risk_params`에서 직접 읽는다.
- `judge_regime`은 코디네이터를 모른다. **`run_daily_regime_cycle`이 코디네이터에서 두 값을 읽어 `judge_regime(target_vol_pct=..., vol_multiplier_min=...)`로 넘긴다.** `judge_regime`이 코디네이터를 직접 잡으면 판정 모듈이 실행 계층에 의존하게 되므로 그렇게 하지 않는다. 인자 기본값은 모듈 기본 상수다(코디네이터 조회 실패 시 그대로 쓰인다).

**SPY 수집(`macro_snapshot`)은 그대로 둔다** — 레짐 판정의 LLM 입력으로 계속 쓴다.
`regime_snapshot`도 그대로 둔다 — breadth·수급으로 레짐 라벨에 쓰인다. **변동성 계산만 떼어낸다.**

**스케줄 배선**: `run_daily_regime_cycle`(08:05)에서 `judge_regime()` **앞**에 `refresh_index_daily()`를 부른다. 순서는 `지수 수집 → 매크로 수집 → 레짐 판정 → 슬롯 적용`.

### U4 · 문서 정정

`2026-08-07-regime-aware-exposure-design.md`:
- §1의 "합성 시장" 서술 삭제 — 실제 시장임을 명시하고 반증 근거를 남긴다
- §3 U3의 C-1 근거 정정 — `TARGET_VOL_PCT=18.0`은 **KOSPI 중앙값 20.6%와 맞물리는 타당한 값**이었다. 틀린 것은 상수가 아니라 **입력을 SPY로 바꾼 것**이다
- §6 판정 기준의 `m_vol` 관련 항목을 KOSPI/`index_daily` 기준으로 재작성

## 5. 실패 처리

| 상황 | 처리 |
|---|---|
| `refresh_index_daily` 실패 | `None` 반환, 로그. 기존 행은 남아 있으므로 계산은 계속된다. 며칠 이어지면 신선도 검사가 잡는다 |
| `get_recent_index_closes` DB 오류 | **raise** → 호출자의 기존 `try/except`가 처리(판정 행 미기록 → 검사 8 스킵 → 슬롯 되돌리기) |
| 행 없음 / 표본 < 5 | `m_vol=1.0` + `index_vol_insufficient` |
| 시계열 노후 | `m_vol=1.0` + `index_series_stale` |
| 전략이 바운드 밖 값 제안 | `strategy_apply`가 클램프 |

**어떤 실패도 노출도를 위로 열지 않는다** — `m_vol=1.0`은 "깎지 않음"이지 "키움"이 아니다.

## 6. 테스트

**순수 함수(대부분)**
- `closes_to_returns`: 정상 / 0·비유한 종가 건너뜀 / 길이 n-1 / 빈 입력
- `is_series_stale`: 경계(7일 정확히·8일) / 연휴 5일 공백에서 오탐 없음
- `compute_regime_target`: **게이트 부재 확인 — 연 98%가 `m_vol=0.5`를 만드는가**(이 케이스가 사고의 원점) / 두 노브를 인자로 받는지 / `degraded`에 `index_vol_implausible`이 **더 이상 나오지 않는지**
- 앵커·일일 한도·`slots_for_target`은 **불변** — 회귀로 확인

**저장소**
- `upsert_index_daily`: 같은 `trade_date` 재삽입이 덮어쓰는가(구멍 메우기의 근거) / 실패-무해
- `get_recent_index_closes`: 시간 오름차순 / 행 없으면 `[]` / **DB 오류는 raise**

**수집**
- `refresh_index_daily`: 정상 / 빈 결과 → `None` / 예외 → `None`(never-raise) / **upsert 실패해도 거짓 성공을 보고하지 않는가**

**전략 노브**
- 클램프: `target_vol_pct` 5→10, 50→40 / `vol_multiplier_min` 0.1→0.2, 1.0→0.8
- `GATE_PROTECTED_FIELDS` 봉인 불변(`test_gate_protected_fields_never_move`)
- `strategy=None` 리셋 시 두 필드가 모델 기본값으로

⚠️ 테스트마다 물을 것: **"이 속성이 위반되면 이 테스트가 실제로 실패하는가."**
이 리포는 공허한 테스트가 3라운드 연속 나온 전력이 있다.

## 7. 배포 후 판정 (월요일)

`m_vol`·`index_vol_annualized`·`binding`은 `regime_judgment`가 아니라
`exposure_shadow`에만 저장된다(`insert_regime_judgment`는 `effective_target_pct`·
`degraded`만 싣는다). 그 행은 코디네이터의 `_record_exposure_shadow`가
`is_krx_open_cached()` 가드 뒤에서 5분 주기로 쓰므로 **09:00 개장 이후에만
존재한다.** 08:05 시점에는 아래를 두 시각으로 나눠서 본다.

### 08:05 확인 가능

| 확인 | 정상 | 실패 신호 |
|---|---|---|
| `index_daily` | **약 40행**, 최신이 **2거래일 이내** | 0행 = 수집 배선 실패 |
| `index_daily` 연속성 | **최근 1~2 거래일의 구멍은 정상**(아래 참고) | **오래된 구간**(3거래일 이상 전)에 구멍 = 문제 |
| `regime_judgment.effective_target_pct` | **0.15 근처**(≈0.1538 기대) | 0.30이면 `m_vol`이 안 물렸다 |
| `regime_judgment.degraded` | `index_vol_implausible`이 **없어야** 정상 | 있으면 게이트 제거 실패 |
| `risk_params` | `target_vol_pct=18.0`, `vol_multiplier_min=0.5` | 없으면 필드 추가 실패 |
| `regime:slot_baseline` | 행 존재 | 없으면 되돌리기 기계 무력 |

⚠️ **`index_daily` 연속성 재정정**: 원래 "거래일 누락 없음"이 정상 기준이었으나
**항상 참은 아니다.** yfinance는 당일 봉을 정산 전에 `Close=NaN`으로 돌려줄
때가 있고(2026-08-07 실측 — 금요일 봉이 다음날 아침에도 여전히 `NaN`),
`isfinite` 필터가 이를 걸러내면 그 구멍은 **원인이 upsert 창 부족이 아니라
Yahoo 정산 지연이다.** 다음 실행이 자동으로 메운다(§4 `refresh_index_daily`의
매 실행 전체 창 재기록). 최근 1~2 거래일의 구멍은 이 지연으로 정상 발생한다 —
**오래된 구간**(정산이 끝났을 시점)에 구멍이 남아 있을 때만 배선 실패로 본다.

### 09:05 이후 확인 가능

```sql
SELECT m_vol, index_vol_annualized, binding, degraded
FROM exposure_shadow ORDER BY created_at DESC LIMIT 1;
```

| 확인 | 정상 | 실패 신호 |
|---|---|---|
| `index_vol_annualized` | **90~110** 근처 | 9~15면 아직 SPY |
| `m_vol` | **0.5** (하한) | 1.0이면 세 원인 중 하나 — `degraded` 열로 구별한다: 게이트가 남아 있음(`index_vol_implausible`), 표본 부족(`index_vol_insufficient`), **시계열 노후**(`index_series_stale` — `index_daily` 최신 행이 `INDEX_SERIES_MAX_AGE_DAYS`(7일)보다 오래됨) |
| `degraded` | 위 세 값 중 아무것도 없어야 정상 | 있으면 위 표에서 원인 특정 |

**예상**: `ramped 0.3078 × m_vol 0.50 = 목표 15.39%` (현재 보유 15.78%).
사실상 동결 — 신규 매수는 막히고 기존 포지션은 유지된다. **2년 최고 변동성 국면에서 의도한 동작이다.**

### 슬롯 노브 — 월요일에 움직이는 것은 하나뿐

`max_open_positions`는 **7 유지가 정상이다.** `slots_for_target`은 상향만
하고 하향은 하지 않는데(§6 참고), 목표 0.1538 → `ceil(0.1538/0.05)=4`
→ `max(current_max, 4)`이고 `current_max`는 이미 7이므로 결과도 7이다.
월요일에 실제로 움직이는 노브는 **`max_single_position_pct` 0.03→0.05
하나뿐이다.**

## 8. 남는 위험

1. **`yfinance`는 비공식 소스다.** 키움과 값이 정확히 일치함을 확인했고(2026-08-07), 실패해도 `m_vol=1.0`으로 degrade하며, 이미 설치돼 있다. 더 나은 소스가 생기면 `source` 컬럼과 수집 함수만 바꾸면 된다.
2. **`vol_multiplier_min`이 변동성 36% 위에서 항상 바닥에 붙는다**(KOSPI 75분위 36.5%). 순수 변동성 타게팅이면 101.7%에서 `18/101.7=0.177`까지 줄여야 하는데 0.5에서 멈춘다. 이번에 건드리지 않는다 — **전략 노브가 됐으므로 이제 패널이 [0.2, 0.8] 안에서 조정할 수 있다.**
3. **`regime_snapshot`의 누락은 남는다.** 변동성 계산은 떼어냈지만 breadth·수급은 여전히 EOD 체인 의존이고 재시작 날 유실된다. **별건으로 기록** — 레짐 라벨의 breadth 성분에 같은 구멍이 있다.
4. **`M_evidence` 부재** — 왕복 11건으로 엣지가 미측정인 상태는 그대로다. 사용자 결정에 따라 변동성 방어만으로 간다.
5. **`^KS11`은 KOSPI다.** 보유 종목에 KOSDAQ이 섞이면 변동성 대리가 정확하지 않다. 현재 6종은 전부 KOSPI라 문제없으나, KOSDAQ 비중이 늘면 재검토가 필요하다.
