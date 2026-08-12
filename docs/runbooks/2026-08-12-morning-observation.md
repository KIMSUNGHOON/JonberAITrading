# 2026-08-12(수) 아침 관측 런북

> 작성: 2026-08-11 17:20 · **갱신: 2026-08-12 13:00**.
> **이 문서는 다음 세션이 이어받기 위한 것이다.**
> 전 세션의 감시(Monitor)·예약(cron)·컨텍스트는 세션 종료와 함께 사라졌다.
>
> **관측 3건**: ① 방어 매도 재제출 억제(**미검증 5일째**) · ② 패널 노출도 역학(**08-12 16:35이 첫 EOD** — 15:35이 아니다, §EOD 타이밍 참조) · ③ `index_daily` 지연(**규명·배포 완료**, 08-13 09:35 첫 판정).
>
> ### 2026-08-12에 일어난 일
>
> 🔴 **11:04 — agent-chat 엔진이 3거래일간 꺼져 있던 것을 발견·복구.**
> 원인은 08-11 테스트 스위트의 라이브 DB 오염(**함정 2번**). 개장 후 2시간 4분간 토론 0건이었고
> 손절만 돌고 있었다. 재기동 체크리스트에 agent-chat이 없던 것이 화근 — **§0-A에 추가했다.**
> 이후 `max_concurrent`를 3→**10**으로 올리고 영속화(재기동 후 복원 확인).
>
> **배포 2건** (둘 다 라이브·TDD·회귀 0):
>
> | 커밋 | 내용 | 상태 |
> |---|---|---|
> | `f5af713` (12:21) | 지연 경고 래치 + 저하 태그 사람말 번역 | ✅ **실증 완료** — 42건/4h → 1건/17분 |
> | `259ab7a` (12:46) | 09:30 재수집 + 당일 진행 봉 제외 | ✅ 스케줄러 등록 확인 · **첫 실행 08-13 09:30** |
> | `948e9ea` | 라이브 DB 가드 (autouse 리다이렉트) | ✅ 회귀 0 · 위반 테스트 **16개** 적발 |
> | `04fec8b`+`32a6db3` | Telegram·Kiwoom 엔드포인트 가드 | ✅ 회귀 0 · Kiwoom 접속 **39건** 차단 |
>
> ⭐ 가드 작업이 두 가지를 드러냈다: **워크트리 규칙은 Kiwoom을 막지 못했고**(URL이 코드에
> 하드코딩), **teardown보다 오래 사는 폴링 태스크**는 function 스코프 가드를 우회한다.
>
> **예약 알람**(세션 전용 — 세션이 끊기면 사라진다. 그때는 이 문서가 대신한다):
> `c1a0ff15` 08-12 **16:40** EOD · `ad8f7ac1` 08-13 08:10 개장 전 · `a94f4424` 08-13 09:35 재수집 판정
> (`6159351a` 15:40 EOD는 1시간 일러 헛돌았다 — 아래 §EOD 타이밍)

---

## 0-A. ✅ 시스템은 **기동되어 있다** (2026-08-12 12:46 재기동 완료)

이 절은 *재시작이 필요할 때*를 위한 참조다. 08-12에 배포로 두 번 재시작했다
(12:21 `f5af713`, 12:46 `259ab7a`). **장중 재시작 공백은 각각 5초·11초**였다.

