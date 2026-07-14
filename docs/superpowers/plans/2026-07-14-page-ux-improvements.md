# Page UX 개선 Implementation Plan (Position 대안2 + Agent Chat 대안3)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Position 페이지 중복/빈 레이아웃·SL/TP 회귀 봉합(소스 통일), Agent Group Chat 페이지 난해함 해소(SSOT+마스터디테일+명명+가시화+수동토론).

**Audit/Design:** `docs/superpowers/audits/2026-07-14-page-ux-audit.md` (A/B 개선안, A-Unit/B-Unit). 사용자 승인=Position 대안2, AgentChat 대안3.

## Global Constraints
- C1 라이브 가동 중(:8001 재시작 배포됨, :5173 HMR). 커밋 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. 문서 tracked.
- 백엔드 테스트: `cd backend && env -u OPENROUTER_API_KEY python -m pytest <파일> -v -p no:logging`. FE: `cd frontend && npx tsc --noEmit && npx vitest run <파일>`(navigation-bug 1 pre-existing 허용).
- 퍼널 PIPELINE `HoldingColumn`(`/operations` 소스)이 SL/TP 정확한 유일 표면 — Position 우측을 이 소스로 통일.
- Agent Chat on/off는 `/agent-chat` Status Card를 SSOT로, DebatePanel·TradingDashboard는 읽기전용 상태칩+딥링크로 강등.

---

## Phase A — Position 페이지 (대안 2: 소스 통일)

### Task A1: 좌측 계좌카드 미니리스트 제거 + 계좌 요약 순화
**Files:** Modify `frontend/src/components/kiwoom/KiwoomAccountBalance.tsx`(:216-236 보유종목 미니리스트), (coin 라벨)`frontend/src/components/coin/CoinAccountBalance.tsx`, Test
**근본:** 좌측 계좌카드 안 "보유 종목" 미니리스트가 우측 보유 패널과 동일 kt00004 데이터를 중복 표시(육안 확인).
- [ ] Step1: `KiwoomAccountBalance`의 보유종목 서브리스트(216-236) 제거 → 좌측=현금·평가액·예수금 **계좌 요약 전용**. 헤더/의미를 "계좌 요약"으로 명확히(중복 제거, 계좌 총액/예수금/주식평가만). Coin 좌측 라벨을 "계좌 잔고(원장)"로 명확히(우측 추적 포지션과 구분). TDD: 미니리스트 미표시, 계좌 요약 수치 유지.
- [ ] Step2 커밋: `refactor(fe): Position 계좌카드 보유 미니리스트 제거 — 중복 해소 (대안2 A1)`

### Task A2: 우측 KR 보유 패널 소스 → /operations 통일(SL/TP 표시)
**Files:** Modify `frontend/src/components/kiwoom/KiwoomPositionPanel.tsx`(또는 `HoldingColumn` 재사용), `frontend/src/pages/PositionsPage.tsx`, Test
**근본:** 우측이 `/kr_stocks/positions`(SL/TP=None 하드코딩) 독립 폴링 → SL/TP 항상 대시 + 퍼널과 4중 분산. 퍼널과 동일 `/operations` holding으로 통일하면 SL/TP 표시 + 단일 진실.
- [ ] Step1 실패테스트: 우측 KR 보유가 `/operations` holding(coordinator/PM 보강 SL/TP 포함)을 소스로 사용 → SL/TP 표시됨(대시 아님), 퍼널 PIPELINE 보유와 동일 값. 청산 버튼은 기존 close 경로 유지(전량매도, T1b). STOP/TAKE 인라인 편집은 `/operations`/risk_monitor 경로와 재조회 일치(저장 후 되돌아감 회귀 봉합) 또는 편집 불가면 명시.
- [ ] Step2~4: `KiwoomPositionPanel`을 `/operations` holding 소스로 전환(또는 `HoldingColumn` 재사용). 필드 매핑·청산 경로 검증. 회귀.
- [ ] Step5 커밋: `fix(fe): Position 우측 KR 보유 소스 /operations 통일 — SL/TP 표시·단일진실 (대안2 A2)`

---

## Phase B — Agent Group Chat 페이지 (대안 3: 전면 재구조)

