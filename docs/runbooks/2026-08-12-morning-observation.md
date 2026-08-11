# 2026-08-12(수) 아침 관측 런북

> 작성: 2026-08-11 17:20. **이 문서는 다음 세션이 이어받기 위한 것이다.**
> 전 세션의 감시(Monitor)·예약(cron)·컨텍스트는 세션 종료와 함께 사라졌다.

---

## 0-A. 🔴 현재 시스템은 **정지 상태**다 — 먼저 기동할 것

2026-08-11 17:28에 사용자가 PC 재부팅을 위해 백엔드·프론트엔드를 정상 종료했다
(`Application shutdown complete`, 미체결 주문 0건, 포트 해제 확인).

### 기동 명령

```bash
cd /Users/sunghoonk/Workspaces/JonberAITrading/backend && \
nohup /Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python run_dev.py \
  > ../debug/backend-$(date +%Y%m%d-%H%M).log 2>&1 &
```

⚠️ **conda 인터프리터를 절대 경로로 쓸 것.** `python run_dev.py`는 base 환경을 타서
`ModuleNotFoundError: uvicorn`으로 죽는다. 2026-08-11 장중에 이걸로 1분간 무방비가 됐다.

프론트엔드(필요시): `cd frontend && npm run dev` (포트 5173)

**기한: 2026-08-12 08:05 전.** 그때 레짐 판정 사이클이 돌고 09:00에 개장한다.
장이 닫혀 있는 동안은 포지션이 안 움직이므로 보호 공백은 생기지 않는다.

### 기동 후 확인

```bash
grep -aE "Restored .* positions|holiday_service_initialized|Traceback" debug/backend-*.log | tail -3
curl -s http://127.0.0.1:8000/api/trading/positions | python3 -m json.tool
```

| 확인 | 합격 |
|---|---|
| 복원 로그 | `[Coordinator] Restored 5 positions, ... daily_count=3` |
| 달력 | `holiday_service_initialized ... untrusted_years=[]` |
| 기동 오류 | `Traceback` 0건 |
| 손절가 5종 | 316140 31,154 · 004370 351,075 · 028670 5,520 · 030000 17,765 · 207940 1,404,840 |
| 모드 | `mode=active` |

### 🔴 반드시 확인할 것 — 028670 수량 불일치

**영속된 코디네이터 스냅샷은 028670이 3,115주인데, 브로커에는 3,470주가 있다.**
16:35 시간외 체결 355주(209+146)가 원장(`kr_stock_trades`)에는 들어갔으나
포지션 스냅샷에는 반영되지 않은 채 종료됐다.

리컨실러가 브로커 잔고와 대조해 메우게 되어 있다(30초 스케줄러 2틱마다 ≈60초).
**기동 후 5분쯤 지나 3,470주로 맞춰졌는지 확인할 것.**

```bash
curl -s http://127.0.0.1:8000/api/trading/positions | python3 -c "
import json,sys
r=json.load(sys.stdin); r=r.get('data') or r
if isinstance(r,dict): r=r.get('positions') or []
for p in r:
    if p.get('ticker')=='028670': print('028670:', p.get('quantity'), '주  (3470이면 정상, 3115면 리컨실러 미작동)')"
```

3,115주 그대로면 리컨실러가 안 도는 것이고 별도 조치가 필요하다.
방치하면 손절 발동 시 355주가 덜 팔린다.

---

## 0-B. 정지 직전 라이브 상태 (2026-08-11 17:28)

| 항목 | 값 |
|---|---|
| 프로세스 | PID 70185 (17:15 기동, **17:28 정상 종료**) · 포트 8000 |
| 코드 | `4107ec9` · 브랜치 `read-trading-prompt-dgm5U` |
| 계좌 | equity ₩499,000,954 · 현금 ₩427,855,838 · 주식 ₩71,145,116 (14.26%) |
| 모드 | `mode=active` |
| 포지션 | 5종 — 316140(549) · 004370(25) · 028670(3,115+) · 030000(739) · 207940(7) |
| 손절가 | 316140 31,154 · 004370 351,075 · 028670 5,520 · 030000 17,765 · 207940 1,404,840 |
| 노브 | 종목당 **0.03** · 슬롯 7 · `target_vol_pct` **22.0** · `vol_multiplier_min` **0.4** |
| 로그 | `debug/backend-lunar-20260811.log` |

