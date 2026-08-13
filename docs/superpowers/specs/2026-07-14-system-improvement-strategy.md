# 시스템 개선 전략 계획 (2026-07-14)

2트랙 멀티에이전트 감사 종합 — 트랙1(사용자 지목 5이슈, 5건 CONFIRMED) + 트랙2(능동 발굴 5차원, CRITICAL 1 포함). 각 항목 발견→반박검증.

## 핵심 통찰

1. **한 줄이 이슈 2개를 죽인다**: `kiwoomSessionHandlers.ts onComplete`가 백엔드가 이미 보내는 `analysis_results`를 버리고 `completeKiwoomSession`(호출자 0)을 안 부름 → 분석 상세 공백(③) + 새로고침 상세 유실(①) 동시 해결. **최고 ROI, 공수 S.**
2. **가장 비싼 자산이 가장 좁은 깔때기에 물림**: 멀티에이전트 딥분석(펀더+감성+기술)은 깊은데 입력이 100% 수동. 발굴 계층 부재가 "자율 매매" 제품 정체성의 최대 공백(⑤).
3. **"수익률 담보"가 UI에서 불가시 + 구조적으로 0**: 실현 P&L·성과 뷰 부재(TUX4) + coordinator current_price 원가 고정으로 미실현 P&L 영구 0(DI2). 아크의 핵심 딜리버러블이 이중으로 안 보임.
4. **무음 랜덤-목 폴백이 방어까지 오염**(DI1, CRITICAL): 시세 API 실패 시 랜덤 가격을 분석·HITL·투표·**보유 포지션 손절 판정**에 무플래그 주입. 일시적 키움 오류가 조작된 손절 매도를 유발 가능.

---

## 통합 로드맵

### P0 — 즉시 (퀵윈 + 안전, 이번 배치)
| # | 문제 | 수정 방향 | 공수 | 파일 |
|---|---|---|---|---|
| P0-1 | 분석 상세 공백(③)+새로고침 유실(①) | onComplete→`completeKiwoomSession(analysisResults/tradeProposal/reasoningSummary)` (cancelled/error 가드) | S | kiwoomSessionHandlers.ts:114, store:1168 |
| P0-2 | **DI1 CRITICAL 랜덤-목 폴백** | 시세 실패 시 raise/None+stale 센티넬; 목은 KIWOOM_IS_MOCK 명시 플래그 뒤로만. 소비자(분석·PM 방어·투표)는 stale 시 결정·방어 스킵 | M | agents/tools/kr_market_data.py:68-161, position_manager.py:482 |
| P0-3 | Autonomous 토글 데드엔드(④) | `disabled`에서 `!masterEnabled` 제거+".env AUTONOMY_ENABLED 필요·인앱 불가" 안내행. Armed 배지는 masterEnabled 유지 | S | TradingModeSection.tsx:51 |
| P0-4 | WatchlistPanel KR 고정가(②일부) | KR 조기 return 제거, stock_info 단건 임시 봉합(완전판 P1 배치REST) | S | WatchlistPanel |

### P1 — 이번 주
| # | 문제 | 수정 방향 | 공수 |
|---|---|---|---|
| P1-1 | **성과 가시화 + DI2 리프라이싱**(복합·"수익률 담보" 딜리버러블) | 실현/누적수익·승률·일별곡선 패널(paper_performance/get_realized_pnl 노출) + coordinator `_state.positions[].current_price` 매 사이클 재가격(미실현 0 근본) | M-L |
| P1-2 | **M1 손절 엔진 전역정지**(C2 최대 차단) | 급등락 시 종목별 pause+N틱/안정화 자동복구(현재 전 종목 정지+사람 RESUME만). M4 무테스트 동반 | M |
| P1-3 | 인앱 관제/알림 센터(TUX5+OBS1+OBS4) | Bell→InlineTradeNotifications 배선+store 영속, activity_log persist+렌더, 루프 생존 배지(죽은 스케줄러가 "active" 표시 방지) | M |
| P1-4 | 재량 통제면(TUX1/2/3) | 수동 :buy/:sell 커맨드 + SL/TP 인라인 편집 + 부분청산 — 기존 0소비자 엔드포인트에 UI만 배선 (**신규 write 경로 인증 확인 필수**) | M |
| P1-5 | 스캐너 데드엔드 봉합(⑤ 선행) | 스캔 완료 시 임계 이상 BUY/WATCH를 서버 watch-list로 자동 승격→agent-chat 모니터·큐가 픽업. 디스커버리 아크의 값싼 선불 | M |
| P1-6 | 재시작 상세 복구 + coin 새로고침 | status 엔드포인트 sm 폴백(state_json.analyses 서빙) + rehydrateCoinSessions | M |
| P1-7 | KR 가격 노후도(②) 배치 완화 | getKRStockTickers 배치 REST 신설→관심/포지션/Operations 폴 정합 | M |