### Task B1: 코디네이터 on/off SSOT + 3중 컨트롤 강등 + Debate 딥링크
**Files:** Modify `frontend/src/components/terminal/panels/DebatePanel.tsx`(:181 토론시작→상태칩+딥링크, :198 세션ID 전달), `frontend/src/components/trading/TradingDashboard.tsx`(:222-230 brain 버튼→상태칩+딥링크), `frontend/src/components/agent-chat/AgentChatDashboard.tsx`(Status Card=권위 소스 유지), Test. **`DebatePanel.test.tsx:149`가 "토론 시작→startAgentChat" 계약 검증 → 강등 시 테스트 수정.**
**근본:** 동일 코디네이터 on/off가 3곳(AgentChat/Debate/Trading)에 다른 라벨로 중복 → 사용자 혼란. Debate "세션 보기"가 세션ID 미전달로 목록 첫화면 낙하.
- [ ] Step1: DebatePanel·TradingDashboard의 코디네이터 Start/Stop 버튼을 **읽기전용 상태칩(running/last_check) + "/agent-chat에서 제어 →" 딥링크**로 강등(SSOT=/agent-chat Status Card). DebatePanel "세션 보기 →"에 현재 세션ID 전달 딥링크(`/agent-chat?session=…` 또는 상태). TDD: 강등된 화면은 start 호출 안 함(칩만), 딥링크가 세션ID 포함.
- [ ] Step2 커밋: `refactor(fe): 코디네이터 on/off SSOT=/agent-chat, Debate/Trading은 상태칩+딥링크 강등 (대안3 B1)`

### Task B2: 마스터-디테일 재구조 + 명명 정정 + last_check 가시화
**Files:** Modify `frontend/src/components/agent-chat/AgentChatDashboard.tsx`(:121-128 full-swap→master-detail, :189 명명), `frontend/src/components/agent-chat/ChatSessionViewer.tsx`(브레드크럼), Test
**근본:** 세션 선택=전체 페이지 스왑(앱 유일 네비 문법), "Start" 명명이 "자동 모니터링 스케줄러 켜기"인데 즉시 토론 기대 유발, last_check 미표시.
- [ ] Step1 실패테스트: 세션 선택 시 리스트가 사라지지 않고 유지(마스터-디테일) 또는 상세 상단 세션 컨텍스트 브레드크럼(종목/상태/← 목록). Start 버튼 라벨="자동 모니터링 시작 (5분 주기)". Status Card에 `last_check_at`→"다음 점검까지 mm:ss" 또는 마지막 점검 시각 렌더(루프 생존 가시화). TDD.
- [ ] Step2~4: 구조 재편(리스트 유지 or 브레드크럼), 명명, last_check 렌더. 회귀.
- [ ] Step5 커밋: `feat(fe): AgentChat 마스터-디테일+명명정정+last_check 가시화 (대안3 B2)`

### Task B3: 페이지 내 수동 토론 입력 + 빈 상태 정직화
**Files:** Modify `frontend/src/components/agent-chat/AgentChatDashboard.tsx`(수동토론 입력, :269 Active Discussions 조건부), `frontend/src/components/agent-chat/PositionMonitor.tsx`(빈상태·EventItem), `frontend/src/api/client.ts`(`startAgentChatDiscussion` 재사용), Test
**근본:** 페이지에 종목별 토론 시작 입력 없음(⌘K에만), Active Discussions 0건시 사라짐, PositionMonitor "Add positions"는 존재하지 않는 UI 안내, EventItem 클릭 불가.
- [ ] Step1 실패테스트: 종목 입력→`startAgentChatDiscussion` 호출(페이지 내 수동 토론). Active Discussions 0건시 섹션 유지+"다음 점검 mm:ss · 조건 충족 종목 없음" 설명. PositionMonitor 빈상태 문구를 실동작("코디네이터 시작 시 계좌 자동 동기화")과 일치+존재않는 "Add positions" 제거. EventItem "Discussion Required" 클릭시 해당 세션 열기. TDD.
- [ ] Step2~4: 수동토론 입력 배선(기존 API), 빈상태 정직화, EventItem 클릭. 회귀.
- [ ] Step5 커밋: `feat(fe): AgentChat 페이지내 수동토론+빈상태 정직화+EventItem 클릭 (대안3 B3)`

---

## Task C: 배포 검증(컨트롤러)
- [ ] FE HMR 반영 → 브라우저: /positions 좌측 계좌요약 전용·우측 SL/TP 표시·중복 제거 / /agent-chat 마스터디테일·명명·last_check·수동토론·상태칩 강등 확인. 결과 레저.