| 확인 | 2026-08-12 12:46 실측 |
|---|---|
| 백엔드 | **PID 28626** · 포트 8000 · `259ab7a` · 로그 `debug/backend-20260812-1246.log` |
| 프론트엔드 | 포트 5173 · HTTP 200 · 프록시 → 127.0.0.1:8000 (PID 2977, 08-11 17:49부터 무중단) |
| 복원 | `Restored 5 positions, 7 queued trades, 48 watched stocks, daily_count=0` |
| 손절가 5종 | 전부 아래 §0-B 값과 일치 |
| 달력 | `untrusted_years=[]` · 08-15 광복절 + **08-17 대체공휴일** 둘 다 등록 |
| 노브 | 종목당 0.03 · `max_open_positions` **7** · `target_vol_pct` 22.0 · `vol_multiplier_min` 0.4 |
| 모드 | `mode=active` · Traceback 0건 |
| **agent-chat** | ✅ `agent_chat=True trading=True` · `max_concurrent=10` 복원 |
| **신규 스케줄러** | ✅ `index_refresh_scheduler_started hour=9 minute=30` → `index_refresh_scheduler_wired` |
| LLM 라우터 | openrouter ✅ / claude_cli ✅ / codex_cli ❌ |

⚠️ 리스닝까지 **5~40초**. 그 전의 `curl`은 `HTTP 000`을 돌려준다 — 죽은 것이 아니다.
`Uvicorn running`을 로그에서 확인할 것(08-11엔 37초, 08-12엔 5초·11초 걸렸다).

### 🔴 재기동 후 반드시 확인 — 엔진은 **둘**이다

`mode=active`는 **trading 엔진**만 말한다. 자율매매의 토론·의결은 **agent-chat**이라는
별개 엔진이고, 부팅 자동 재개도 **따로** 판정된다. 한쪽만 보면 절반을 놓친다.

```bash
grep -a "boot_auto_resume_complete" debug/backend-*.log | tail -1
#   합격: agent_chat=True trading=True   ← 둘 다 True여야 한다
curl -s http://127.0.0.1:8000/api/agent-chat/status | python3 -m json.tool
#   합격: "is_running": true · "check_interval_minutes": 1   (5면 테스트 오염, 함정 2번)
```