### P2 — 구조 아크
| # | 문제 | 수정 방향 | 공수 |
|---|---|---|---|
| P2-1 | **디스커버리 레이어**(⑤, 최대 레버리지) | 개장 전 스케줄드 스크리너: 딥그래프의 펀더멘털/감성 코어 재사용+매크로/섹터 레짐으로 유니버스 랭킹→후보 스테이징→top-N 딥분석→watch-list/큐 | XL |
| P2-2 | 퍼널 통합(디스커버리 동반) | 서버 watch-list=단일 출처, 클라 basket→"Scratchpad" 리네임, 명칭충돌 제거 | L |
| P2-3 | KR 실시간 WS(②) | DORMANT `KiwoomWebSocketClient`를 Upbit realtime_service 패턴으로 배선(0B체결/0C호가 fan-out). **선행: 키움 mock push 지원 검증**(미지원이면 P1-7 배치REST로 확정) | L |
| P2-4 | **페이퍼 체결 사실성**(블라인드 스팟·"수익률 담보" 신뢰 급소) | 모의 체결이 마지막가 완전체결 가정하는지 검증→슬리피지·수수료·부분체결·큐위치 반영(낙관 체결이면 검증 수익률 자체가 부풀려짐) | L |

### 정리 배치 (신뢰-부채, 저비용)
- 죽은 코드 삭제: 모바일 nav no-op·Sidebar/MarketTabs 레거시·/trading/agents·parallel_analysis.py·죽은 FE 헬퍼(AgentWorkflowGraph/AgentStatusWidget/StrategyConfigWidget). **effort S 배치**

---

## 블라인드 스팟 (감사가 스스로 지목 — 별도 조사 필요)
- **페이퍼 체결 사실성**(P2-4로 승격) — 아크 정면 사각
- **방어 경로 LLM 지연**: 손절 히트가 수초~수분 agent-chat 토론 트리거(D2 런북 기지) — 급락 속도 대비 방어 레이턴시 미검토
- **신규 write 엔드포인트 인증**: 수동 주문·SL/TP·리스크 파라미터 배선 시 인가 확인
- **3루프 동시성/멱등성**: scheduler·monitor·reconciler가 `_state.positions` 동시 변이+SQLite blob — 이중발주 방지 미검토

## C2 자율 실증 전 필수 (재확인)
- P0-2(랜덤-목 폴백), P1-2(손절 전역정지), P2-4(체결 사실성 — 수익률 신뢰), 방어 LLM 지연 — 무인 운용에서 조작·정지·부풀림을 유발. F4b 기지 백로그(execution.py:486 부분체결 오라벨 등)와 함께.

## 의존성·시퀀싱
- **독립 퀵윈**: P0-1(onComplete)·P0-3(토글) — 프론트 단독, 백엔드 이미 지원.
- P0-1 → P1-6(status 폴백)은 내구성 보완재로 강등.
- P1-7(배치REST) → P0-4·②완전판 선행.
- P1-5(스캐너 승격) = P2-1(디스커버리) 값싼 선불.
- P2-2(통합) → P2-1(디스커버리) 선행(단일 출처 확정 후 헤드 부착).
- P2-3(실시간 WS)는 mock push 검증에 블록 — 실패 대비 P1-7 무조건 먼저.

**한 줄 권고**: P0 배치(onComplete + 랜덤-목 봉쇄 + 토글)부터 — 최고 체감·최고 위험을 최소 비용으로. 그다음 "수익률 담보 가시화"(P1-1)로 아크 딜리버러블을 세우고, 구조는 통합→디스커버리 순.
