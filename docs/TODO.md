# Development TodoList - Coin Trading Feature

> Last Updated: 2025-12-19
> Focus: Upbit API 기반 암호화폐 트레이딩 모듈

---

## Priority Legend
- **P0**: Critical - Must have for feature launch
- **P1**: High - Important for user experience
- **P2**: Medium - Nice to have

---

## Current Focus: Coin Trading Module

> 상세 명세: [FEATURE_SPEC_COIN_TRADING.md](FEATURE_SPEC_COIN_TRADING.md)

---

## Phase 1: Market Data Integration [P0] ✅ COMPLETED

### Backend - Upbit API Client
- [x] `services/upbit/client.py` - Upbit API 클라이언트 구현
- [x] `services/upbit/auth.py` - JWT 인증 모듈
- [x] `services/upbit/models.py` - Pydantic 모델 정의
  - [x] `get_markets()` - 마켓 코드 조회
  - [x] `get_ticker()` - 현재가 조회
  - [x] `get_candles_minutes()` - 분봉 조회
  - [x] `get_candles_days()` - 일봉 조회
  - [x] `get_orderbook()` - 호가 조회
  - [x] `get_trades()` - 체결 내역 조회

### Backend - API Routes
- [x] `app/api/routes/coin.py` - 코인 분석 라우트
  - [x] `POST /api/coin/analysis/start` - 분석 시작
  - [x] `GET /api/coin/markets` - 마켓 목록
  - [x] `GET /api/coin/ticker/{market}` - 현재가
  - [x] `GET /api/coin/candles/{market}` - 캔들 데이터
  - [x] `GET /api/coin/orderbook/{market}` - 호가 조회
  - [x] `POST /api/coin/markets/search` - 마켓 검색

### Frontend - Tab Navigation
- [x] `components/layout/MarketTabs.tsx` - 증권/코인 탭 컴포넌트
- [x] Store에 `activeMarket` 상태 추가
- [x] Sidebar에서 탭 기반 입력 컴포넌트 전환

### Frontend - Coin Input
- [x] `components/coin/CoinTickerInput.tsx` - 코인 검색/선택
- [x] 마켓 자동완성 드롭다운
- [x] 한글/영문 검색 지원
- [x] 인기 코인 빠른 선택

---

## Phase 2: Analysis Pipeline [P0] ✅ MOSTLY COMPLETED

### LangGraph - Coin Trading Graph
- [x] `agents/graph/coin_trading_graph.py` - 코인 분석 워크플로우
- [x] `agents/graph/coin_nodes.py` - 코인 전용 노드
- [x] `agents/graph/coin_state.py` - 코인 상태 정의

### Agent Modifications
- [x] Technical Agent - 크립토 지표 추가
  - [x] 24시간 거래량/변동률
  - [x] 호가 불균형 분석 (bid/ask ratio)
  - [x] RSI, 트렌드 분석
- [x] Market Agent - 시장 분석 (Fundamental 대체)
  - [x] 24h 거래량 분석
  - [x] BTC 상관관계 고려
- [x] Sentiment Agent - 크립토 소스 추가
  - [x] 일반 감성 분석 프롬프트
  - [ ] Crypto Twitter 감성 (외부 API 필요)
  - [ ] Fear & Greed Index (외부 API 필요)
- [x] Risk Agent - 크립토 리스크 요소
  - [x] 24시간 변동성 기반 리스크 점수
  - [x] 보수적 포지션 사이징 (3-5%)
  - [x] 넓은 스탑로스 (8-12%)

### WebSocket Integration (Phase 4로 이동)
- [ ] `services/upbit/websocket.py` - 실시간 시세 스트리밍
- [ ] Frontend WebSocket 연결 (코인 전용)
- [ ] 실시간 가격 업데이트 UI

---

## Phase 3: Trading Execution [P1] (1-2 weeks)

### Backend - Exchange API
- [ ] `services/upbit/exchange.py` - 거래 메서드
  - [ ] `get_accounts()` - 잔고 조회
  - [ ] `place_order()` - 주문 생성 (지정가/시장가)
  - [ ] `cancel_order()` - 주문 취소
  - [ ] `get_order()` - 주문 조회
  - [ ] `get_orders()` - 주문 목록

### HITL Integration
- [ ] Approval API 코인 지원 수정
- [ ] 코인 Trade Proposal 표시
- [ ] 주문 실행 연동

### Order Monitoring
- [ ] 주문 상태 추적
- [ ] 체결 알림
- [ ] 미체결 주문 관리

---

## Phase 4: UI/UX Polish [P1] (1 week)

### Components
- [ ] `CoinChart.tsx` - 코인 차트 (TradingView)
- [ ] `CoinPosition.tsx` - 코인 포지션 카드
- [ ] `CoinProposal.tsx` - 코인 거래 제안
- [ ] `CoinHistory.tsx` - 코인 분석 히스토리

### Real-time Updates
- [ ] 실시간 가격 표시
- [ ] P&L 계산 및 표시
- [ ] 호가창 시각화

### Responsive Design
- [ ] 모바일 탭 네비게이션
- [ ] 코인 UI 반응형 검증

---

## Environment Setup

### Required Environment Variables
```env
# Upbit API Keys (Phase 3에서 필요)
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key
UPBIT_TRADING_MODE=paper  # paper | live
```

### Dependencies to Add
```
# backend/requirements.txt
httpx>=0.25.0
PyJWT>=2.8.0
```

---

## Upbit API Quick Reference

### Rate Limits
| Type | Per Second | Per Minute |
|------|------------|------------|
| 주문 API | 8회 | 200회 |
| 기타 API | 30회 | 900회 |

### Market Code Format
- KRW 마켓: `KRW-BTC`, `KRW-ETH`
- BTC 마켓: `BTC-ETH`, `BTC-XRP`
- USDT 마켓: `USDT-BTC`

### Key Endpoints
| Endpoint | Auth | Description |
|----------|------|-------------|
| `/v1/market/all` | No | 마켓 목록 |
| `/v1/ticker` | No | 현재가 |
| `/v1/candles/*` | No | 캔들 데이터 |
| `/v1/orderbook` | No | 호가 |
| `/v1/accounts` | Yes | 잔고 조회 |
| `/v1/orders` | Yes | 주문 생성/조회 |

---

## Related Documents

- [Coin Trading Feature Spec](FEATURE_SPEC_COIN_TRADING.md)
- [Stock Features Archive](archive/TODO_STOCK_FEATURES.md)
- [Real-Time Agent Trading Spec](FEATURE_SPEC_REALTIME_AGENT_TRADING.md)

---

## Notes

- Phase 1-2는 인증 없이 QUOTATION API만 사용
- Phase 3부터 Upbit API 키 필요
- `paper` 모드에서 먼저 테스트 후 `live` 전환
