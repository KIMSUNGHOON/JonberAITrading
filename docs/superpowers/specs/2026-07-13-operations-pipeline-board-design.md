# OPERATIONS 운용 파이프라인 보드 — 설계

- **날짜**: 2026-07-13 (C1 HITL 운용 첫 개장일)
- **요청**: "Main dashboard에 어떤 종목을 분석하고 있는지, 어떤 종목을 감시/매수/매수대기/매도하는지 아무 정보가 표시되지 않는다 — 전반적으로 개선"
- **상태**: 설계 승인됨 (사용자, 2026-07-13)

## 1. 문제와 실증

C1 운용 중 실제로 발생한 갭 (2026-07-13 오전):

- 사용자가 WATCH 제안 2건을 승인하고 워치리스트→큐 전환까지 수행 → 지정가 매수 4건(삼성전자 144주 @260,000 3분할 + SK하이닉스 19주 @1,909,000, 합계 ≈₩7,370만)이 브로커에 **미체결**로 예약됨.
- 그러나 홈 대시보드는: WATCHLIST 타일 비어 있음, REASONING "활성 세션 없음", ORDER 레일 "NO PENDING ORDER", 미체결 주문은 앱 어디에도 상시 노출 없음.
- 새로고침 한 번으로 진행 중 분석 세션 2건과 승인 대기 제안이 화면에서 전멸.

## 2. 근본 원인 (코드 확인 완료)

| # | 원인 | 근거 |
|---|---|---|
| 1 | 홈 WATCHLIST 타일(`panels/WatchlistPanel.tsx`)은 **클라이언트 로컬 바스켓**(`selectBasketItems`)을 그림. 서버 워치리스트(`/api/trading/watch-list`)는 `/trading`의 별개 위젯(`WatchListWidget.tsx`)만 표시 — 같은 이름의 평행 구현 2벌 | WatchlistPanel.tsx:28-58 |
| 2 | 미체결 주문 컴포넌트(`KiwoomOpenOrders`)는 존재하나 `/positions`·`/workflow`에만 마운트 — 홈 mosaic에 타일 없음 | PositionsPage.tsx:65, WorkflowPage.tsx:176 |
| 3 | 분석 세션은 WS push로 스토어(`kiwoom.sessions`)에만 존재 — 서버 재수화 없음 → 새로고침 시 소실(승인 대기 제안 포함). 홈 REASONING 타일은 수동적 tail | store/index.ts:106-124, ReasoningPanel.tsx:9-34 |
| 4 | 거래 큐는 `/trading`, 체결 이력은 `/trades`에 갇힘. TradeQueueWidget의 "주문 완료" 라벨이 발주(접수)와 체결을 구분하지 않음 | TradeQueueWidget.tsx |

데이터·API·위젯은 대부분 존재 — **홈 배선 부재 + 새로고침 비영속**이 문제.

## 3. 사용자 결정

1. **형태**: 운용 파이프라인 보드 (분석중→승인대기→감시→매수대기→보유→오늘체결 전 수명주기를 한 타일에). 개별 타일 확충·요약 스트립 안 대신 채택.
2. **인터랙션**: **완전 인터랙티브** — 승인/거부 + 미체결 취소 + 감시→큐 전환 + 분석 세션 취소까지 보드에서 직접.
3. **판단 승인**: 홈 WATCHLIST 타일 → BASKET 개명(기능 유지), 레이아웃 키 v1→v2 버전 업(사용자 배치 1회 초기화).
4. 마켓 범위: 기존 타일 관례대로 `activeMarket` 추종. KR 우선, COIN은 매핑 가능한 컬럼만(세션·Upbit 미체결·보유), 큐/감시 컬럼은 KR 전용이라 코인 모드에서 숨김.

## 4. 백엔드 — 집계 엔드포인트 (신규 1개)

`GET /api/trading/operations?market=kiwoom`

보드가 한 번의 요청으로 전체 스냅샷을 수신 (개별 폴링 6개 → 1개, 키움 유량 보호):

```jsonc
{
  "analyzing":   [{"session_id", "ticker", "name", "status", "current_stage", "started_at"}],
  "awaiting":    [{"session_id", "ticker", "proposal": {"action","entry_price","stop_loss","take_profit","risk_score"}, "auto_approve_at"}],
  "watching":    [/* 기존 watch-list 항목 */],
  "pending_buy": {"queue": [/* PENDING/PROCESSING 큐 */], "open_orders": [{"order_id","stk_cd","qty","price","created_at"}]},
  "holding":     [{"ticker","qty","entry","cur","pnl","pnl_pct","stop_loss","take_profit"}],
  "today_fills": [{"ticker","side","qty","price","time"}],
  "errors":      {"open_orders": "조회 실패 사유" /* 실패 섹션만 */}
}
```

