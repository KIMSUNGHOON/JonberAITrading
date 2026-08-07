# 레짐 인지 노출도 제어 — 설계

- 날짜: 2026-08-07
- 범위: 포트폴리오 총 노출도를 매크로 레짐에 연동한다. 종목 선정 로직은 건드리지 않는다.
- 상태: 사용자 승인 완료(4개 결정), 구현 대기

## 1. 문제

계좌 ₩498.8M 중 주식이 **6.64%**(2026-08-07 09:35 실측)다. 90% 이상이 몇 주째
놀고 있다. 원인은 노브가 보수적이어서가 아니라 **현금 비중을 구속하는 기계가
아예 없기** 때문이다.

**`min_cash_ratio`는 죽은 노브다.** 전략 패널이 매일 밤 토론하고
(`strategy_panel.py:46`), `strategy_apply.py:53`이 `(0.05, 0.50)`으로 클램프하고,
`coordinator.py:1385`가 로그에 찍는다. 그런데 `_calculate_max_position_value`
(`portfolio_agent.py:323`)가 읽는 것은 `max_single_position_pct`, `risk_score`,
`r_cap`, 유동성 캡뿐이다. **현금 비율은 사이징 계산 어디에도 없다.** 이 리포의
반복 패턴 "만들어졌으나 닿지 않는다"의 다섯 번째 사례다.

실제 천장은 `max_open_positions × max_single_position_pct`다 — 오늘 기준
`7 × 3% = 21%`. 목표를 55%로 정해도 이 곱이 21%면 도달 자체가 불가능하다.

두 번째 문제는 **레짐 판정에 매크로가 하나도 없다**는 것이다. 현행
`compute_market_regime`(`regime.py:161`)의 입력은 셋뿐이다:

```
sentiment_score = 평균(
    breadth_ratio,     ← 스캐너 자신의 BUY/SELL 비율 (자기참조)
    지수 등락률,        ← 키움 모의투자 서버의 합성 시장
    수급 부호           ← 외국인/기관 순매수의 부호만, 크기 무시
)
```

환율·금리·유가·변동성·미국 지수 전부 미참조. 그리고 `KIWOOM_IS_MOCK=true`라
지수는 실제 시장이 아니다 — 07-28 −10.84%, 07-31 +17.91%로 움직이고 레벨과
등락률이 내부적으로 정확히 일치한다(5,593 × 1.1791 = 6,595). 파싱 오류가 아니라
합성 시장이다. 실현 연변동성 112.1%가 노출도 관측 유닛에서 이미
`index_vol_implausible`로 거부되고 있다.

**실측 증거**: 2026-08-07 간밤 EWY(한국 ETF, 미국 상장) **−2.97%**. 외국인이
값을 매기는 한국 시장이 3% 가까이 빠졌는데 시스템은 이 사실을 모른 채 당일
오전 두 종목을 익절했다.

## 2. 사용자 결정 (6건, 이 설계의 전제)

1. **판단 입력** — Finnhub 확장(미국 실물 매크로). 국내 지수·수급은 모의라 미사용
2. **결정 경계** — LLM은 라벨만 출력. 숫자는 고정 테이블이 정한다
3. **개방 속도** — 앵커 즉시 전면 적용. 증거 연동(`M_evidence`) 제거
4. **레짐 하향 시** — 강제 매도 없음. 초과 사실을 토론 패널 입력으로 주고 종목별
   판단은 에이전트에게 맡긴다
5. **종목당 상한** — 5% 고정
6. **일일 변화 한도** — ±15%p 적용

## 3. 만드는 것

```
Finnhub 실물 매크로  →  LLM 레짐 판정  →  고정 앵커 테이블  →  게이트 총량 검사
   (U1: 데이터)        (U2: 라벨 3개)     (U3: 산술)         (U4: fail-closed)
```

LLM은 사슬의 한 칸만 담당한다. **판단은 AI가, 숫자는 산술이, 집행은 게이트가.**

| 유닛 | 파일 | 책임 |
|---|---|---|
| U1 | `services/trading/macro_snapshot.py` (신규) | 매크로 8종 수집·적재 |
| U2 | `services/trading/regime_judge.py` (신규) | LLM 레짐 판정 + 영속 |
| U3 | `services/trading/exposure_target.py` (개편) | 레짐 → 목표 비중 (순수 계산) |
| U4 | `services/autonomy/gate.py` (수정) | 검사 8: 총 노출도 상한 |
| U5 | `services/agent_chat/` (수정) | 초과 사실을 토론 프롬프트에 주입 |
| U6 | `services/telegram/briefing.py` (수정) | `/brief`·`/exposure`에 레짐 노출 |

