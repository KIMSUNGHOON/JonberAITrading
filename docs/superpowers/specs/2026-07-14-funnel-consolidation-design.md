# 디스커버리 퍼널 통합 설계 (2026-07-14)

> 근거: `docs/superpowers/audits/2026-07-14-ui-wiring-audit.md`. 사용자 승인 방향 = **2안(퍼널 통합)**, 선행 부채 분리.
> 전제: C1 HITL 라이브 불변. 이 문서는 설계이며 승인 전 구현 없음.

## 목표
"관심종목이 3중 명칭 + 3개 저장소로 분산"을 정리해, 메인 대시보드에 **발견→감시→실행** 단일 퍼널을 세운다. 이미 살아있으나 UI에 미노출인 백엔드(Scanner pause/resume/stop, auto_promote, watch-list/add)를 신규 개발 없이 켠다.

## 아키텍처 원칙
- **역할 분리형 이원 SSOT**(완전 단일화 아님):
  - 클라 **Scratchpad**(기존 basket, localStorage): 사용자 수동 리서치 스테이징 — 분석 시작용 임시 목록.
  - 서버 **Watchlist(감시)**(ExecutionCoordinator.watch_list): 시스템 감시 대상 — WATCH 결정/스캐너 승격 산출물, 5분 모니터→토론 트리거.
- "Watchlist" 명칭은 **서버 감시 리스트가 독점**. 클라 basket은 "Scratchpad"로 개명.
- 신규 백엔드 최소화: 기존 엔드포인트 노출 우선.

---

## Phase 0 — 선행 부채 (통합 PR과 분리, 먼저 착수)

### P0-a. KR 포지션 단일 소스 = 브로커 balance 확정
**문제:** `kr_stocks/positions.py:43`이 부재 메서드 `storage.get_kr_stock_positions()` 호출→`except AttributeError`로 항상 `[]`. KR 포지션 writer도 전역 0건. Operations '보유'(브로커 kt00004)와 값이 갈림.
**결정:** KR 포지션의 진실 소스를 **브로커 balance(kt00004 holdings)로 확정**. 스토리지 경로 폐기.
- `GET /positions`(KR)가 `get_account_balance().holdings`를 소비하도록 재배선(Operations '보유'와 동일 소스 → 값 일치).
- 대시보드 PositionsPanel의 KR 홀딩이 실제 브로커 데이터를 표시.
- SL/TP 편집은 T7 봉합대로 risk_monitor→coin_positions 폴백 유지(KR은 코디네이터 관리 종목만 유효, 아니면 정직 404).
- 죽은 스토리지 분기(`except AttributeError`) 제거.

### P0-b. 서버 Watchlist SQLite 영속
**문제:** `coordinator.py:1001-1023` app_settings blob에 watch_list 키 없음→재시작 소실.
**결정:** R5-P1 영속 blob에 `watch_list` 키 추가(positions/queue/daily_count와 동일 패턴). start 복원.

### P0-c. Watchlist 항목 가격 리프라이싱
**문제:** 워치 항목 `current_price`가 등록 시점 고정(`_reprice_positions`는 포지션 전용). 5분 모니터가 stale 가격으로 판정.
**결정:** `_reprice_positions`(P1-1)를 워치 항목에도 확장 or 워치 전용 리프라이스 루프. None/0이면 직전값 유지(T2 stale 계약).

### P0-d. 자율 실행 후 워치 항목 CONVERTED 정리
**문제:** 자율 토론이 실행까지 마쳐도 워치 status가 CONVERTED로 안 바뀜(`agent_chat/coordinator.py:403-514`가 convert_watch_to_queue 미경유)→재토론/중복.
**결정:** 자율 경로가 실행 시 해당 워치 항목을 CONVERTED로 마킹(중복 트리거 방지).

---

## Phase 1 — 퍼널 통합 (메인 대시보드)

### P1-a. basket → Scratchpad 개명
- store persist 키/partialize/merge, `basket-rehydrate.test.ts` 동반. 라벨/타입 개명(내부 식별자는 점진 가능).
- nav 'Watchlist' 라벨을 **서버 watch-list로 재지정**, Scratchpad는 퍼널 입구로.

