# Development TodoList - Trading Features

> Last Updated: 2025-12-29
> Focus: Coin Trading (Upbit) & Korea Stock Trading (Kiwoom)

---

## Priority Legend
- **P0**: Critical - Must have for feature launch
- **P1**: High - Important for user experience
- **P2**: Medium - Nice to have

---

## Progress Overview

| Phase | Coin (Upbit) | Korea Stock (Kiwoom) |
|-------|--------------|----------------------|
| Phase 1: Market Data | ✅ Complete | ✅ Complete |
| Phase 2: Analysis Pipeline | ✅ Complete | ✅ Complete |
| Phase 2.5: Real-time & Multi-Session | ✅ Complete | ✅ Complete |
| Phase 3: Trading Execution | ✅ Complete | ✅ Complete |
| Phase 4: UI/UX Polish | ✅ Mostly Complete | ✅ Mostly Complete |
| Phase 5: Advanced Features | ⏳ Future | ⏳ Future |

---

## Phase 1: Market Data Integration [P0] ✅ COMPLETED

### Coin (Upbit)

#### Backend - Upbit API Client
- [x] `services/upbit/client.py` - Upbit API 클라이언트 구현
- [x] `services/upbit/auth.py` - JWT 인증 모듈
- [x] `services/upbit/models.py` - Pydantic 모델 정의
  - [x] `get_markets()` - 마켓 코드 조회
  - [x] `get_ticker()` - 현재가 조회
  - [x] `get_candles_minutes()` - 분봉 조회
  - [x] `get_candles_days()` - 일봉 조회
  - [x] `get_candles_seconds()` - 초봉 조회
  - [x] `get_orderbook()` - 호가 조회
  - [x] `get_trades()` - 체결 내역 조회

#### Backend - API Routes
- [x] `app/api/routes/coin.py` - 코인 분석 라우트
  - [x] `POST /api/coin/analysis/start` - 분석 시작
  - [x] `GET /api/coin/markets` - 마켓 목록
  - [x] `GET /api/coin/ticker/{market}` - 현재가 (단일)
  - [x] `GET /api/coin/tickers` - 현재가 (배치)
  - [x] `GET /api/coin/candles/{market}` - 캔들 데이터
  - [x] `GET /api/coin/orderbook/{market}` - 호가 조회
  - [x] `POST /api/coin/markets/search` - 마켓 검색

#### Frontend - Coin Input
- [x] `components/coin/CoinTickerInput.tsx` - 코인 검색/선택
- [x] 마켓 자동완성 드롭다운
- [x] 한글/영문 검색 지원
- [x] 인기 코인 빠른 선택

### Korea Stock (Kiwoom)

#### Backend - Kiwoom API Client
- [x] `services/kiwoom/client.py` - Kiwoom API 클라이언트 구현
- [x] `services/kiwoom/auth.py` - OAuth 인증 모듈
- [x] `services/kiwoom/models.py` - Pydantic 모델 정의
  - [x] `get_stock_info()` - 종목 기본정보 조회
  - [x] `get_daily_chart()` - 일봉 조회
  - [x] `get_orderbook()` - 호가 조회
  - [x] `get_cash_balance()` - 예수금 조회
  - [x] `get_account_balance()` - 잔고 조회
- [x] `services/kiwoom/rate_limiter.py` - Rate Limit 관리
- [x] `services/kiwoom/cache.py` - 캐시 관리
- [x] `services/kiwoom/websocket.py` - 실시간 스트리밍

#### Backend - API Routes
- [x] `app/api/routes/kr_stocks.py` - 한국주식 라우트
  - [x] `GET /api/kr-stocks/stocks` - 인기 종목 목록
  - [x] `POST /api/kr-stocks/stocks/search` - 종목 검색
  - [x] `GET /api/kr-stocks/ticker/{stk_cd}` - 현재가
  - [x] `GET /api/kr-stocks/candles/{stk_cd}` - 캔들 데이터
  - [x] `GET /api/kr-stocks/orderbook/{stk_cd}` - 호가 조회
  - [x] `POST /api/kr-stocks/analysis/start` - 분석 시작