`agent_chat=False`면 **body 없이** 시작한다(body를 주면 현재 값을 덮어쓴다):

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent-chat/start -H "Content-Type: application/json"
```

⚠️ **꺼져 있어도 손절은 돈다** — RiskMonitor는 trading 엔진 쪽이다. 그래서 증상이
"주문이 안 나간다"뿐이고, 포지션을 보고 있으면 정상으로 보인다. 2026-08-12에 개장 후
**2시간 4분** 동안 토론 0건이었는데 손익 화면은 멀쩡했다.

### 기동 명령 (재시작이 필요할 때)

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

### ✅ 028670 수량 — **불일치는 없었다 (이 문서의 최초 서술이 오경보였다)**

이 문서는 처음에 "스냅샷 3,115 vs **브로커 3,470**"이라고 적었다. **틀렸다.**
2026-08-11 17:55에 브로커를 직접 조회해 확인한 결과:

| 출처 | 수량 |
|---|---|
| 브로커 실조회 (`/api/kr_stocks/positions` → `get_account_balance()`, kt00004) | **3,115** |
| 원장 `kr_stock_trades` 체결 누적 (buy 18행, sell 0) | **3,115** |
| 코디네이터 스냅샷 | **3,115** |

**세 숫자가 전부 같다.** 3,470은 3,115 **+** 355를 더해 만든 숫자였는데, 그 355주는
**이미 3,115 안에 포함**돼 있었다 — 즉 이중 계상이다.

원장이 16:35 체결의 정체를 설명한다:

| 시각 | 주문 | 주문량 | 체결 |
|---|---|---|---|
| 09:07:47 | `0018558` | 207 | **61** (부분) |
| 16:35:05 | `0018558` | — | **146** (잔량 — 61+146=207 완결) |
| 16:35:05 | `0018653` | 209 | 209 (별개 신규 주문) |

146은 오전 주문의 잔량 체결이고 209는 별개 주문이다. 둘 다 정상이며 누적에 이미 반영돼 있다.

⚠️ **따라서 리컨실러가 조용한 것은 정상이다** — 교정할 드리프트가 없다.
`_queue_scheduler_loop`(coordinator.py:4845)는 장중 게이트가 없어 마감 후에도 30초마다 돌고
2틱마다 `reconcile()`을 부르지만, `_fix_positions`는 `quantity != broker_qty`일 때만 로그를 남긴다.

**교훈: 원장 합을 브로커 잔고에 "더하지" 말 것.** 원장 누적은 이미 잔고 그 자체다.
불일치를 주장하려면 브로커를 **직접 조회**해 대조해야 한다 — 위 표의 세 줄이 그 방법이다.

---

## 0-B. 라이브 상태 (2026-08-12 12:46 재기동 후)

| 항목 | 값 |
|---|---|
| 프로세스 | **PID 28626** (12:46 기동) · 포트 8000 |
| 코드 | **`259ab7a`** · 브랜치 `read-trading-prompt-dgm5U` (origin 동기화 완료) |
| 계좌 | 08-12 12:44 기준 주식 ₩70,547,159 · 손절 최소여유 5.3% |
| 모드 | `mode=active` · `daily_trades` **0**/10 (일일 리셋 정상 작동) |
| 포지션 | 5종 — 316140(549) · 004370(25) · **028670(3,115 — 확정)** · 030000(739) · 207940(7) |
| 손절가 | 316140 31,154 · 004370 351,075 · 028670 5,520 · 030000 17,765 · 207940 1,404,840 |
| 노브 | 종목당 **0.03** · 슬롯 7 · `target_vol_pct` **22.0** · `vol_multiplier_min` **0.4** |
| agent-chat | `running=true` · `check_interval=1` · **`max_concurrent=10`** (전부 영속됨) |
| 오늘 목표 | `effective_target_pct` **11.99%** (bull, 신뢰 72%) < 실제 약 14.3% → **초과 상태** |
| 로그 | `debug/backend-20260812-1246.log` |

⚠️ **PID는 재시작하면 바뀐다.** `ps -eo pid,etime,command | grep run_dev | grep -v grep`로 확인할 것.

### ⭐ 레짐 라벨이 결과에 도달하지 못한다 — 3일치로 확증 (2026-08-12)

| 일자 | 레짐 | anchor | **eff** |
|---|---|---|---|
| 08-10 | bull | 0.80 | 15.38% |
| 08-11 | bear | 0.55 | 15.10% |
| 08-12 | **bull** | 0.80 | **11.99%** |

bull → bear → bull인데 목표는 **단조 감소**한다. 오늘은 bull인데 어제 bear보다 목표가 더 낮다.
라벨이 아니라 `vol_multiplier_min`(08-11에 패널이 0.5→0.4로 낮춤, 수렴 10%)이 지배하고 있다.
설계 문서가 예고한 "램프가 먼저 묶어 앵커가 구속 조건이 안 된다"가 관측으로 확인된 것이다.

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

**배포**: 2026-08-11 (`3eafb8f`). **08-11 EOD는 재시작 전이라 블록을 못 봤다. 08-12가 처음이다.**

### ⏰ EOD 타이밍 — 15:35이 아니라 **16:35**다 (2026-08-12 정정)

이 문서는 "15:35 EOD"라고 적어 왔다. **틀렸다.** `strategy_revisions`의 생성 시각이
6일 내내 같다:

| 일자 | `created_at` (UTC) | KST |
|---|---|---|
| 08-11 | 07:35:05 | **16:35** |
| 08-10 | 07:35:19 | 16:35 |
| 08-07 | 07:36:12 | 16:36 |
| 08-05 · 08-04 · 08-03 | 07:35:57 · 07:41:33 · 07:37:50 | 16:35~16:41 |

**구조**: EOD는 스케줄러 잡이 아니다. `coordinator.py:4404` 부근의
`elif not is_open and self._market_was_open:` — **`open→closed` 엣지**가 트리거고,
거기서 `run_eod_review` → `run_strategy_consensus` → 발굴 파이프라인이 이어진다.
LLM을 여러 번 타서 **약 65분** 걸린다. 15:30 마감 → 16:35 완료.

⚠️ **15:40에 조회하면 어제 행이 최신으로 보인다.** 08-12에 그 함정을 실제로 밟아
알람이 헛돌았다. 마감 직후의 "행이 없다"는 실패가 아니라 **아직 도는 중**이다.
판정은 **16:40 이후**에 하고, 그때도 없으면 `[error`·`eod`·`strategy_consensus`
로그를 볼 것.

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

## ✅ 관측 ③ — `index_daily` 지연: 원인 규명·배포 완료 (2026-08-12)

**"자동 복구될 것"이라던 08-11의 예상은 절반만 맞았다.** 08-12 08:05 수집에서 08-10은
들어왔지만 **08-11이 없었다.** 지연이 해소된 게 아니라 **한 칸씩 밀려가는 정상 상태**였다.

### 확정된 원인 — 08:05가 Yahoo 반영보다 이르다

| 시각 (KST) | `^KS11` 최신 봉 |
|---|---|
| 08-12 **08:12** 조회 | 08-10 (08-11 **없음**) |
| 08-12 **12:28** 조회 | **08-11 도착** (6,345.53) |

**08-11 종가 6,345.53은 08-11 17:55에 본 값과 완전히 같다.** 즉 그것은 확정치였다 —
KOSPI는 15:30 마감이라 그 시각엔 이미 확정이다.

⭐ **08-11에 내가 "그건 잠정치였다"고 판단한 것은 틀렸다.** 그 오판으로 "마감 후 수집은
잠정치를 굳힌다"며 수정을 보류했었다. 잠정인 것은 전일 종가가 아니라 **당일 봉**이다.

### 배포 (`259ab7a`, 2026-08-12 12:46 라이브)

**① 평일 09:30 재수집** — `start_index_refresh_scheduler`(`index_series.py`),
`app/main.py`에서 배선(`index_refresh_scheduler_wired`). 레짐 스케줄러와 **독립**이다.

**② 당일 진행 봉 제외** — `refresh_index_daily`가 오늘 날짜 행을 저장하지 않는다.
🔴 **이 둘은 분리 불가다.** 장중 재수집은 확정 전 봉을 끌고 온다(실측: 12:28 6,629.37 →
12:33 6,626.09, 움직이는 중). 스케줄러만 켜면 진행 봉이 확정 종가로 굳는다.
08:05 수집은 장 시작 전이라 이 위험이 없었다 — 장중 재수집이 새로 만든 것이다.

### 🔴 첫 실행 판정 — 2026-08-13 09:35 (알람 `a94f4424`)

```bash
sqlite3 -readonly -header -column "file:backend/data/storage.db?mode=ro" \
 "SELECT trade_date, ROUND(close,2) close, substr(created_at,1,19) written
  FROM index_daily ORDER BY trade_date DESC LIMIT 4;"
L=$(ls -t debug/backend-2026*.log | head -1)
grep -a "index_series_refreshed\|index_series_intraday_bar_skipped" "$L" | tail -3
```

| 확인 | 합격 | 불합격이면 |
|---|---|---|
| 최신 `trade_date` | **전일** (09:30 재수집이 메움) | 그대로면 09:30에도 Yahoo가 안 낸 것 — 실측상 12:28엔 있었으니 `hour` 상향 검토 |
| 🔴 **오늘 날짜 행** | **없어야 한다** | 있으면 진행 봉이 굳은 것 — 즉시 보고 + 해당 행 삭제 검토 |
| `index_series_refreshed` | 09:30~09:31에 1건 | 없으면 스케줄러 미작동 |

⚠️ **`degraded_json`의 `index_series_lagging`은 08-13에도 남아 있는 게 정상**이다 —
그 값은 **08:05 판정 시점**의 기록이고 그때는 아직 뒤져 있다. 사라지는 것은 **08-14 판정부터**다.
*"오늘 없으면 성공"으로 읽지 말 것.*

### 곁가지 — 경고 래치 (`f5af713`, 12:21 라이브)

`evaluate_series_lag`는 장중 감시 루프에서도 호출되는데 `logger.warning`에 래치가 없어
같은 줄이 5분마다 찍혔다. `(latest, expected)` 키로 래치했다. **지연이 깊어지면 다시 말한다.**

**실증 완료**: 배포 전 **42건/4시간** → 배포 후 **1건/17분**.
🔴 분모도 확인했다 — 같은 창에 로그가 매분 찍혀 루프는 살아 있었다(침묵의 원인이 래치임을 확증).

⚠️ 위험 방향은 아니다 — `stale` 판정이 나도 `m_vol`이 하한(방어적)으로 떨어져 노출도가
**열리지 않는다**(2026-08-11 봉합).

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
| `index_daily` 최신 | **08-11** (현재 08-07 — 08-10·08-11 두 날이 함께 채워져야 한다. **관측 ③ 참조**) |
| 종목당 상한 | **0.03 유지** (레짐 채널이 덮어쓰지 않는다는 실증, 3일째) |
| 슬롯 | 7 유지 (`max_open_positions`, 17:49 실측 확인) |

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
2. 🔴 **전체 테스트 스위트는 반드시 워크트리에서.** 메인 리포에서 돌리면 라이브 DB에 쓴다.
   2026-08-11 13:2x~13:3x에 **두 DB가 동시에 오염됐다**:
   - `holidays.db` — 즉시 발견 (데이터가 우연히 정확해 피해 없음)
   - **`storage.db`의 `app_settings` — 3거래일 뒤에야 발견** 🔴

   **`agent_chat:coordinator_state`가 `{"running": false, "check_interval": 5, ...}`로 덮였다.**
   `check_interval: 5`는 프로덕션 기본값(**1**, `coordinator.py:528`)이 아니라 **테스트 픽스처 값**이다
   (`test_coordinator.py:39`, `test_runtime_persist.py:22`) — 이것이 오염의 물증이었다.

   ⚠️ **오염과 발현이 분리된다.** 쓰는 순간에는 증상이 전혀 없다 — 실행 중인 프로세스는 메모리
   상태로 계속 돈다(실제로 13:35 오염 후 **17:14까지 정상 작동**했다). **다음 재기동에서야** 터진다.
   그래서 "테스트 돌린 날 멀쩡했다"는 안전의 증거가 아니다.

   메인 리포에서 스위트를 돌려버렸다면, **그날 안에 아래를 조회해 오염 여부를 확인할 것**:
   ```bash
   sqlite3 -readonly -header -column "file:backend/data/storage.db?mode=ro" \
    "SELECT key, substr(value,1,70) value, substr(updated_at,1,19) upd
     FROM app_settings ORDER BY updated_at DESC LIMIT 10;"
   ```
   `updated_at`이 스위트 실행 시각과 겹치는 행, 특히 `check_interval:5` / `max_concurrent:10` 같은
   **픽스처 냄새가 나는 값**을 찾는다. 기본값과 우연히 같은 값(`max_concurrent:3`)은 구별되지 않으니
   `updated_at`이 1차 단서다.

   ### ✅ 2026-08-12: DB는 코드로 막았다 — 그러나 규칙은 그대로다

   `948e9ea`로 conftest에 **autouse 가드**를 넣었다. 라이브 `storage.db`/`holidays.db` 경로를
   여는 시도를 tmp 샌드박스로 돌리고(`db_path=None` 기본 경로까지), 세션 끝에 어떤 테스트가
   그랬는지 이름으로 보고한다. **실측 16개 테스트가 라이브 경로를 열려 하고 있었다** —
   `test_approval_pending_ssot.py`(5건) · `test_autonomy_injector.py` ·
   `test_kr_analysis_sm_migration.py` · `test_status_routes_ssot.py` ·
   `test_websocket_session.py` · `test_hitl_execution_routing.py` · `test_watch_refresh_loop.py` 등.

   🔴 **그래도 메인에서 돌리지 마라. DB는 겹치는 자원의 일부일 뿐이다.**
   2026-08-12 실측 — 메인에서 스위트를 돌리자 라이브 백엔드 로그에 이것이 쌓였다:

   ```
   telegram_receiver_polling_error
     error='Conflict: terminated by other getUpdates request'   ← 18건
   ```

   **테스트가 라이브 Telegram 봇의 폴링을 빼앗았다.** 장중이었다면 손절·익절 통지가 유실된다.
   14% 진행에 5분이 걸렸으니 완주하면 35분 이상 그 상태다(그래서 중단했다).
   Kiwoom 레이트리밋도 공유한다.

   | 실행 위치 | Telegram 폴링 강탈 |
   |---|---|
   | 메인 리포 | **18건** |
   | 워크트리 | **0건** (`.env`가 없어 토큰이 없다) |

   ### 🔴 그런데 워크트리도 Kiwoom에는 안전하지 않았다 (2026-08-12 발견)

   `32a6db3`의 엔드포인트 가드를 켜고 **워크트리에서** 전체 스위트를 돌렸더니
   **39건이 차단됐고 전부 `mockapi.kiwoom.com`이었다.** Telegram은 0건이다.

   차이는 자격증명의 **출처**다:

   | | 출처 | 워크트리에서 |
   |---|---|---|
   | Telegram | `.env`의 `TELEGRAM_BOT_TOKEN` | 없음 → 시도조차 안 함 |
   | Kiwoom | **URL이 코드에 하드코딩**(`client.py:214-215`) | **39건 시도** |

   인증은 실패하지만 **요청 자체는 나가 레이트리밋을 소모한다.** 개장 직후 `ka10001`
   초과가 상시로 나는 것과 무관하지 않을 수 있다.

   ⭐ **워크트리 규칙은 필요조건이었지 충분조건이 아니었다.** `.env` 부재는 Telegram만
   막는다. 코드에 URL이 박힌 것은 어디서 돌리든 나간다 — 이 가드가 그 구멍을 처음 드러냈다.

   **가드는 규칙의 대체가 아니라 그물이고, 규칙 혼자로는 구멍이 있었다. 둘 다 필요하다.**
3. ~~**`kill`은 어시스턴트 권한 밖이다.**~~ **정정(2026-08-12): 세션에 따라 다르다.**
   08-12 세션에서는 어시스턴트가 `kill -TERM 22135`를 직접 실행해 성공했다. **먼저 시도해 보고,
   거부되면** 사용자에게 `! kill -TERM <PID>` 실행을 요청할 것 — 무조건 요청부터 하면 왕복이 는다.
4. **`git stash` 금지** — 워크트리 여럿이 스택을 공유한다.
5. **장중 재시작 금지가 기본** — 손절이 이 프로세스에만 있고 브로커에 스탑이 없다.
6. pytest 출력의 ANSI 색상 때문에 `grep "^FAILED"`가 0건을 반환한다. `sed 's/\x1b\[[0-9;]*m//g'`.
7. **전체 스위트 기준선 = 21 failed / 3,249 passed / 1 skipped** (`04fec8b`, 워크트리, 6분 30초).
   측정 조건을 함께 적는다 — 조건이 다르면 숫자가 달라진다:
   ```bash
   git worktree add --detach <tmp> <commit>
   cd <tmp>/backend && /Users/sunghoonk/anaconda3/envs/agentic-trading/bin/python \
     -m pytest -q --no-header -p no:cacheprovider --no-cov
   ```
   ⚠️ **21건 중 6건은 Telegram 인증 테스트**다 — 워크트리에 `.env`가 없어 토큰이 없기 때문이고,
   메인에서 돌리면 이 6건은 통과할 수 있다. **기준선은 환경에 따라 다르다.**
   (옛 기준선 "21 failed / 3,230 passed"에서 passed가 +19 늘어난 것은 `--import-mode=importlib`로
   새로 실행된 충돌 파일 11건 + DB 가드 5건 + 엔드포인트 가드 5건 때문이다.
   failed 수는 세 번 측정 내내 **21로 고정** — 가드 3종 전부 **회귀 0**.)
8. ✅ ~~**동명 테스트 파일이 수집을 죽인다**~~ — `948e9ea`로 봉합(`--import-mode=importlib`).
   `tests/services/`와 `tests/test_services/test_trading/`에 `test_risk_monitor_alert_dedup.py`가
   **둘 다 실재**하고 `__init__.py`가 없어, 기본 import 모드에서 basename이 충돌해
   `Interrupted: 1 error during collection`으로 스위트가 통째로 죽었다. `__pycache__`를 지워도 재발한다.
   ⚠️ **`import-mode`는 ini 키가 아니라 CLI 옵션이다.** ini에 쓰면 `Unknown config option` 경고만
   뜨고 조용히 무시된다 — `addopts`에 넣어야 한다. 검증 없이는 "고쳤다"고 오인하기 쉽다.
9. **원장 합을 브로커 잔고에 더하지 말 것.** 원장 체결 누적은 **이미 잔고 그 자체**다.
   2026-08-11에 이 문서가 직접 밟았다 — "스냅샷 3,115 + 오늘 체결 355 = 브로커 3,470"으로 계산해
   존재하지 않는 불일치를 🔴 경보로 적었다. 실제 브로커는 3,115였다. 불일치를 주장하려면
   `/api/kr_stocks/positions`(kt00004 직접 조회)로 **대조**해야 한다 — 산수로 만들면 안 된다.
10. **기동 후 서버 리스닝까지 5~40초.** 그 전 `curl`은 `HTTP 000`이다. 죽은 게 아니다
    (08-11 37초 · 08-12 5초·11초 — 편차가 크다).
11. zsh에서 `grep --include=*.py`는 glob 확장으로 실패한다 — `--include="*.py"`로 따옴표를 칠 것.
12. 🔴 **teardown보다 오래 사는 것은 function 스코프로 못 막는다.**
    `updater.start_polling()`은 폴링 **태스크**를 만들고 즉시 반환한다(`receiver.py:20`).
    function 스코프 monkeypatch는 테스트가 끝나면 되돌아가는데 그 태스크는 계속 살아
    라이브 봇을 폴링한다. 2026-08-12에 transport 가드만 넣었다가 이걸로 샜다 —
    `getMe`는 막혔는데(RuntimeError 로그 확인) 충돌은 18→**39건**으로 늘고
    테스트 종료 후인 05:32까지 이어졌다.
    ⭐ **막을 지점은 요청이 아니라 태스크 생성이다.** `Updater.start_polling` 자체를
    차단하고 픽스처를 **세션 스코프**로 올려야 한다(`32a6db3`).
13. 🔴 **파괴적 부작용이 있는 RED는 안전장치를 먼저 단언하라.**
    2026-08-12에 라이브 DB 가드를 TDD로 만들면서, 경로 검증을 쓰기 **뒤에** 뒀다:
    ```python
    await storage.set_app_setting(...)                   # ← 가드 없는 RED에서 실제로 실행됐다
    assert Path(storage.db_path) != _LIVE_STORAGE
    ```
    가드가 없는 RED 단계에서 그 쓰기가 실행돼 **08-11과 똑같은 값으로 라이브를 덮었다**(백업 복구).
    재현 테스트를 쓰다가 사고를 재현한 것이다. 검사를 쓰기 **앞**으로 옮기면 RED가 안전장치에서
    멈춰 부작용에 닿지 않는다.

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
| ✅ | ~~**테스트 DB 오염을 코드가 못 막는다**~~ — `948e9ea`로 conftest autouse 가드 배포. 라이브 경로를 tmp로 돌리고 세션 끝에 위반 테스트를 이름으로 보고한다. 회귀 0(21 failed 동일) | 2026-08-12 |
| ✅ | ~~**Telegram·Kiwoom에는 가드가 없다**~~ — `04fec8b`+`32a6db3` 배포. httpx 전송 계층에서 `api.telegram.org`·`api.kiwoom.com`·`mockapi.kiwoom.com`을 차단하고, `Updater.start_polling`을 태스크 생성 전에 막는다(세션 스코프). 회귀 0 | 2026-08-12 |
| 🟡 | **테스트가 Kiwoom에 39건 붙고 있었다** — 워크트리에서도. URL이 코드에 하드코딩(`client.py:214-215`)이라 `.env` 부재로도 안 막힌다. 가드가 지금은 차단하지만, 근본은 각 테스트가 `httpx.MockTransport`/`respx`를 쓰는 것이다. 목록은 스위트 실행 시 RuntimeError 메시지로 드러난다 | 2026-08-12 |
| 🟡 | **격리 없이 라이브 DB 경로를 여는 테스트 16개** — 가드가 막고는 있지만 근본은 각 파일이 `isolated_storage_service`를 쓰는 것이다. 목록은 스위트 실행 시 `LIVE-DB GUARD` 블록에 찍힌다 | 2026-08-12 |
| 🟡 | **중복 테스트 파일 정리** — `tests/services/test_risk_monitor_alert_dedup.py`(4건)는 `tests/test_services/test_trading/`의 7건이 사실상 포함한다. 고유한 것은 `test_alert_history_records_every_call_regardless_of_dedup` 하나. 흡수 후 구 파일 제거 | 2026-08-12 |
| 🟡 | **Telegram Markdown 파싱 실패가 상시화** — 08-04부터 반복. plain 폴백이 100% 살리고 있어 유실은 없지만(08-12 실측 2/2), 결정 텍스트의 이스케이프 누락이라는 원인은 그대로 | 2026-08-12 |
| 🟡 | **`agent-chat` 실행 중에는 설정을 영속할 수 없다** — `start()`가 `if self._running: return`(coordinator.py:606)으로 조기 반환해 `_persist_runtime_state()`(:659)에 못 닿는다. 값을 바꾸려면 `stop→start`가 필요한데 `stop()`이 진행 중 토론을 `room.cancel()`한다. 별도 `PATCH /agent-chat/config`가 있으면 장중에도 안전하게 바꾼다 | 2026-08-12 |

---

## 참고 — 확인된 정상 동작

- **시간외 단일가(15:40~18:00)에 체결이 난다.** 2026-08-11 16:35에 028670 355주 매수. `market_hours.py:261`에 정의된 정상 세션이다 — 이상 아님.
- 게이트 검사 8이 처음 물렸다(08-11, 439090 BUY 거부: `projected 15.87% > cap 15.10%`). 산수 검증 완료, 정상.
- **개장 직후 `ka10001` rate limit이 1~2건 난다.** 재시도로 전부 복구되고 `kiwoom_rate_limit_exhausted`는 0건이다 — 조치 불필요(08-11·08-12 연속 확인).
- **`agent-chat` 기동 직후 첫 체크가 즉시 실행된다**(`next_run_time=datetime.now()`, coordinator.py:635). 그래서 "재기동 직후 토론 0건인 창"은 **존재하지 않는다** — 08-12에 그 창을 노렸다가 진행 중 4건을 취소시켰다.
- **저하 태그는 실패가 아니다.** `/exposure`·`/brief`의 `⚠️` 줄은 "판정은 났고 입력 하나가 낡았다"는 꼬리표다. `f5af713` 이후 사람 말 + 원문 병기로 나온다.
