# P2 디스커버리 퍼널 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** 관심종목 3중명칭/3저장소 분산을 정리 — 메인 대시보드에 발견→감시→실행 단일 퍼널. 죽은 백엔드(Scanner 제어·auto_promote·watch-list/add) 신규개발 0으로 노출. 선행 부채(KR 포지션 소스·Watchlist 영속) 봉합.

**Spec:** `docs/superpowers/specs/2026-07-14-funnel-consolidation-design.md`
**Audit:** `docs/superpowers/audits/2026-07-14-ui-wiring-audit.md`

## Global Constraints
- C1 HITL 라이브 불변(:8001 master OFF+hitl, :5173). FE=HMR, 백엔드=재시작 배포(구현 중 미접촉).
- 커밋 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. 스펙문서 tracked.
- 백엔드 테스트: `cd backend && env -u OPENROUTER_API_KEY python -m pytest <파일> -v -p no:logging`(full test_api/unfiltered test_services 금지). FE: `cd frontend && npx tsc --noEmit && npx vitest run <파일>`(navigation-bug 1 pre-existing 허용).
- 이원 SSOT: 클라 **Scratchpad**(기존 basket)=수동 리서치 스테이징 / 서버 **Watchlist(감시)**=WATCH·스캐너승격 산출물. "Watchlist" 명칭은 서버 리스트 독점.
- **결정됨**: DebatePanel 살리기(WS+토론개시+딥링크). mosaic 레이아웃 STORAGE_KEY **v4→v5 버전범프(초기화)**.
- **auto_promote 토글은 자율 파이프라인을 실제로 켠다** — HITL/master gate와 상호작용, 사용자가 "승격→자율큐" 흐름을 인지하도록 UI 명시.

---

## Phase 0 — 선행 부채 (backend, 통합 前)

### Task 1: KR 포지션 = 브로커 balance 단일소스
**Files:** Modify `backend/app/api/routes/kr_stocks/positions.py`(get positions ~:37-101), Test `backend/tests/test_api/`
**근본:** `storage.get_kr_stock_positions()` 부재→`except AttributeError`로 항상 `[]`. KR writer 전역 0건. Operations '보유'(브로커 kt00004)와 값 갈림.
- [ ] Step1 실패테스트: `GET /positions`(KR)가 `get_account_balance().holdings`(kt00004)를 소비해 실 홀딩(종목/수량/평단/현재가/평가손익) 반환; 브로커 조회 실패 시 정직 강등(빈+에러, 조작 0 아님). 미실현 P&L이 holdings 기반 계산.
- [ ] Step2~4: 죽은 스토리지 분기 제거→balance holdings 배선. Operations '보유'와 **동일 소스로 값 일치**(회귀로 두 경로 동일 종목 동일 수량 확인). SL/TP 편집은 T7(P1) 봉합 유지.
- [ ] Step5 커밋: `fix(kr): KR 포지션 소스=브로커 balance 단일화 — 스토리지 미구현 봉합 (P2 선행)`

### Task 2: 서버 Watchlist 영속 + 리프라이싱 + 자율 CONVERTED 정리
**Files:** Modify `backend/services/trading/coordinator.py`(영속 blob·리프라이스), `backend/services/agent_chat/coordinator.py`(실행 후 CONVERTED), Test 신규
**근본:** watch_list가 app_settings blob에 없어 재시작 소실; 워치 current_price 등록시점 고정; 자율 실행이 convert_watch_to_queue 미경유→중복 트리거.
- [ ] Step1 실패테스트: (a) watch_list 항목 추가 후 영속→restore 시 복원(positions/queue 패턴); (b) `_reprice_positions`(또는 워치 리프라이스)가 워치 항목 current_price 갱신, None/0이면 직전값 유지(T2 stale 계약); (c) 자율 경로가 워치→큐 실행 시 해당 항목 status=CONVERTED 마킹(재토론 방지).
- [ ] Step2~4: coordinator 영속 blob에 `watch_list` 키 추가+start 복원; 리프라이스 루프에 워치 포함; agent_chat/coordinator 실행 경로가 워치 항목 CONVERTED 처리. 회귀 r5_p1 영속·워치 테스트 PASS.
- [ ] Step5 커밋: `fix(trading): 서버 Watchlist 영속+리프라이싱+자율 CONVERTED 정리 (P2 선행 SSOT)`