### P1-b. 발견→감시→실행 3구획 퍼널 패널
메인 대시보드에 와이드 패널(또는 기존 타일 재편):
```
DISCOVERY : [Scanner ▶시작 ⏸ ⏹ + auto-promote 토글] 진행바 · 스캔결과 상위N(액션뱃지·신뢰도) [승격▲][분석▶]
            Scratchpad(수동추가): 검색+추가 [분석▶][승격▲]
WATCHLIST : 서버 SSOT · 종목·target_entry·신뢰도·상태 [큐전환→][제거✕]  (5분 모니터가 토론 트리거)
PIPELINE  : 분석중 → 승인대기(HITL) → 매수대기(큐) → 보유 → 오늘체결
```
- **승격▲**: Scanner결과/Scratchpad 항목을 서버 Watchlist에 추가 — 죽어있는 `POST /watch-list/add` 클라 함수 배선(신규 백엔드 불필요).
- **Scanner 제어**: 살아있는 pause/resume/stop 엔드포인트 노출(백엔드 작업 0).
- **auto-promote 토글**: `startScan({auto_promote_enabled:true})` 전달(백엔드 완성).
- PIPELINE 구획은 기존 OperationsPanel 6열 로직 재사용(섹션별 정직 강등 계약 유지).

### P1-c. 승인 UI 이중화 정리
OrderTicketRail vs Operations '승인대기' — 둘 다 같은 submitApproval. 하나로 통합(레일 유지 + Operations 열은 링크/요약, 또는 반대).

---

## Phase 2 — 죽은/장식 위젯 정리 (통합과 독립, 즉시)
- 삭제: `AgentWorkflowGraph/index.tsx`, `startAgentChatDiscussion`(client.ts) 또는 승격버튼에 배선, `setBasketUpdating` 죽은 액션.
- DebatePanel **살리기(결정됨)**: `useAgentChatWebSocket` 연결(실시간 message/vote/status_change/decision push, 기존 5초 REST 폴링 대체) + 이 타일에 **토론 개시 액션** 추가(코디네이터 기동) + 결과 클릭 시 /agent-chat 세션뷰어 딥링크. 고립 장식 타일 → 실동작 관제 카드로.
- 레거시 /positions KiwoomPositionPanel/CoinPositionPanel: 대시보드 PositionsPanel 부분집합 → 삭제 후보(KR은 P0-a 선행).
- /trading WatchListWidget·TradeQueueWidget vs Operations '감시'/'매수대기': 이중 UI → 병합.

---

## 회귀 위험 / 검증
- `TerminalDashboard.tsx` 타일 재편→localStorage 레이아웃 키 **버전 범프 v4→v5(결정됨)**: 저장 레이아웃 초기화, 새 퍼널 기본 레이아웃으로 리셋(사용자 커스텀 1회 소실 수용). PanelId/TITLES/DEFAULT_LAYOUT/renderBody 4곳 정합 갱신.
- OperationsPanel 섹션별 null+errors 정직강등 계약 유지(브로커/코디네이터/세션 3소스 혼합).
- nav 'Watchlist' 재지정→딥링크/북마크 영향.
- auto_promote 토글 노출 시 **자율 파이프라인이 실제로 켜짐** — HITL/master gate 상호작용 검증 필수, 사용자가 "승격→자율큐 흐름"을 인지하도록 UI 명시.
- 게이트: 백엔드 `env -u OPENROUTER_API_KEY -u AUTONOMY_ENABLED pytest -p no:logging`(서브셋). FE basket/scanner/operations vitest + 레이아웃 마이그레이션 수동. 라이브 :8001(master OFF+hitl)에서 각 구획 실 REST+정직강등 확인.

## 시퀀싱
Phase 0(선행 부채) → Phase 1(퍼널 통합) → Phase 2(정리). Phase 2 죽은위젯 삭제는 언제든 병행 가능. Phase 0-a/b/c/d는 상호 독립(병렬 가능).