⚠️ **PID는 재시작하면 바뀐다.** `ps -eo pid,etime,command | grep run_dev | grep -v grep`로 확인할 것.

---

## 🔴 관측 ① — 방어 매도 재제출 억제 (아직 시험되지 않음)

**배포**: 2026-08-10 (`9485c44`). **이틀째 미검증.**

2026-08-10 09:00에 089860 익절이 부분체결되자, 축소된 수량으로 재등록된 포지션이 즉시 재발동했는데 그 수량은 미체결 주문이 이미 예약하고 있어 `800033 매도가능수량 부족`으로 거부됐다. 세 관문(G1 보유 없음 · G2 미체결 SELL · G3 30초 쿨다운)을 넣었다.

### 신호 읽는 법 — 침묵을 성공으로 읽지 말 것

```bash
L=/Users/sunghoonk/Workspaces/JonberAITrading/debug/backend-lunar-20260811.log
for p in defensive_sell_suppressed defensive_sell_stale_pending_ignored 800033 \
         "Stop-loss triggered" "Take-profit triggered"; do
  echo "$p: $(grep -ac "$p" "$L")"
done
```

| 신호 | 읽는 법 |
|---|---|
| `defensive_sell_suppressed` (reason=`no_position`\|`pending_sell`\|`cooldown`) | ✅ **관문 발동 — 유일하게 "작동한다"를 증명하는 신호** |
| `defensive_sell_stale_pending_ignored` | 🔴 180초 창에 걸린 주문. **`ord_no` 기준 `sort -u`로 셀 것**(래치가 있어 에피소드당 1줄) |
| `800033` 재발 | 관문을 우회한 경로가 있다는 뜻. 발동 직전 로그와 함께 볼 것 |
| **손절/익절 발동 건수** | **분모.** 이게 0이면 관문 신호가 0인 것에 아무 의미가 없다 |

⚠️ **판정 규칙**: 관문 신호가 0줄이고 분모도 0이면 **"잘 되고 있다"가 아니라 "아직 시험되지 않았다"** 로 보고할 것. 관문 발동 조건(방어 매도 → 부분체결 → 재발동)이 안 오면 로그는 성공했을 때와 **글자 하나까지 같다.**

2026-08-11 실적: 손절 0 / 익절 0 / `800033` 0 → **정보 없음.**

### 알려진 잔여 위험

`defensive_sell_stale_pending_ignored`가 뜨면 그 종목은 최대 180초간 방어가 억제될 수 있다. 근본 해결은 `ka10075`를 `fill_tracker`에 배선해 `CANCELLED`를 실제로 대입하는 것(백로그).

---

## 🔴 관측 ② — 전략 패널의 노출도 역학 (내일 EOD가 첫 관측)

**배포**: 2026-08-11 (`3eafb8f`). **오늘 15:35 EOD는 재시작 전이라 블록을 못 봤다. 내일 15:35가 처음이다.**

### 왜 만들었나

목표 노출도 = `ramped(레짐앵커) × m_vol × m_drawdown`, `m_vol = min(1.0, max(vol_multiplier_min, target_vol_pct / 실현변동성))`.

KOSPI 실현변동성이 **101.7%**라 `m_vol`이 하한에 박혀 있다. 그래서:
- **레짐 라벨이 결과에 도달하지 못한다** — bull/neutral/bear 앵커가 전부 같은 목표를 낸다(램프가 먼저 묶어 앵커가 구속 조건이 안 됨)
- 패널이 8-10에 `target_vol_pct`를 18→22로 올렸으나 **효과 0**. 하한 탈출에 필요한 값은 **50.9**인데 그 노브의 상한은 **40** — 최대치를 불러도 아무 일도 안 일어난다

수렴점: `p* = min(ramp·m/(1−m), anchor·m)`

