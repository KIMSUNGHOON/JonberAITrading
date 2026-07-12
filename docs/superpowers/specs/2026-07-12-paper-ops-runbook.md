# 모의투자 자율 운용 런북 (Paper-Proof Phase D2)

2026-07-12. Phase D3(관찰 운용)의 시작/중지/모니터링/사고 대응 절차. 모든 API 경로는 **현재 코드 기준으로 검증됨** (탐색 감사, 파일:라인 근거는 아크 레저 참조). 대상 서버는 항상 **모의투자(mockapi)** — 게이트 paper 하드코딩이 live를 차단한다.

## 0. 아키텍처 한 줄 요약

`agent_chat ChatCoordinator`(워치리스트 감시→토론→결정, **기본 휴면**)가 `trading ExecutionCoordinator`(큐/실행)를 단방향 호출한다. 자율 실행은 매 결정마다 `check_autonomy` 게이트(master env→마켓모드→paper→브레이커→포지션/금액캡)를 통과해야 한다. PositionManager(손절/익절 감시)는 agent-chat start 시에만 함께 기동된다.

## 1. 사전 조건

- `.env`: 모의투자 `KIWOOM_APP_KEY`/`KIWOOM_SECRET_KEY`, `KIWOOM_IS_MOCK=true`(기본), `UPBIT_TRADING_MODE=paper`
- 백엔드 기동 (env 마스터 게이트는 **재시작 필요** — 유일하게 런타임 전환 불가한 스위치):
  ```bash
  cd backend
  UPBIT_TRADING_MODE=paper KIWOOM_IS_MOCK=true AUTONOMY_ENABLED=true \
    <conda python> -m uvicorn app.main:app --port 8000
  ```
  Telegram 알림을 받으려면 `TELEGRAM_ENABLED=true` + 토큰/챗ID 추가.
- (선택) FE: `cd frontend && npm run dev` — 터미널 UI로 레일/REASONING/AGENT DEBATE 관찰.

## 2. 운용 시작 절차 (순서 중요)

1. **기준 자산 기록** — 성과 계측의 분모. 운용 개시 직전 1회:
   ```bash
   python scripts/paper_performance_report.py   # '현재 자산' 값을 기준 자산으로 기록
   ```
   이후 리포트는 `--base <기록값>`으로 실행.
2. **장중 스모크** (개장 후, 조회 전용): `python scripts/kiwoom_readonly_smoke.py` → 9/9 확인.
3. **kiwoom 자율 모드 전환** (즉시 반영, 재시작 불필요 — 게이트가 매 결정마다 storage를 읽음):
   ```bash
   curl -X PUT localhost:8000/api/settings/trading-mode \
     -H 'Content-Type: application/json' -d '{"market":"kiwoom","mode":"autonomous"}'
   ```
4. **실행 계층 기동**: `POST /api/trading/start` (바디 생략 가능; risk_params 기본 = 3% 일일한도 / 5 포지션 / ₩1M 캡)
5. **관심종목 등록** (ticker와 current_price 필수):
   ```bash
   curl -X POST localhost:8000/api/trading/watch-list/add \
     -H 'Content-Type: application/json' \
     -d '{"ticker":"005930","stock_name":"삼성전자","current_price":70000}'
   ```
6. **결정 계층 기동 = 실제 운용 시작**: `POST /api/agent-chat/start` (바디 생략 시 5분 주기 / 동시 토론 3). 이 호출이 PositionManager도 함께 기동하고 워치리스트를 즉시 1회 체크한다.

## 3. 모니터링

| 대상 | 방법 |
|---|---|
| 코디네이터 상태 | `GET /api/agent-chat/status` (is_running/active_discussions) · `GET /api/trading/status` |
| 포지션/손절익절 | `GET /api/agent-chat/positions/summary` · UI POSITIONS 타일 |
| 자율 승인 이벤트 | 로그 grep: `auto_approve_scheduled` / `auto_approved` / `auto_approve_stood_down` / `auto_approve_cancelled_at_recheck` / `gate` deny · UI 레일 카운트다운("자율 승인까지 N초") · Telegram(켰다면) |
| 성과 | `python scripts/paper_performance_report.py <운용시작일> --base <기준자산>` — 일일 마감 후 1회 실행·기록 권장 |

**60초 거부권**: 자율 승인 예정 알림 후 60초 안에 UI에서 REJECT/취소하면 수동 결정이 항상 이긴다. reject 후 재분석이 새 제안을 만들면 injector가 자동 재암된다(새 60초 유예).

## 4. 브레이커·이상 대응

- **daily-loss 브레이커 발동** (당일 실현손실 ≥ 3%): 자율 승인 전면 거부 + Telegram 1일 1회 통지. HITL은 정상 동작. 조치: 원인 분석(성과 리포트+체결 내역) → 당일은 그대로 두고(재발동 방지 로직이 매 결정 재계산) 익일 실현손실이 리셋되면 자동 해제.
- **브레이커 조회 실패**(모의서버 장애 등): fail-closed로 자율 거부 — 로그 `daily_loss_breaker` deny 확인. 서버 복구 후 자동 정상화.
- **미의도 주문 의심**: 즉시 킬스위치 1단(아래) → `GET /api/trading/status`·체결 내역(ka10076)으로 대조 → 아크 레저에 기록.

## 5. 킬스위치 (약한 순 → 강한 순)

1. **마켓 hitl 전환 (즉시, 재시작 없음 — 1차 권장)**:
   `PUT /api/settings/trading-mode {"market":"kiwoom","mode":"hitl"}` — 진행 중인 60초 유예도 grace-후 재확인 게이트에서 취소된다.
2. **결정 계층 정지**: `POST /api/agent-chat/stop` (토론/워치 감시/PositionManager 중지).
3. **실행 계층 정지**: `POST /api/trading/stop` (큐 처리 중지).
4. **마스터 차단**: 백엔드를 `AUTONOMY_ENABLED` 없이 재시작 (env 기본 false = 전 마켓 자율 불가).
5. 개별 세션은 UI REJECT/Cancel Analysis로 언제든 수동 개입.

## 6. 운용상 알아둘 성질 (코드 확인됨)

- **자동 손절/익절 "실행"은 기본 OFF** (`auto_execute_stop_loss=False`, `auto_execute_take_profit=False`, 트레일링 갱신만 ON) — 손절선 도달 시 주문이 아니라 **agent 토론이 트리거**되고, 그 결정이 다시 게이트를 거친다. 관찰 기간에는 이 기본값 유지 권장 (직접 청산까지 자율화할지는 D3 관찰 후 결정).
- 백그라운드 스캐너(`/api/scanner/*`)는 실존하지만 자율 파이프라인과 **자동 연동되지 않음** — 스캔 결과에서 관심종목을 골라 `/watch-list/add`로 수동 등록하는 흐름.
- 토론 합의 게이트: 컨센서스 75% 미만이면 NO_ACTION (검증 세션에서 54%→NO_ACTION 확인).
- 모의서버는 KRX만 지원, 장중에만 체결. 장외 주문은 다음 장 접수.

## 7. 일일 루틴 (관찰 기간, 제안 2주+)

1. 장 마감 후 성과 리포트 실행(`--base` 포함) → 값 기록.
2. 로그에서 `auto_approved`/`stood_down`/deny 건수 훑기 — **exit criteria 항목**: 게이트 오작동 0, 미의도 주문 0.
3. 특이사항(브레이커 발동, 재분석 재암, LLM 지연) 아크 레저에 한 줄 기록.
4. 주 1회: 누적 수익률/승률 스냅샷 — Phase E(실전 전환) 판단 자료.