### U1 · 매크로 수집

`us_market_data.py`의 `_finnhub_quote` 호출부와 스케줄러 패턴
(`start_us_signal_scheduler`)을 재사용한다. 전 티커 실시세 수신을 2026-08-07에
확인했다.

| 티커 | 읽는 것 | 검증값(08-07) |
|---|---|---|
| `EWY` | 외국인이 값을 매기는 한국 시장 | 164.12 / −2.97% |
| `SPY` | 미국 위험선호 | 768.56 / −0.16% |
| `QQQ` | 성장주 선호 | 714.65 / −0.37% |
| `VIXY` | 변동성 | 19.53 / −1.21% |
| `TLT` | 장기금리 | 82.52 / −0.58% |
| `UUP` | 달러 (신흥국 자금 흐름) | 28.19 / +0.36% |
| `USO` | 유가 | 118.87 / +3.47% |
| `GLD` | 안전자산 | 389.67 / +0.01% |

매일 **08:00 KST** 수집(간밤 미국장 마감 후). `macro_snapshot` 테이블 1일 1행.
이력이 쌓이는 것 자체가 추세 입력이다.

```sql
CREATE TABLE IF NOT EXISTS macro_snapshot (
    id           TEXT PRIMARY KEY,
    trade_date   TEXT NOT NULL UNIQUE,
    quotes_json  TEXT NOT NULL,   -- {ticker: {c, dp}}
    missing_json TEXT,            -- 수신 실패 티커 목록 (없으면 NULL)
    created_at   TEXT NOT NULL
);
```

**부분 실패는 허용한다** — 받은 것만 저장하고 못 받은 티커를 `missing_json`에
기록한다. 조용히 0을 채우지 않는다(노출도 관측 유닛에서 세운 규칙과 동일).
8종 전부 실패하면 행을 만들지 않는다.

**스케줄 배선**: `app/main.py`의 기존 `AsyncIOScheduler` + `CronTrigger` 패턴
(08:30 `morning_brief`가 쓰는 것)을 따른다. 수집(08:00) → 판정(08:05) →
브리핑(08:30) 순서다.

⚠️ **휴장일 스킵에서 이미 한 번 밟은 함정** — 2026-08-06 브리핑 구현에서
`is_business_day`(존재하지 않는 이름)를 부르고 `get_holiday_service`를 `await`
없이 써서, 넓은 `except`가 둘 다 삼키는 바람에 **휴장일 스킵이 한 번도 작동하지
않았다**. 실제 이름은 `is_trading_day`이고 `get_holiday_service`는 **async**다.
브리핑에 넣은 계약 카나리 테스트와 같은 것을 이 스케줄에도 둔다.

### U2 · AI 레짐 판정

입력: 오늘 스냅샷 + 최근 **10거래일** 이력. 출력:

```json
{"regime": "bull|neutral|bear", "confidence": 0.0~1.0,
 "rationale": "...", "key_drivers": ["EWY -2.97%", "..."]}
```

기존 LLM 라우터(`agents/llm_provider.py`)를 쓴다. 판정 전문을 저장한다.

```sql
CREATE TABLE IF NOT EXISTS regime_judgment (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL UNIQUE,
    regime               TEXT NOT NULL,      -- bull|neutral|bear
    confidence           REAL,
    rationale            TEXT,
    key_drivers_json     TEXT,
    anchor_target_pct    REAL NOT NULL,      -- 앵커 테이블 원값
    effective_target_pct REAL NOT NULL,      -- ±15%p 한도 적용 후
    prev_effective_pct   REAL,               -- 한도 계산에 쓴 직전값
    degraded_json        TEXT,               -- 저하 사유 목록
    macro_snapshot_id    TEXT,
    created_at           TEXT NOT NULL
);
```

**실패 처리 — 방향이 중요하다.** 조회 실패가 노출도를 위로 열면 안 된다
(2026-08-06 리뷰가 잡은 "폴백이 전부 한 방향으로 겹친다"와 같은 함정).

| 상황 | 처리 |
|---|---|
| LLM 호출 실패·타임아웃 | **직전 유효 판정 유지**, `degraded=llm_unavailable` |
| 응답 파싱 실패 / 라벨이 3개 밖 | 직전 유지, `degraded=regime_unparseable` |
| 직전 판정도 없음 (최초·전면 장애) | **검사 8 스킵** — 기존 천장(슬롯 × 종목당)이 그대로 남는다. 임의의 숫자를 만들지 않는다 |
| 판정이 **5역일** 초과로 오래됨 | 없는 것으로 취급(검사 8 스킵) + Telegram 경보 |