#### Frontend - Kiwoom Input
- [x] `components/kiwoom/KiwoomTickerInput.tsx` - 종목 검색/선택
- [x] 종목 자동완성 드롭다운
- [x] 한글 종목명 검색 지원
- [x] 인기 종목 빠른 선택

### Common
- [x] `components/layout/MarketTabs.tsx` - 마켓 탭 컴포넌트 (Stock/Coin/Korea)
- [x] Store에 `activeMarket` 상태 추가
- [x] Sidebar에서 탭 기반 입력 컴포넌트 전환

---

## Phase 2: Analysis Pipeline [P0] ✅ COMPLETED

### Coin (Upbit)

#### LangGraph - Coin Trading Graph
- [x] `agents/graph/coin_trading_graph.py` - 코인 분석 워크플로우
- [x] `agents/graph/coin_nodes.py` - 코인 전용 노드
- [x] `agents/graph/coin_state.py` - 코인 상태 정의

#### Agent Modifications
- [x] Technical Agent - 크립토 지표 추가
  - [x] 24시간 거래량/변동률
  - [x] 호가 불균형 분석 (bid/ask ratio)
  - [x] RSI, 트렌드 분석
- [x] Market Agent - 시장 분석 (Fundamental 대체)
  - [x] 24h 거래량 분석
  - [x] BTC 상관관계 고려
- [x] Sentiment Agent - 크립토 소스 추가
  - [x] 일반 감성 분석 프롬프트
  - [ ] Crypto Twitter 감성 (외부 API 필요) - P2
  - [ ] Fear & Greed Index (외부 API 필요) - P2
- [x] Risk Agent - 크립토 리스크 요소
  - [x] 24시간 변동성 기반 리스크 점수
  - [x] 보수적 포지션 사이징 (3-5%)
  - [x] 넓은 스탑로스 (8-12%)

### Korea Stock (Kiwoom)

#### LangGraph - Korea Stock Trading Graph
- [x] `agents/graph/kr_stock_graph.py` - 한국주식 분석 워크플로우
- [x] `agents/graph/kr_stock_nodes.py` - 한국주식 전용 노드
- [x] `agents/graph/kr_stock_state.py` - 한국주식 상태 정의

#### Agent Modifications
- [x] Technical Agent - 한국주식 지표
  - [x] PER/PBR/EPS/BPS 분석
  - [x] 거래량/거래대금 분석
  - [x] 이동평균, RSI 등
- [x] Fundamental Agent - 재무분석
  - [x] 한국 재무제표 기반 분석
- [x] Sentiment Agent - 시장 심리
  - [x] 한국어 뉴스 감성분석
- [x] Risk Agent - 리스크 평가
  - [x] 변동성 기반 리스크 점수
  - [x] 포지션 사이징 계산

---

## Phase 2.5: Real-time & Multi-Session [P0] ✅ COMPLETED

### Coin (Upbit)

#### Upbit WebSocket Client
- [x] `services/upbit/websocket.py` - 실시간 데이터 스트리밍
  - [x] Ticker 스트리밍 (현재가)
  - [x] Trade 스트리밍 (체결)
  - [x] Orderbook 스트리밍 (호가)
  - [x] Auto-reconnect with exponential backoff
  - [x] Callback 기반 데이터 전달

#### WebSocket Integration
- [x] `app/api/routes/websocket.py` - 코인 WebSocket 라우트
- [x] `frontend/src/api/websocket.ts` - 코인 WebSocket 클라이언트
- [x] `frontend/src/hooks/useCoinTicker.ts` - 실시간 티커 훅

#### Rate Limit Optimization
- [x] 배치 Ticker API 추가 (`GET /api/coin/tickers`)
- [x] `CoinMarketList.tsx` 배치 API 사용으로 변경
- [x] 429 Too Many Requests 에러 해결