---

## Phase 1 — 퍼널 통합 (FE)

### Task 3: basket → Scratchpad 개명
**Files:** Modify `frontend/src/store/index.ts`(basket 슬라이스 라벨/타입), `frontend/src/nav.ts`, `frontend/src/pages/BasketPage.tsx`(제목), `frontend/src/store/basket-rehydrate.test.ts`, 관련 라벨. Test 동반.
**근본:** '관심종목' 3중 명칭. basket을 "Scratchpad"로, nav 'Watchlist' 라벨을 서버 watch-list로 재지정.
- [ ] Step1: FE 사용자 표시 라벨을 "Scratchpad"(또는 "리서치 목록")로 — 사이드바/페이지제목/대시보드 basket 타일. nav 'Watchlist' 항목을 서버 watch-list(Operations 감시) 지향으로 재지정. 내부 store 식별자(basket)는 점진(개명 시 persist 키/partialize/merge/rehydrate test 동반 수정, 영속 데이터 마이그레이션 안전). TDD: rehydrate 회귀 유지, 개명 후에도 기존 저장 항목 복원.
- [ ] Step2 커밋: `refactor(fe): basket→Scratchpad 개명·nav Watchlist 재지정 — 명칭충돌 해소 (P2)`

### Task 4: DISCOVERY 구획 컴포넌트 (Scanner 제어+auto_promote+Scratchpad+승격▲)
**Files:** Create `frontend/src/components/terminal/panels/DiscoverySection.tsx`, Modify `frontend/src/components/terminal/commands.ts`(선택), Test 신규
**근본:** Scanner pause/resume/stop 죽음(호출0), auto_promote 켤 UI 전무, watch-list/add 클라함수 죽음.
- [ ] Step1 실패테스트: DiscoverySection이 (a) Scanner ▶시작(startScan, auto_promote 토글 상태 전달)·⏸/⏹(pause/resume/stopScan 배선)·진행바; (b) 스캔결과 상위N(액션뱃지·신뢰도) 각 행에 [승격▲](`POST /watch-list/add` 클라함수 배선)·[분석▶](useStartAnalysis); (c) Scratchpad(검색+추가, 기존 BasketWidget 로직 재사용) 항목에 [분석▶][승격▲]; (d) auto_promote 토글에 "자율큐로 흘러감" 경고 문구. 각 버튼이 올바른 클라함수를 정확한 인자로 호출.
- [ ] Step2~4: 컴포넌트 구현(기존 BasketWidget/ScannerPanel/client.ts 함수 재사용, 신규 백엔드 0). auto_promote ON+master gate 상호작용 경고 명시. TDD 통과+tsc.
- [ ] Step5 커밋: `feat(fe): DISCOVERY 구획 — Scanner 제어·auto승격토글·Scratchpad·승격버튼 (P2 퍼널)`

### Task 5: 퍼널 조립 + WATCHLIST/PIPELINE 구획 + mosaic v5
**Files:** Create `frontend/src/components/terminal/panels/FunnelPanel.tsx`, Modify `frontend/src/components/terminal/TerminalDashboard.tsx`(PanelId/TITLES/DEFAULT_LAYOUT/renderBody + STORAGE_KEY v5), Test
**근본:** 발견→감시→실행이 흩어짐. 한 화면 세로 퍼널로.
- [ ] Step1 실패테스트: FunnelPanel이 DISCOVERY(Task4)+WATCHLIST(서버 SSOT: 종목·target_entry·신뢰도·상태 [큐전환→convertWatchToQueue][제거✕removeFromWatchList])+PIPELINE(기존 OperationsPanel 6열 로직 재사용: 분석중·승인대기·매수대기·보유·오늘체결, 섹션별 정직강등 계약 유지)를 세로 배치. TerminalDashboard에 funnel 패널 등록(4곳 정합), STORAGE_KEY v5.
- [ ] Step2~4: 조립 구현. 섹션별 null+errors 정직강등 유지(위장 금지). v5 범프로 저장 레이아웃 초기화. tsc+회귀.
- [ ] Step5 커밋: `feat(fe): 발견→감시→실행 퍼널 패널 조립+mosaic v5 — 디스커버리 통합 (P2 퍼널)`

