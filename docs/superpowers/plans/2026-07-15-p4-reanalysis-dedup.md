# P4 재분석 dedup + 보유종목 인지 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 이미 포지션 있는 종목의 무의미한 재분석 낭비 차단 — (1) 티커 단위 진행중 세션 dedup, (2) 보유 종목은 position-aware 분석(ADD/REDUCE/HOLD)임을 인지·명시.

**Audit:** `docs/superpowers/audits/2026-07-14-autonomous-position-mgmt-audit.md` (§C P4). 근본: `/analysis/start`가 보유 여부·동일티커 중복 세션을 전혀 확인 안 함(전역 동시개수 세마포어만).

## Global Constraints
- C1 라이브 :8001(master OFF+hitl)·:5173 HMR. 백엔드 변경은 재시작 배포. 커밋 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 백엔드 테스트: `cd backend && env -u OPENROUTER_API_KEY python -m pytest <파일> -v -p no:logging`. FE: `npx tsc --noEmit && npx vitest run <파일>`.
- **실행 로직 불변**: 이 아크는 분석 요청 게이팅·인지만 — 매매 실행(on_trade_approved/_apply_decision)은 건드리지 않음(그건 P0~P3).

---

### Task 1: 티커 단위 진행중 세션 dedup (backend)
**Files:** Modify `backend/app/api/routes/kr_stocks/analysis.py`(start_kr_stock_analysis) + coin 분석 라우트(coin/analysis 또는 해당 경로), 세션 매니저 조회, Test 신규
**근본:** `/analysis/start`가 매번 새 uuid 세션 발급, 동일 티커 진행중 세션 확인 없음. agent-chat의 `_active_rooms`(ticker in _active_rooms→거부) 패턴을 분석 파이프라인에 이식.
- [ ] Step1 실패테스트: 동일 티커(stk_cd)로 진행중(RUNNING/AWAITING_APPROVAL) 세션이 이미 있으면, 두 번째 `/analysis/start`가 새 세션을 만들지 않고 **기존 세션 참조를 반환**(또는 409+기존 session_id). 완료/취소된 세션은 재분석 허용. KR+coin 양쪽.
- [ ] Step2~4: 세션 매니저에서 티커별 활성 세션 조회 헬퍼 + start 라우트에서 중복 가드. 회귀: 기존 analysis 라우트 테스트 PASS.
- [ ] Step5 커밋: `feat(analysis): 티커 단위 진행중 세션 dedup — 동일종목 중복분석 차단 (P4)`

### Task 2: 보유 종목 인지 + position-aware 확인 (backend)
**Files:** Modify `backend/app/api/routes/kr_stocks/analysis.py`(응답에 position_exists 플래그), 분석 그래프 decision 경로 확인(kr_stock_nodes/decision_nodes.py — 기존 포지션 인지 여부), Test
**근본:** 보유 종목 분석 시 사용자가 "이미 보유 중"임을 모르고 재요청. 또 decision이 보유를 인지해 ADD/REDUCE/HOLD를 내는지 확인 필요.
- [ ] Step1: (a) `/analysis/start`(또는 status 응답)가 해당 티커 보유 여부 `position_exists`를 반환(브로커 balance/coordinator positions 조회). (b) decision 노드가 기존 포지션을 인지해 BUY 대신 ADD/REDUCE/HOLD를 산출하는지 **검증 테스트**로 고정 — 이미 인지하면 문서화 테스트, 아니면 최소 배선(state에 current_position 주입)해서 position-aware하게. TDD.
- [ ] Step2~4: position_exists 플래그 + decision position-awareness 확인/봉합. 회귀 PASS.
- [ ] Step5 커밋: `feat(analysis): 보유 종목 인지(position_exists)+position-aware decision 확인 (P4)`

### Task 3: FE — 보유 종목 재분석 UX (dedup 라우팅 + 안내)
**Files:** Modify `frontend/src/hooks/useStartAnalysis.ts`(중복 세션 재사용 + 보유 안내), 분석 시작 UI(DiscoverySection/Scratchpad·Scanner 결과·Analysis), Test
**근본:** FE가 보유 종목에도 무조건 새 분석 요청.
- [ ] Step1 실패테스트: (a) 이미 진행중 세션이 있는 티커 분석 시작 시 새 세션 대신 기존 세션으로 포커스/이동(Task1의 dedup 응답 소비). (b) `position_exists` 시 "이미 보유 중 · 포지션 관리 분석" 표기. TDD.
- [ ] Step2~4: useStartAnalysis가 dedup/held 응답 처리, UI 안내. tsc+회귀.
- [ ] Step5 커밋: `feat(fe): 보유 종목 재분석 dedup 라우팅+관리분석 안내 (P4)`

### Task 4: 배포+검증
- [ ] 백엔드 재시작 → 동일 종목 재분석 차단·보유 안내 확인. 레저.