| `vol_multiplier_min` | 수렴 목표 |
|---|---|
| 0.4 (**현재**) | **10.0%** |
| 0.5 | 15.0% |
| 0.6 | 22.5% |
| 0.8 | 44%~60% |

### 무엇을 볼 것인가

```bash
sqlite3 -readonly "file:backend/data/storage.db?mode=ro" \
"SELECT trade_date, stance,
 json_extract(strategy_json,'\$.position_sizing.max_position_pct') per_pos,
 json_extract(strategy_json,'\$.position_sizing.target_vol_pct') tgt_vol,
 json_extract(strategy_json,'\$.position_sizing.vol_multiplier_min') vol_min
 FROM strategy_revisions ORDER BY trade_date DESC LIMIT 5;"
```

이력:

| 일자 | 스탠스 | 종목당 | tgt_vol | vol_min |
|---|---|---|---|---|
| 08-11 | **defensive** | 0.03 | 22.0 | **0.4** |
| 08-10 | aggressive | 0.0375 | 22.0 | 0.5 |
| 08-07 | neutral | 0.03 | — | — |

**08-11에 패널이 `vol_min`을 0.5→0.4로 스스로 낮췄다**(목표 15%→10%). 역학 블록 **없이** 내린 판단이다.

⚠️ **판정 기준**: 블록은 `by_vol_multiplier_min` 격자에 0.8(수렴 44%, 현재의 3배)을 **중립적으로** 싣는다. 내일 패널이 그걸 보고 어느 쪽으로 투표하는지가 **이 작업이 정보를 준 것인지 유혹을 준 것인지**를 가른다.

**급격한 이동은 구조적으로 불가능하다** — 노브 1회당 ±25%(0.4→0.5가 최대), 목표는 하루 ±15%p. 0.4→0.8까지 최소 3회 EOD, 노출도 10%→44%까지 **6거래일 이상**이고 중간에 되돌릴 창이 여러 번 있다.

블록이 프롬프트에 실제로 들어갔는지 확인하려면 `exposure_mechanics` 키가 패널 컨텍스트 직렬화에 있는지 보면 된다(`strategy_panel.build_strategy_context`).

---

## 08:05 레짐 사이클 정기 점검

```bash
DB="file:/Users/sunghoonk/Workspaces/JonberAITrading/backend/data/storage.db?mode=ro"
sqlite3 -readonly -header -column "$DB" \
 "SELECT trade_date, regime, confidence, degraded_json, ROUND(effective_target_pct,6) eff
  FROM regime_judgment ORDER BY created_at DESC LIMIT 2;"
sqlite3 -readonly "$DB" "SELECT COUNT(*)||'행, 최신 '||MAX(trade_date) FROM index_daily;"
```

| 확인 | 합격 |
|---|---|
| `regime_judgment` 1행 | **08:05** (08:00 아님 — 수집이 `judge_regime()` 안 인라인) |
| `degraded_json` | 비어 있음. `index_series_lagging`이 뜨면 지수 수집이 거래일 기준으로 뒤졌다는 뜻 |
| `index_daily` 최신 | **08-11**로 갱신돼야 함 |
| 종목당 상한 | **0.03 유지** (레짐 채널이 덮어쓰지 않는다는 실증, 3일째) |
| 슬롯 | 7 유지 |

⚠️ `index_daily`가 08-10을 여전히 못 받고 있으면 yfinance 지연이다. **7역일이 지나면 `stale` 판정**이 되는데, 이제는 `m_vol`이 하한(방어적)으로 떨어지므로 **노출도가 열리지 않는다**(2026-08-11 봉합).

---

## 달력 (2026-08-17 광복절 대체공휴일이 6일 뒤)

부팅 로그에 **`holiday_calendar_untrusted_years`가 있으면 실패**다. 2026-08-11 배포 후 `untrusted_years=[]`가 정상.

```bash
grep -a "holiday_service_initialized\|untrusted_years" debug/backend-*.log | tail -2
sqlite3 -readonly "file:backend/data/holidays.db?mode=ro" \
 "SELECT year, COUNT(*) FROM krx_holidays GROUP BY year;"   # 2026:20, 2027:22
```