### Task 6: DebatePanel 살리기 (WS+토론개시+딥링크)
**Files:** Modify `frontend/src/components/terminal/panels/DebatePanel.tsx`, wire `frontend/src/hooks/useAgentChatWebSocket`(기존), Test
**근본:** 고립 REST폴링 장식 타일(WS 미연결, 코디네이터 미기동, 버튼0).
- [ ] Step1 실패테스트: DebatePanel이 useAgentChatWebSocket로 실시간(message/vote/status_change/decision) 렌더(5초 REST 폴백 유지 or 대체); "토론 시작" 액션이 코디네이터 기동 경로 호출; 결과 클릭 시 /agent-chat 세션뷰어 딥링크. 코디네이터 미기동 시 정직 빈상태+시작 유도.
- [ ] Step2~4: WS 배선(기존 useAgentChatWebSocket 재사용)+시작 액션+딥링크. tsc+회귀.
- [ ] Step5 커밋: `feat(fe): Agent debate 위젯 살리기 — WS 실시간+토론개시+세션딥링크 (P2)`

### Task 7: 승인 UI 이중화 정리
**Files:** Modify `frontend/src/components/terminal/OrderTicketRail.tsx` 또는 OperationsPanel 승인열, Test
**근본:** OrderTicketRail·Operations '승인대기' 둘 다 같은 submitApproval — 대시보드에 승인/거부 버튼 이중 노출.
- [ ] Step1: 단일화 — 레일을 1차 승인면으로 유지하고 Operations '승인대기' 열은 요약/딥링크(또는 반대). 동일 submitApproval 계약 유지, 액션(승인/거부/취소) 누락 없음. TDD.
- [ ] Step2 커밋: `refactor(fe): 승인 UI 이중화 정리 — 단일 승인면 (P2)`

---

## Phase 2 — 죽은/장식 위젯 정리 (독립)

### Task 8: 죽은 위젯 삭제 + 이중 위젯 병합
**Files:** Delete `frontend/src/components/**/AgentWorkflowGraph/*`, remove `startAgentChatDiscussion`(client.ts, 미배선 시)·`setBasketUpdating`(store), 레거시 /positions 패널·/trading 이중 위젯(WatchListWidget/TradeQueueWidget) 정리. Test 갱신.
- [ ] Step1: grep로 소비자 0 재확인 후 삭제(AgentWorkflowGraph, setBasketUpdating). startAgentChatDiscussion은 Task6/4에서 배선됐으면 유지, 아니면 삭제. 레거시 포지션/이중 위젯은 퍼널이 대체하므로 제거(라우트 정합). tsc+회귀(삭제로 인한 import 오류 0).
- [ ] Step2 커밋: `chore(fe): 죽은/장식 위젯 정리 — AgentWorkflowGraph·미배선 헬퍼·이중 위젯 (P2 정리)`

---

## Task 9: P2 배포+검증 (컨트롤러) — P1 배포 흡수
- [ ] 백엔드 재시작(Phase0 + 잔여 P1 배포) → 상태복구(trading/start, 스탑·워치 자동복원) → 브라우저: 퍼널 3구획 동작(Scanner 제어·승격·Scratchpad·Watchlist SSOT·PIPELINE)·KR 포지션 브로커값·성과 패널·알림센터·Debate WS·재량 통제 확인. 정직강등(빈vs에러) 확인. 결과 레저.