- 소스: `session_manager.get_all_sessions`(실재 확인, session_manager.py:431 — SQLite 영속이라 백엔드 재시작도 견딤) / 기존 watch-list·queue 코디네이터 / 브로커 orders·positions·trades(기존 캐시 경유) / 보유는 브로커 진실 + 코디네이터 관리 스탑 병합(ticker 기준).
- **부분 실패 정직성**: 섹션별 독립 수집 — 실패 섹션은 값을 `null`로 하고 `errors`에 사유를 기록(키 생략 없음, FE가 "없음"과 "조회 실패"를 구분). 0/빈 배열로 위장 금지 (스캐너 실패 정직 표기 전례 준용).
- 쓰기 액션은 전부 기존 엔드포인트 재사용: 승인/거부(approval), 분석 취소(`POST /api/kr_stocks/analysis/cancel/{id}`), 감시 제거/전환(watch-list DELETE·convert), 큐 dismiss, 주문 취소(`DELETE /api/kr_stocks/orders/{id}`). 신규 쓰기 API 없음.

## 5. FE — OperationsPanel 타일 (신규)

`frontend/src/components/terminal/panels/OperationsPanel.tsx`, `TerminalDashboard.tsx`의 mosaic에 등록(PanelId·TITLES·DEFAULT_LAYOUT·renderBody 4곳, 레이아웃 키 `jonber.dashboard.layout.v2`로 버전 업, OPERATIONS 기본 상단 와이드 배치).

6컬럼: **분석중 → 승인대기 → 감시 → 매수대기 → 보유 → 오늘체결** (각 컬럼 헤더에 카운트, 좁으면 타일 내부 가로 스크롤, honest-empty `—` 관례 준수).

| 컬럼 | 표시 | 액션 |
|---|---|---|
| 분석중 | 종목, 진행 단계 | 클릭→`/workflow/:id`, ✕ 취소 |
| 승인대기 | 액션/진입/손절/익절/리스크, 자율 카운트다운(`auto_approve_at`) | **[승인] [거부]** — 기존 `submitApproval` 재사용 |
| 감시 | 목표진입 vs 현재가, 등락% | [큐 전환] [제거] |
| 매수대기 | 큐 대기 항목 + 브로커 미체결(수량·지정가·경과) — **발주≠체결 구분 명시** | [주문 취소] |
| 보유 | 수량/평단/현재가/손익, 손절·익절 라인 | 클릭→`/positions` |
| 오늘체결 | 당일 매수/매도 체결 | 클릭→`/trades` |

갱신: 5초 폴링(기존 관례) + `useTradeNotifications`의 `/ws/trade-notifications` 이벤트(trade_executed/queued/watch_added/stop·take triggered) 수신 시 즉시 재조회.

## 6. 새로고침 세션 복원 (전제 작업)

앱 로드 시(App.tsx 초기화 or SessionBridge): operations의 `analyzing`+`awaiting`(또는 동일 소스 세션 목록)으로 스토어 `kiwoom.sessions` 재수화 → 진행 중 세션은 `ensureKiwoomSessionStreaming`으로 WS 재연결(멱등, 5c0d7c1의 공유 팩토리 재사용) → OrderTicketRail 승인 레일도 자동 복원. 기존 백로그 "FE 새로고침 세션 복원"의 해소.

## 7. 혼동·정직성 정리

- 홈 `WatchlistPanel` 타일명 **WATCHLIST → BASKET** (클라이언트 후보 바구니, :analyze 용도 유지). 서버 감시는 보드의 "감시" 컬럼이 담당.
- `TradeQueueWidget` "주문 완료" → **"발주 완료"** 라벨 정정.

## 8. 테스트

- 백엔드 TDD: operations 집계 정합(각 섹션 소스 병합), market 필터, 섹션별 실패 강등(브로커 예외 → errors 기록 + 타 섹션 정상), 보유 스탑 병합.
- FE: OperationsPanel 상태별 렌더(빈/정상/부분 오류/카운트다운) vitest, 재수화 로직 단위 테스트, tsc, 기존 스위트 회귀(FE 108+, backend 영향 subset).
- 라이브 검증: 실 스택(:8001/:5173)에서 분석 시작→보드 반영→승인→미체결 표시→새로고침 생존 E2E.

## 9. 범위 밖

- COIN 파이프라인 완전 대응(큐·감시의 코인 확장), /trading·/positions 위젯 통폐합, react-query 도입(폴링 표준화), 알림 이력 스토어화, WS 체결 이벤트 기반 실시간 주문 추적(R5-P4).