**2026-08-17(월)이 휴장일로 인식되는지**가 그날 아침의 확인 사항이다.

---

## ⚠️ 이 리포의 함정 (전 세션에서 실제로 밟은 것)

1. **기동 명령에 conda 인터프리터를 절대 경로로 쓸 것.**
   `python run_dev.py`는 base 환경을 타서 `ModuleNotFoundError: uvicorn`으로 죽는다. 2026-08-11 장중에 이걸로 1분간 무방비가 됐다.
   ```
   nohup /Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python run_dev.py > ../debug/<log> 2>&1 &
   ```
2. **전체 테스트 스위트는 반드시 워크트리에서.** 메인 리포에서 돌리면 라이브 DB에 쓴다. 2026-08-11에 `holidays.db`에 실제로 썼다(`isolated_storage_service` 픽스처는 `storage_service`만 덮고 `KRXHolidayService`는 자기 기본 경로를 따로 갖는다).
3. **`kill`은 어시스턴트 권한 밖이다.** 사용자에게 `! kill -TERM <PID>` 실행을 요청할 것.
4. **`git stash` 금지** — 워크트리 여럿이 스택을 공유한다.
5. **장중 재시작 금지가 기본** — 손절이 이 프로세스에만 있고 브로커에 스탑이 없다.
6. pytest 출력의 ANSI 색상 때문에 `grep "^FAILED"`가 0건을 반환한다. `sed 's/\x1b\[[0-9;]*m//g'`.
7. **전체 스위트 기준선 = 21 failed** (`4107ec9` 기준 3,230 passed). 이 21건은 전부 base부터 있던 것이다.

---

## 백로그 (우선순위 순)

| | 항목 | 근거 |
|---|---|---|
| 🔴 | **`market_hours` 경로가 관측 밖** — 자율매매의 실제 관문 `is_krx_open_cached()` → `_is_krx_holiday()` → `is_holiday()`는 `get_trading_day_verdict`도 ERROR 래치도 안 거친다. **1초/30초 게이트는 여전히 완전히 조용하다.** 달력 데이터는 옳아졌지만 "틀렸을 때 알 수 있는가"는 아직 아니다 | 2026-08-11 리뷰 |
| 🔴 | **`ka10075` 배선** — `fill_tracker`가 `CANCELLED`를 실제로 대입하면 방어 매도의 180초 창이 사라진다 | 2026-08-10 리뷰 |
| 🔴 | **KRX API 복구** — `open.krx.co.kr` OTP가 HTML 반환, 직접 호출 404. `source=fallback_table`이 계속 찍히는 게 정상이 아니라는 신호 | 2026-08-11 |
| 🟡 | **`연말`(12/31) 고정** — KRX 폐장일은 연말 최종 영업일 기준이라 12/31이 주말인 해(2028·2033)에 실제 휴장일이 빠질 수 있음. **미검증** | 2026-08-11 리뷰 |
| 🟡 | 램프 재계산이 `strategy_panel`에 잔존 사본 — `TargetExposure`에 `ramped`를 노출시키는 것이 근본 해결 | 2026-08-11 리뷰 |
| 🟡 | `coordinator.py:2991` `equity_peak or 0.0`이 조회 실패(None)와 스냅샷 없음(0.0)을 뭉갬 → 섀도 경로의 `m_drawdown`이 조용히 1.0 | 2026-08-11 리뷰 |
| 🟡 | 체결 원장 중복 — 같은 체결이 31초 간격으로 두 번 기록 (사용자: 별건) | 2026-08-07 |
| 🟡 | `kr_realized_pnl` 1행 = 거래가 아니라 부분체결 슬라이스 | 2026-08-09 |

---

## 참고 — 오늘 확인된 정상 동작

- **시간외 단일가(15:40~18:00)에 체결이 난다.** 2026-08-11 16:35에 028670 355주 매수. `market_hours.py:261`에 정의된 정상 세션이다 — 이상 아님.
- 게이트 검사 8이 처음 물렸다(08-11, 439090 BUY 거부: `projected 15.87% > cap 15.10%`). 산수 검증 완료, 정상.