### Korea Stock (Kiwoom)

#### Backend - Concurrency Control
- [x] `app/core/analysis_limiter.py` - 동시 분석 제어
  - [x] Semaphore 기반 동시 실행 제한 (MAX=3)
  - [x] 세션 정리 메커니즘
- [x] WebSocket 메시지에 `session_id` 포함
- [x] Rate Limit 429 에러 처리 (재시도 로직)

#### Frontend - Multi-Session Support
- [x] Store sessions 배열 구조 (`kiwoom.sessions[]`)
- [x] 세션별 독립적 상태 관리
- [x] `WebSocketManager` 클래스 (다중 연결)
- [x] `useMultipleAnalysisWebSockets` 훅

### Common
- [x] BasketWidget에서 다중 종목 분석 시작
- [x] API 호출 + WebSocket 연결
- [x] 동시 분석 수 제한 표시 (3개)

---

## Phase 3: Trading Execution [P1] ✅ COMPLETED

### Coin (Upbit)

#### Backend - Exchange API ✅
- [x] `services/upbit/client.py` - 기본 구현 완료
  - [x] `get_accounts()` - 잔고 조회
  - [x] `place_order()` - 주문 생성 (지정가/시장가)
  - [x] `cancel_order()` - 주문 취소
  - [x] `get_order()` - 주문 조회
  - [x] `get_orders()` - 주문 목록

#### Backend - API Routes ✅
- [x] `GET /api/coin/accounts` - 계좌 잔고 조회
- [x] `GET /api/coin/orders` - 주문 목록 조회
- [x] `POST /api/coin/orders` - 주문 생성
- [x] `DELETE /api/coin/orders/{uuid}` - 주문 취소
- [x] `GET /api/coin/positions` - 포지션 조회
- [x] `POST /api/coin/positions/{market}/close` - 포지션 청산
- [x] `GET /api/coin/trades` - 거래 내역 조회

#### HITL Integration ✅
- [x] Approval API 코인 지원 (`/api/approval/decide`)
- [x] 코인 Trade Proposal 생성 (수량 자동 계산)
- [x] 승인 후 자동 주문 실행 (`coin_execution_node`)

#### Order Monitoring (Phase 4/5로 이동)
- [ ] 주문 상태 추적 실시간 UI
- [ ] 체결 알림
- [ ] 미체결 주문 관리

### Korea Stock (Kiwoom)

#### Backend - Exchange API ✅
- [x] `services/kiwoom/client.py` - 주문 기능 구현
  - [x] `place_order()` - 주문 생성 (지정가/시장가)
  - [x] `cancel_order()` - 주문 취소
  - [x] `get_pending_orders()` - 미체결 주문 조회

#### Backend - API Routes ✅
- [x] `GET /api/kr-stocks/accounts` - 계좌 잔고 조회
- [x] `GET /api/kr-stocks/orders` - 주문 목록 조회
- [x] `POST /api/kr-stocks/orders` - 주문 생성
- [x] `DELETE /api/kr-stocks/orders/{order_id}` - 주문 취소
- [x] `GET /api/kr-stocks/positions` - 포지션 조회
- [x] `POST /api/kr-stocks/positions/{stk_cd}/close` - 포지션 청산
- [x] `GET /api/kr-stocks/trades` - 거래 내역 조회

#### HITL Integration ✅
- [x] Trade Proposal 생성 (KRStockTradeProposal, 수량 자동 계산)
- [x] 원화(₩) 통화 표시 수정
- [x] Approval API 한국주식 지원 (`/api/approval/decide`)
- [x] 승인 후 자동 주문 실행 (`kr_stock_execution_node`)

#### Order Monitoring (Phase 4/5로 이동)
- [ ] 주문 상태 WebSocket 스트리밍
- [ ] 체결 알림 UI
- [ ] 미체결 주문 관리 UI

---

## Phase 4: UI/UX Polish [P1] ✅ MOSTLY COMPLETE

### Coin (Upbit)