`neutral`을 폴백으로 쓰지 않는다 — 중간값 65%는 "판정 못 함"의 결과로는
공격적이다. 판정이 없으면 새 밸브를 아예 열지 않고 오늘의 동작을 유지한다.

### U3 · 레짐 → 목표 (순수 계산)

```python
REGIME_ANCHORS = {"bull": 0.80, "neutral": 0.65, "bear": 0.55}
DAILY_TARGET_DELTA_MAX = 0.15      # ±15%p / 판정 1회
REGIME_PER_POSITION_PCT = 0.05     # 종목당 상한 (고정)
JUDGMENT_MAX_AGE_DAYS = 5
```

```
anchor    = REGIME_ANCHORS[regime]
ramped    = clamp(anchor,
                  prev_effective - 0.15,
                  prev_effective + 0.15)
effective = clamp(ramped × M_vol × M_drawdown, 0.02, 0.80)
```

**한도는 앵커에만 적용하고 배수는 그 뒤에 곱한다.** 방어(낙폭·변동성)는 일일
한도보다 빠르게 줄일 수 있어야 하기 때문이다. 다음 판정의 `prev_effective`는
배수까지 적용된 `effective`를 잇는다 — 회복도 +15%p/일로 제한된다.

- **`M_evidence` 제거** — 왕복 8건은 *모의 시장에서* 쌓은 것이다. 시뮬레이터
  숙련도를 실력으로 착각하는 안전장치는 어느 방향으로도 작동하지 않는다.
- **`M_drawdown` 유지** — 고점 대비 실제 낙폭에 반응하는 데이터 기반 축소다.
  기존 계수(`DRAWDOWN_SLOPE=3.0`, `DRAWDOWN_FLOOR=0.3`)와 기존 함수를 그대로 쓴다.
- **`M_vol` 입력 교체** — 모의 KOSPI 대신 **SPY 일간 등락률**(`macro_snapshot`에
  누적된 `dp` 값)을 쓴다. 계산식·상수·위생 게이트는 기존 것을 **한 글자도
  바꾸지 않는다**: `annualized_vol()`(20일 창, 최소 5표본, ×√250) →
  `TARGET_VOL_PCT(18.0) / vol_ann`을 `[0.5, 1.5]`로 클램프, 게이트
  `[5.0, 60.0]` 밖이면 `1.0` + `degraded="index_vol_implausible"` + 원값 보존.
  **배포 직후에는 이력이 0행이라** 표본 부족으로 `m_vol=1.0` +
  `degraded="index_vol_insufficient"`이고, 스냅샷이 5행 쌓이는 5거래일째부터
  실제로 작동한다. 이건 결함이 아니라 예상 동작이며 판정 기준에 포함한다.

**`prev_effective` 시드**: 최초 1회는 그 시점의 실제 주식 비중을 쓴다.
이후에는 저장된 `effective_target_pct`를 잇는다 — 실제 비중이 아니라 **직전
목표**를 잇는 이유는, 익절로 실제 비중이 떨어졌다고 목표까지 따라 내려가면
안 되기 때문이다.

한도는 **판정 1회당** 적용된다(판정은 하루 1회). 며칠 중단됐다 재개해도 재개
후 첫 판정에 한 번만 적용된다.

**램프 예시** (오늘 8.55%에서 시작, bear 판정 지속):
```
8.55% → 23.55% → 38.55% → 53.55% → 55.00%   (4거래일)
```

### U4 · 목표 → 밸브

**게이트 검사 8 신설** (`services/autonomy/gate.py`). 기존 검사 7 **직후**,
**`if action in POSITION_INCREASING_ACTIONS:` 분기 안에** 둔다
(`POSITION_INCREASING_ACTIONS = {"BUY", "ADD"}`, `gate.py:54`). 검사 4~7이 이미 그
분기 안에 있으므로 SELL·REDUCE는 **구조적으로 면제**된다 — 손절 경로에 새 조건이
하나도 추가되지 않는다.

`quantity`·`entry_price`·`account_equity_provider`는 검사 7이 이미 받고 있다.
새로 필요한 provider는 둘뿐이다: `exposure_target_provider`,
`stock_value_provider`.

