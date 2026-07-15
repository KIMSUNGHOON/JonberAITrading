# 보유 포지션 자율관리 실행 완성 Implementation Plan (P0~P3)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 지속 감시가 실제로 ADD/REDUCE/SELL 자율 실행까지 완결되게 — 현재 DEFENSIVE_ONLY(전량SELL만 실행, ADD=침묵, 부분REDUCE=장부 desync)를 봉합.

**Audit:** `docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md`.

## Global Constraints
- C1 라이브 :8001(master OFF+hitl). **배포(재시작)는 장중 금지** — 실행 변경은 장 마감 후 또는 명시 승인 후. 구현·리뷰는 무영향(재시작 전까지 라이브 미반영).
- 커밋 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 백엔드 테스트: `cd backend && env -u OPENROUTER_API_KEY python -m pytest <파일> -v -p no:logging`.
- **모든 신규 실행(ADD/BUY·부분REDUCE/SELL)은 반드시 `check_autonomy` 게이트 경유** — master gate·마켓모드·paper·브레이커·notional 캡. 기존 SELL 청산 패턴과 동일.
- 손절/익절 방어(RiskMonitor)는 불변 — 이미 올바름.

---

### Task P0: 정직화 (부분REDUCE desync + ADD 침묵 봉합) — 선행 필수
**Files:** Modify `backend/services/agent_chat/position_manager.py`(_apply_decision ~:950-1020), Test
**근본:** `_apply_decision`에서 (a) 부분 REDUCE가 `update_position(quantity=new)`만 호출 → 브로커 주문 없이 그림자 장부만 바뀌어 실계좌와 desync(다음 sync까지 거짓); (b) ADD가 HOLD와 동일 분기 → 매수 없이 스탑값만, 조용히 격하. **이 desync는 master OFF/hitl에서도 활성**(로컬 상태 변이라 게이트 안 탐).
- [ ] Step1 실패테스트: (a) 부분 REDUCE 결정 → 실행 경로 없음이면 **로컬 장부를 건드리지 않고**(현재처럼 몰래 줄이지 않음) "부분청산 미지원 — 실행 보류" 이벤트/로그+통지; (b) ADD 결정 → "추가매수 미지원 — 보류" 통지, 스탑값 갱신은 유지하되 조용하지 않게. 즉 **거짓 상태를 만들지 않고 명시적으로 미실행 표기**.
- [ ] Step2~4: _apply_decision 부분REDUCE 분기가 update_position으로 수량 조작하지 않도록(전량REDUCE=전량청산은 유지) + ADD/부분REDUCE 미실행 통지. 회귀: 기존 PositionManager 테스트 PASS.
- [ ] Step5 커밋: `fix(position): 부분REDUCE desync·ADD 침묵 정직화 — 거짓 장부 차단 (P0)`

### Task P1: 부분매도 실행 경로
**Files:** Modify `backend/services/trading/coordinator.py`(부분매도 지원), `backend/services/agent_chat/position_manager.py`(REDUCE→부분매도 배선), Test
**근본:** `coordinator._close_position`(1403-1426)이 quantity=position.quantity 하드코딩 전량청산 전용 → 부분매도 발주 호출부 자체가 없음.
- [ ] Step1 실패테스트: 수량 지정 부분매도 API(예: `_reduce_position(ticker, quantity)`)가 `check_autonomy(SELL)` 게이트 통과 시 지정 수량만 실제 매도(전량 아님). PositionManager REDUCE(부분) 분기가 이걸 호출해 실계좌 반영(P0의 미실행 표기 대체). 오버셀 불가(min(요청, 보유)).
- [ ] Step2~4: coordinator 부분매도 + PM 배선 + check_autonomy. 회귀 PASS.
- [ ] Step5 커밋: `feat(trading): 수량지정 부분매도 실행 경로 — REDUCE 실계좌 반영 (P1)`

### Task P2: ADD(추가매수) 실행 + 사이징 정책
**Files:** Modify `backend/services/agent_chat/position_manager.py`(ADD→매수 배선), 사이징 정책 로직, Test. **사이징 정책은 설계 결정 선행 — 사용자 확인.**
**근본:** ADD 실행 코드 전무 + "얼마를 더 살지" 사이징 로직 없음.
- [ ] Step1: 사이징 정책 결정(예: 기존 포지션의 N%, 고정 notional, 또는 신뢰도 비례) — **사용자 확인 후 확정**. 그 후 ADD가 `check_autonomy(BUY)` + notional 캡 + 브레이커 통과 시 사이징된 수량 매수. 진입 경로 on_trade_approved와 동일 안전수준.
- [ ] Step2~4: ADD 매수 실행 + 사이징 + 게이트. 회귀 PASS.
- [ ] Step5 커밋: `feat(trading): ADD 추가매수 실행 + 사이징 정책 (P2)`

### Task P3: 보유 포지션 주기적 전략 재평가 루프 (본체)
**Files:** Modify 관리 루프(PositionManager 또는 신규 스케줄러) + 분석 그래프 재사용 배선, Test. **설계 체크포인트 선행.**
**근본:** 현재 30초 루프는 방어 이벤트만 반응. 능동 "지금 재판단" 트리거 없음.
- [ ] Step1: 설계 — 보유 종목에 대해 주기적(N분/유의미 변화 시) position-aware 분석 그래프 재기동 → ADD/REDUCE/HOLD/SELL → P1/P2 실행 경로로. 재기동 스케줄러·중복억제(P4 dedup 재사용)·비용관리. **사용자 설계 승인 후 구현.**
- [ ] Step2~5: 구현 + 회귀. 커밋: `feat(trading): 보유 포지션 주기적 전략 재평가 루프 (P3 본체)`

### Task P4(배포): 실행 변경 배포 — 장 마감 후 또는 승인 후
- [ ] 백엔드 재시작 → REDUCE/ADD 실행·재평가 확인. 레저. **장중 금지.**