#### Components ✅
- [x] `CoinPriceTicker.tsx` - 실시간 가격 티커
- [x] `CoinInfo.tsx` - 코인 상세 정보
- [x] `CoinMarketList.tsx` - 마켓 리스트
- [x] `CoinChart.tsx` - 코인 차트 (간단 버전)
- [x] `CoinPositionPanel.tsx` - 코인 포지션 패널 (P&L, 청산)
- [x] `CoinOpenOrders.tsx` - 코인 미체결 주문
- [x] `CoinTradeHistory.tsx` - 코인 거래 내역
- [x] `CoinAccountBalance.tsx` - 코인 계좌 잔고
- [x] `ApprovalDialog.tsx` - 거래 제안 승인/거절 (통합)

#### Real-time Updates
- [x] 실시간 가격 표시
- [x] P&L 계산 및 표시 (CoinPositionPanel)
- [ ] 호가창 시각화 (Phase 5)

### Korea Stock (Kiwoom)

#### Components ✅
- [x] `KiwoomTickerInput.tsx` - 종목 검색
- [x] `KRStockPriceTicker.tsx` - 실시간 가격 티커
- [x] `KiwoomAccountBalance.tsx` - 계좌 잔고
- [x] `KiwoomPositionPanel.tsx` - 포지션 패널 (P&L, 청산)
- [x] `KiwoomOpenOrders.tsx` - 미체결 주문
- [x] `KRStockTradeHistory.tsx` - 거래 내역
- [x] `ApprovalDialog.tsx` - 거래 제안 승인/거절 (통합)

#### Trade Execution UI ✅
- [x] `ApprovalDialog.tsx` - 주문 확인 모달 (approve/reject/cancel)
- [x] `TradesPage.tsx` - 주문 히스토리 페이지 (Coin + Kiwoom)

#### Position Management ✅
- [x] 포지션 API 연동 (`GET /positions`)
- [x] 포지션 P&L 실시간 업데이트 (10초 polling)
- [x] 스탑로스/테이크프로핏 표시 (수정 UI: Phase 5)
- [x] 포지션 청산 UI (KiwoomPositionPanel, CoinPositionPanel)

### Pages ✅
- [x] `BasketPage.tsx` - My Basket 전체 페이지
- [x] `HistoryPage.tsx` - 분석 기록 페이지 (필터링, 검색)
- [x] `PositionsPage.tsx` - 포지션 전체 페이지
- [x] `ChartsPage.tsx` - 차트 페이지
- [x] `TradesPage.tsx` - 거래 내역 페이지

### Common (Phase 5로 이동)
- [ ] 모바일 UI 최적화
- [ ] 태블릿 레이아웃
- [ ] 반응형 검증

---

## Phase 5: Advanced Features [P2] (Future)

### Real-time Monitoring (Both Markets)
- [ ] 실시간 체결 알림 (WebSocket)
- [ ] 가격 알림 설정
- [ ] 목표가 도달 알림

### Strategy & Automation (Both Markets)
- [ ] 자동매매 스케줄러
- [ ] 조건부 주문 (conditional orders)
- [ ] 포트폴리오 리밸런싱

### Analytics (Both Markets)
- [ ] 거래 성과 분석
- [ ] 승률/손익비 통계
- [ ] 월간 리포트

### External Integrations
- [ ] Crypto Twitter 감성 분석
- [ ] Fear & Greed Index 연동
- [ ] 뉴스 API 연동

---

## Bug Fixes (Completed)

### Coin Trading
- [x] JWT encode 에러 수정 (`jwt` → `PyJWT` 패키지)
- [x] MinuteCandle duplicate 'unit' keyword argument 에러 수정
- [x] 429 Rate Limit 에러 수정 (배치 API 도입)
- [x] WebSocket 연결 안정화
- [x] Trade Proposal quantity=0 버그 수정 (KRW 잔고 기반 자동 계산)