```python
# 8. 목표 노출도 상한 (검사 7 직후, 같은 분기 안)
try:
    target = await (exposure_target_provider or _default_exposure_target_provider)(market)
except Exception as e:
    return _deny("exposure_target", f"target unavailable: {e}")   # 오류 → fail-closed

if target is not None:            # None = 판정 부재/만료 → 검사 스킵(기존 천장 유지)
    try:
        stock_value = await (stock_value_provider or _default_stock_value_provider)(market)
    except Exception as e:
        return _deny("exposure_target", f"stock value unavailable: {e}")
    cap = float(target) * float(equity)          # target은 분율(0.55), equity는 검사 7의 것 재사용
    projected = float(stock_value) + notional    # notional = quantity × entry_price (검사 7 계산값)
    if projected > cap:
        return _deny(
            "exposure_target",
            f"projected ₩{projected:,.0f} > target cap ₩{cap:,.0f} "
            f"({target * 100:.1f}% of ₩{equity:,.0f})",
        )
```

⚠️ **단위**: `target`은 **분율**(0.55)이고 검사 7의 `max_trade_notional_pct`는
**퍼센트**(30.0)다. `/100.0`을 복사해 오면 목표가 100배 작아져 모든 매수가
막힌다.

**오류와 부재를 절대 합치지 않는다.** 조회 예외는 `deny`, 판정 부재(`None`)는
스킵이다. 2026-08-06에 `/exposure`가 이 둘을 storage 계층에서 합쳐 "행 없음"을
"조회 실패"로 보고한 사고가 있었다. `_default_exposure_target_provider`는 행이
없으면 `None`을 돌려주고, DB 오류에서는 **예외를 올린다**.

**슬롯 수 — 올리기만 한다.**

```python
max_open_positions = max(현재값, ceil(effective_target / 0.05))
max_single_position_pct = 0.05
```

목표가 내려가도 슬롯을 줄이지 않는다. 줄이면 **같은 금액을 더 적은 종목에
담게 되어 집중도가 오른다** — 축소하려는 의도와 정반대다. 총량 축소는 전적으로
검사 8이 담당한다.

| 레짐 | 목표 | 필요 슬롯 |
|---|---|---|
| bull | 80% | 16 |
| neutral | 65% | 13 |
| bear | 55% | 11 |

리스크 파라미터 쓰기는 `PUT /risk-params`가 쓰는 것과 같은 **`_persist_fields`
RMW 경로**를 탄다 — 이 리포에는 스냅샷 통째 쓰기가 실 포지션 손절가를 덮어쓴
전력이 있다(2026-07-29).

**`GATE_PROTECTED_FIELDS`는 유지한다.** 전략 패널의 자유 서술값은 계속 차단된다.
레짐 채널은 값이 3개뿐인 룩업이라 드리프트가 구조적으로 불가능하므로, 별도의
경계 명시 경로로 `max_open_positions`를 쓴다. 봉인의 취지(LLM 자유 드리프트
차단)는 훼손되지 않는다. `strategy_knob_discarded` 로그는 그대로 남는다.

### U5 · 초과분은 강제하지 않는다

목표가 내려가 실제가 초과 상태가 되면:

- **신규 진입·ADD** — 검사 8이 산술로 막는다 (즉시, 결정론적)
- **기존 포지션** — 팔지 않는다. 다음 문자열을 49분 재평가 토론 프롬프트에
  주입한다:

  ```
  포트폴리오 상태: 목표 주식비중 55.0% / 현재 71.2% / 초과 16.2%p
  (레짐 bear — EWY -2.97%, VIXY +12% 등)
  ```

  어느 종목을 줄일지는 종목별 데이터를 보고 4-에이전트 패널이 판단한다.
  새 청산 엔진을 만들지 않는다.

주입 지점은 프롬프트 구성부 한 곳이며, 투표 파싱·합의 문턱·실행 경로는
한 글자도 바꾸지 않는다.

### U6 · 관측

- `/brief` (08:30 자동 발송) — 오늘 레짐, 신뢰도, 핵심 근거 3줄, 목표/실제 비중
- `/exposure` — 목표·실제·앵커·한도 적용 여부·`degraded`·판정 시각
- `exposure_shadow` 행에 `regime_source`(`llm` / `carried_over` / `absent`) 추가

## 4. 킬스위치

`REGIME_EXPOSURE_ENABLED` (기본 `false`). `false`면 검사 8을 건너뛰고 리스크
파라미터를 쓰지 않는다 — **현행 동작과 바이트 단위로 동일**하다. 배포는 `false`로
나가고 `.env`에서 켠다. 문제가 생기면 재배포 없이 끈다.

## 5. 테스트

