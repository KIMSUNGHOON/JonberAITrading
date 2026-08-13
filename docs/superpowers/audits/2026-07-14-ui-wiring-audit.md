# UI 배선 실사 (2026-07-14)

6-에이전트 READ-ONLY 실사 + 종합자 직접 재검증. "화면에 보이는 것 vs 실제 동작"을 코드 인용으로 판정. 사용자 질문(Agent debate 역할, Scanner/position/실현손익 동작 여부, Basket/Scanner/Watchlist 통합) 대응.

## 정직 상태표

범례: ✅동작 / ⚠️일부 / ⛔사실상무효(코드 존재하나 도달불가) / 💀죽은코드

| 기능 | 상태 | 실제로 하는 일 | 근거 |
|---|---|---|---|
| Basket (클라 관심종목) | ✅ | Zustand+localStorage CRUD. "분석시작"=실 REST 세션 기동→kiwoom.sessions/coin 슬롯(데드엔드 아님) | store/index.ts:1402-1427; BasketWidget.tsx:564-597; useStartAnalysis.ts:38-91 |
| 대시보드 Basket 타일(WatchlistPanel) | ⚠️ | basket 읽기전용 파생뷰. VOL/RSI/SIGNAL 항상 —. 행클릭=차트심볼만 | WatchlistPanel.tsx:1-19,139-141 |
| Scanner 진행률 타일 | ⚠️ | 진행률 표시만, 버튼 0개 | ScannerPanel.tsx(119줄) |
| Scanner 시작 | ⚠️ | ⌘K `:scan` 한 곳, 인자없이 기본값 | commands.ts:101-106 |
| Scanner 일시정지/재개/중지 | 💀 | 백엔드/클라래퍼 살아있으나 호출부 0 | client.ts:1525-1538 |
| Scanner 자동승격(auto_promote) | ⛔ | 기본 False, 켤 UI 전무→항상 return 0 | scanner.py:563 |
| Scanner 결과페이지(/scanner) | ✅ | SQLite 조회+상세분석 개시 정상 | ScannerResultsPage.tsx:113-486 |
| 서버 Watch List | ⚠️ | WATCH 결정이 HITL 승인 前 등록(거부해도 남음). **SQLite 미영속(재시작 소실), 가격 정적**. 모니터→토론→큐 하류는 동작 | decision_nodes.py:329-360; coordinator.py:1001-1023,1976-1978 |
| Agent debate 위젯(DebatePanel) | ⚠️ | REST 5초폴링(WS 아님). 코디네이터 미기동 기본→대개 빈표. 버튼 0개. 고립 장식 타일 | DebatePanel.tsx:1-10; coordinator.py:87; main.py 자동기동 없음 |
| **KR Positions** | ⛔ | **항상 빈 리스트.** `storage.get_kr_stock_positions()` **메서드 부재**→except AttributeError. **KR 포지션 writer 전역 0건** | kr_stocks/positions.py:37-54; grep 0건 |
| Coin Positions | ✅ | coin_positions SQLite, 체결 시 save | storage_service.py:103,692,741 |
| 실현손익/Performance | ✅ | **ka10074+kt00004 실 브로커.** 0 근접=C1 개시 직후 체결無(버그 아님). 코인 실현손익 미포함(KR전용) | trading.py:1466-1525; paper_performance.py:138 |
| OperationsPanel '보유'열 | ✅ | 브로커 balance.holdings(kt00004). PositionsPanel(스토리지)과 **다른 소스** | trading.py:1344-1401 |
| OperationsPanel 나머지 5열 | ✅ | 전부 실 REST, 액션 즉시 refetch | OperationsPanel.tsx; trading.py:1262-1418 |
| OrderTicketRail vs Operations 승인대기 | ⚠️ | 같은 submitApproval, 승인UI 이중 노출 | OrderTicketRail.tsx:18,94 |
| AgentWorkflowGraph | 💀 | 소비자 0, R5-P2 후 파일만 잔존 | AgentWorkflowGraph/index.tsx |
| startAgentChatDiscussion | 💀 | 정의만, 호출 0 | client.ts:1642-1643 |

## 질문 직답 요약
- **Agent debate**: 고립 장식 타일. WS 미연결(REST폴링), 코디네이터 자동기동 없음, 버튼 0개 → 기본상태 항상 '—'. "기능 못 한다" 인상 구조적으로 정확.
- **KR Positions 빈칸**: 진짜 미완성(스토리지 메서드+writer 부재). 코인은 정상.
- **실현손익**: 정상 배선(오해). 0 근접은 체결이력 부재 탓.
- **Scanner**: 엔진 동작, 제어 표면만 미노출/미배선.

## 명칭 충돌 (3중 명칭 + 3개 저장소)
- 클라 Basket(localStorage): 대시보드 "Basket", nav "Watchlist"
- 서버 Watch List(인메모리): 대시보드 "감시", /trading "관심종목(WATCH)"
- Scanner Results(SQLite): 독립 3번째
→ 사용자가 "워치리스트"를 4곳에서 마주치는데 2곳은 클라 basket, 2곳은 서버 WATCH리스트.

## 통합 결론 (사용자 2안 선택)
- **서버 Watch List = "Watchlist(감시)" 이름 독점 + SSOT**, 클라 basket = **"Scratchpad"** 개명(퍼널 입구).
- 메인에 **발견→감시→실행 3구획 퍼널**. 이미 살아있으나 미노출인 백엔드(pause/resume/stop, auto_promote, watch-list/add) 신규개발 0으로 노출.
- **선행 부채(별도)**: (1) KR 포지션 소스=브로커 balance 단일화 확정, (2) 서버 Watchlist SQLite 영속, (3) Watchlist 가격 리프라이싱, (4) 자율 실행 후 워치항목 CONVERTED 정리.
- **즉시 제거 가능 죽은 위젯**: AgentWorkflowGraph, startAgentChatDiscussion, setBasketUpdating, 레거시 포지션 패널.