### Korea Stock Trading
- [x] Trade Proposal 원화(₩) 표시 수정 ($ → ₩)
- [x] `createStoreWebSocket`에 `marketType` 파라미터 추가
- [x] 429 Rate Limit 재시도 로직 추가 (3회 retry, exponential backoff)
- [x] Trade Proposal quantity=0 버그 수정 (주문가능금액 기반 자동 계산)

### General
- [x] 페이지 네비게이션 시 세션 사라짐 버그 수정
- [x] `startKiwoomSession`에서 `sessions` 배열 보존
- [x] RecentAnalysisWidget에 cancelled 상태 포함

---

## Environment Setup

### Required Environment Variables
```env
# Upbit API Keys (Coin Trading - Phase 3)
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key
UPBIT_TRADING_MODE=paper  # paper | live

# Kiwoom (KIS) API Keys (Korea Stock - Phase 3)
KIWOOM_APP_KEY=your_app_key
KIWOOM_APP_SECRET=your_app_secret
KIWOOM_ACCOUNT_NUMBER=your_account_number
KIWOOM_IS_MOCK=true  # true: 모의투자, false: 실거래
```

### Dependencies
```
# backend/requirements.txt
httpx>=0.25.0
PyJWT>=2.8.0
websockets>=12.0
```

---

## API Quick Reference

### Upbit (Coin)

#### Rate Limits
| Type | Per Second | Per Minute |
|------|------------|------------|
| 주문 API | 8회 | 200회 |
| 기타 API (ticker) | 10회 | - |
| WebSocket 메시지 | 5회 | 100회 |

#### Market Code Format
- KRW 마켓: `KRW-BTC`, `KRW-ETH`
- BTC 마켓: `BTC-ETH`, `BTC-XRP`
- USDT 마켓: `USDT-BTC`

#### Key Endpoints
| Endpoint | Auth | Description |
|----------|------|-------------|
| `/v1/market/all` | No | 마켓 목록 |
| `/v1/ticker` | No | 현재가 (배치 지원) |
| `/v1/candles/*` | No | 캔들 데이터 |
| `/v1/orderbook` | No | 호가 |
| `/v1/accounts` | Yes | 잔고 조회 |
| `/v1/orders` | Yes | 주문 생성/조회 |

### Kiwoom (Korea Stock)

#### Rate Limits
| Type | Per Second | Per Minute |
|------|------------|------------|
| 조회 API | 5회 | - |
| 주문 API | 5회 | - |
| 실시간 WebSocket | 제한 없음 | - |

#### Stock Code Format
- KOSPI: 6자리 숫자 (예: `005930` 삼성전자)
- KOSDAQ: 6자리 숫자 (예: `247540` 에코프로비엠)

#### Key Endpoints (Internal API Routes)
| Endpoint | Auth | Description |
|----------|------|-------------|
| `/api/kr-stocks/stocks` | No | 인기 종목 목록 |
| `/api/kr-stocks/stocks/search` | No | 종목 검색 |
| `/api/kr-stocks/ticker/{stk_cd}` | No | 현재가 |
| `/api/kr-stocks/candles/{stk_cd}` | No | 캔들 데이터 |
| `/api/kr-stocks/accounts` | Yes | 계좌 잔고 |
| `/api/kr-stocks/orders` | Yes | 주문 생성/조회 |
| `/api/kr-stocks/positions` | Yes | 포지션 조회 |

---

## Related Documents

- [Coin Trading Feature Spec](FEATURE_SPEC_COIN_TRADING.md)
- [Stock Features Archive](archive/TODO_STOCK_FEATURES.md)
- [Real-Time Agent Trading Spec](FEATURE_SPEC_REALTIME_AGENT_TRADING.md)

---

## Notes

- Phase 1-2는 인증 없이 시세 조회 API만 사용
- Phase 2.5에서 실시간 데이터 및 다중 세션 완성
- Phase 3부터 거래소 API 키 필요 (Upbit/KIS)
- 모의투자 모드에서 먼저 테스트 후 실거래 전환