**순수 함수(대부분)** — 앵커 테이블 3라벨 / ±15%p 한도(상·하한 양방향, 시드
최초 1회, 배수는 한도 뒤에 곱해지는지) / `M_drawdown` 결합 / `M_vol`이 SPY
등락률을 입력으로 받되 계산식·상수·위생 게이트가 기존과 동일한지(표본 부족·
게이트 밖·정상 3갈래) / 판정 만료 판정 / 슬롯 = `ceil(목표/5%)` 및 "올리기만"
불변식(목표가 내려가도 슬롯이 안 줄어드는지).

**게이트 검사 8** — 통과 / 거절 / 판정 부재 시 스킵 / 조회 오류 시 deny의 네
갈래. **SELL·REDUCE가 검사 8을 통과하는지 별도 테스트**(손절 면역).

**LLM 판정** — 정상 / 라벨이 3개 밖 / JSON 깨짐 / 타임아웃 각각에 대해 직전
판정이 유지되는지. 목(mock)이 아니라 실제 폴백 경로를 검증한다.

**킬스위치** — `false`일 때 게이트 반환값과 리스크 파라미터가 불변인지.

**회귀** — 기존 게이트 7검사의 동작과 순서 불변. `GATE_PROTECTED_FIELDS` 봉인
테스트 불변.

⚠️ 각 테스트마다 **"이 속성이 위반되면 이 테스트가 실제로 실패하는가"**를 묻는다.
2026-08-06에 `MagicMock`을 `await`할 때 나는 `TypeError`를 blanket `except`가
삼켜 단언이 여전히 참이 되는 공허한 테스트가 3라운드 연속 나왔다.

전체 스위트는 워크트리에서 `--import-mode=importlib`로 돌린다(라이브
`storage.db` 오염 전력).

## 6. 성공 판정 (배포 후 익일 아침)

| 확인 | 정상 | 실패 신호 |
|---|---|---|
| `macro_snapshot` | 08:00에 1행, `quotes_json` 8종 | **0행 = 스케줄러 미등록** |
| `regime_judgment` | 08:00에 1행 | **0행 = 배선 실패** |
| `rationale` | 실제 매크로 수치를 인용 | 일반론만 = 입력이 프롬프트에 안 닿음 |
| `effective_target_pct` | 직전 대비 ±15%p 이내 | 초과 = 한도 미적용 |
| 게이트 로그 | `exposure_target` 검사가 등장 | 미등장 = 검사 8 미배선 |
| `degraded` | `index_vol_insufficient` **있는 게 정상** (5거래일까지) | 없으면 `M_vol`이 어디서 표본을 얻었는지 의심 |
| `max_open_positions` | `ceil(목표/5%)`로 상향 | 불변 = 슬롯 배선 실패 |
| `/brief` | 레짐과 근거가 표시됨 | — |

**첫날 예상값** (오늘 8.55%에서 시드, bear 판정 가정): `anchor=0.55` →
`ramped=0.2355` → `m_vol=1.0`(표본부족) × `m_drawdown` → `effective≈0.235`,
`max_open_positions = ceil(0.235/0.05) = 5`. ⚠️ 현재 슬롯이 7이므로 **"올리기만"
규칙에 따라 7이 유지된다** — 5로 내려가면 규칙이 안 걸린 것이다.

## 7. 남는 위험 (설계로 못 없앰, 명시만)

1. **후보 공급이 실질 천장** — 워치 12종 × 5% = 60%. 강세 80%는 발굴 증설
   없이는 도달 불가. 목표에 못 닿으면 정직하게 현금으로 남는다(강제 충전 없음).
2. **토론 처리량** — 16포지션을 49분마다 재평가하면 LLM 호출이 현재의 3배가
   된다. `max_concurrent_discussions` 기본값은 3이다. 2026-08-03에 LLM 한도
   소진 사고가 있었다. **슬롯이 11을 넘기 전에 재평가 예산을 재산정해야 한다.**
3. **EWY는 대리일 뿐** — 국내 수급·정책·환율 고유 요인은 보이지 않는다. 국내
   데이터가 모의인 한 이 갭은 못 메운다.
4. **성과 기록이 모의 시장에 대한 것** — 이 설계는 그 문제를 풀지 않는다.
   `M_evidence`를 제거함으로써 *모의 성과를 근거로 삼는 것을 그만둔다*는
   입장을 취할 뿐이다.
5. **`max_daily_trades` 10건** — 목표가 55%로 오르면 하루 진입 수요가 10건을
   넘길 수 있다. 상한에 걸리면 램프가 늦어진다(위험은 아니나 관측 필요).
