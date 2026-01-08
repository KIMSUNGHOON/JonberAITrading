# Feature Specification: Cryptocurrency (Coin) Trading Module

## 1. Executive Summary

이 문서는 **Upbit API 기반 암호화폐 트레이딩 모듈**의 기능 명세서 및 아키텍처를 정의합니다.
기존 증권 분석 시스템과 동일한 워크플로우(Multi-Agent 분석 → HITL 승인 → 실행)를 암호화폐에 적용합니다.

---

## 2. Feature Overview

### 2.1 Goals
- Upbit 거래소 API 연동을 통한 암호화폐 분석 및 트레이딩
- 증권/코인 탭 기반 UI로 통합된 사용자 경험 제공
- 기존 에이전트 아키텍처 재사용 (Technical, Fundamental, Sentiment, Risk)

### 2.2 Scope
- **Phase 1**: 시세 조회 및 분석 (QUOTATION API)
- **Phase 2**: 주문 실행 (EXCHANGE API with 인증)
- **Phase 3**: 실시간 모니터링 (WebSocket)

---

## 3. Upbit API Reference

### 3.1 API Categories

| Category | Authentication | Description |
|----------|---------------|-------------|
| **QUOTATION API** | 불필요 | 시세, 캔들, 호가, 체결 데이터 |
| **EXCHANGE API** | JWT 필요 | 자산, 주문, 출금 |
| **WebSocket API** | 불필요 | 실시간 시세 스트리밍 |

### 3.2 QUOTATION API Endpoints

```
Market Data (인증 불필요)
├── GET /v1/market/all              # 마켓 코드 조회
├── GET /v1/candles/minutes/{unit}  # 분봉 (1, 3, 5, 10, 30, 60분)
├── GET /v1/candles/days            # 일봉
├── GET /v1/candles/weeks           # 주봉
├── GET /v1/candles/months          # 월봉
├── GET /v1/ticker                  # 현재가 정보
├── GET /v1/orderbook               # 호가 정보
└── GET /v1/trades/ticks            # 최근 체결 내역
```

### 3.3 EXCHANGE API Endpoints

```
Account & Orders (JWT 인증 필요)
├── GET  /v1/accounts               # 전체 계좌 조회
├── GET  /v1/orders/chance          # 주문 가능 정보
├── GET  /v1/order                  # 개별 주문 조회
├── GET  /v1/orders                 # 주문 리스트 조회
├── POST /v1/orders                 # 주문하기
├── DELETE /v1/order                # 주문 취소
└── GET  /v1/api_keys               # API 키 리스트 조회
```

### 3.4 Rate Limits

| Type | Per Second | Per Minute |
|------|------------|------------|
| 주문 API | 8회 | 200회 |
| 기타 API | 30회 | 900회 |

### 3.5 Authentication (JWT)

```python
import jwt
import uuid
import hashlib
from urllib.parse import urlencode

# JWT Payload 생성
payload = {
    'access_key': access_key,
    'nonce': str(uuid.uuid4()),
    'timestamp': round(time.time() * 1000)
}

# Query 파라미터가 있는 경우
if query:
    query_string = urlencode(query).encode()
    m = hashlib.sha512()
    m.update(query_string)
    payload['query_hash'] = m.hexdigest()
    payload['query_hash_alg'] = 'SHA512'

# JWT 토큰 생성
jwt_token = jwt.encode(payload, secret_key, algorithm='HS256')
authorization = f'Bearer {jwt_token}'
```

---

## 4. System Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Tab Navigation                            │    │
│  │   ┌──────────────┐         ┌──────────────┐                 │    │
│  │   │  증권 (Stock) │         │  코인 (Coin) │                 │    │
│  │   └──────────────┘         └──────────────┘                 │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  CoinAnalysis    │  CoinChart  │  CoinProposal │  CoinHistory │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────────┘
                             │ WebSocket / REST
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                             │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  Market Type Router                           │   │
│  │         /api/stock/*          │         /api/coin/*           │   │
│  └────────────┬──────────────────┴───────────────┬──────────────┘   │
│               │                                   │                  │
│  ┌────────────▼──────────────┐   ┌───────────────▼──────────────┐   │
│  │   Stock Analysis Service   │   │   Coin Analysis Service      │   │
│  │   (yfinance data)          │   │   (Upbit API data)           │   │
│  └────────────┬──────────────┘   └───────────────┬──────────────┘   │
│               │                                   │                  │
│  ┌────────────▼──────────────────────────────────▼──────────────┐   │
│  │                  Shared Agent Framework                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐          │   │
│  │  │Technical │ │Fundament.│ │Sentiment │ │  Risk   │          │   │
│  │  │ Agent    │ │ Agent    │ │ Agent    │ │ Agent   │          │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   LLM Server    │ │   Upbit API     │ │   yfinance      │
│  (Ollama/vLLM)  │ │  (Crypto Data)  │ │  (Stock Data)   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### 4.2 Data Flow

```
[User Input: Coin Ticker (e.g., KRW-BTC)]
         │
         ▼
┌─────────────────────────────────────────────┐
│           Upbit Data Provider               │
│  ┌─────────────────────────────────────┐   │
│  │  1. Get Market Info                  │   │
│  │  2. Fetch OHLCV Candles              │   │
│  │  3. Get Current Orderbook            │   │
│  │  4. Get Recent Trades                │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│        Technical Analysis Agent             │
│  - RSI, MACD, Bollinger Bands              │
│  - Support/Resistance Levels               │
│  - Volume Analysis (24h)                    │
│  - Trend Detection                          │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│        Crypto-Specific Analysis             │
│  - On-chain Metrics (optional)              │
│  - Exchange Inflow/Outflow                  │
│  - Funding Rate (Futures)                   │
│  - Social Sentiment (Crypto Twitter/Reddit) │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│           Risk Assessment Agent             │
│  - Volatility Analysis (24h, 7d)            │
│  - Liquidity Risk                           │
│  - Market Correlation (BTC Dominance)       │
│  - Position Sizing                          │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│           Trade Proposal                    │
│  - Action: BUY / SELL / HOLD               │
│  - Entry Price                              │
│  - Stop Loss / Take Profit                  │
│  - Position Size                            │
└─────────────────────────────────────────────┘
         │
         ▼
[HITL Approval] ──► [Order Execution via Upbit API]
```

---

## 5. Backend Implementation

### 5.1 New Directory Structure

```
backend/
├── app/
│   └── api/
│       └── routes/
│           ├── analysis.py       # Stock analysis (existing)
│           ├── coin_analysis.py  # NEW: Coin analysis
│           └── approval.py       # Shared approval (modify)
├── agents/
│   ├── graph/
│   │   ├── trading_graph.py      # Stock graph (existing)
│   │   └── coin_trading_graph.py # NEW: Coin graph
│   └── tools/
│       ├── market_data.py        # yfinance (existing)
│       └── upbit_data.py         # NEW: Upbit API wrapper
├── services/
│   ├── upbit/
│   │   ├── __init__.py
│   │   ├── client.py             # Upbit API client
│   │   ├── auth.py               # JWT authentication
│   │   ├── quotation.py          # Market data methods
│   │   ├── exchange.py           # Trading methods
│   │   └── websocket.py          # Real-time streaming
│   └── data_provider.py          # Unified data interface
└── models/
    └── coin.py                   # Coin-specific models
```

### 5.2 Upbit Client Implementation

```python
# backend/services/upbit/client.py

from typing import Optional, List
import httpx
from .auth import generate_jwt_token

class UpbitClient:
    """Upbit API Client with authentication support."""

    BASE_URL = "https://api.upbit.com/v1"

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0
        )

    # ============ QUOTATION API (No Auth) ============

    async def get_markets(self) -> List[dict]:
        """Get all available markets."""
        response = await self._client.get("/market/all")
        return response.json()

    async def get_ticker(self, markets: List[str]) -> List[dict]:
        """Get current ticker for markets."""
        params = {"markets": ",".join(markets)}
        response = await self._client.get("/ticker", params=params)
        return response.json()

    async def get_candles_minutes(
        self,
        market: str,
        unit: int = 1,
        count: int = 200,
        to: Optional[str] = None
    ) -> List[dict]:
        """Get minute candles."""
        params = {"market": market, "count": count}
        if to:
            params["to"] = to
        response = await self._client.get(
            f"/candles/minutes/{unit}",
            params=params
        )
        return response.json()

    async def get_candles_days(
        self,
        market: str,
        count: int = 200
    ) -> List[dict]:
        """Get daily candles."""
        params = {"market": market, "count": count}
        response = await self._client.get("/candles/days", params=params)
        return response.json()

    async def get_orderbook(self, markets: List[str]) -> List[dict]:
        """Get orderbook for markets."""
        params = {"markets": ",".join(markets)}
        response = await self._client.get("/orderbook", params=params)
        return response.json()

    async def get_trades(
        self,
        market: str,
        count: int = 100
    ) -> List[dict]:
        """Get recent trades."""
        params = {"market": market, "count": count}
        response = await self._client.get("/trades/ticks", params=params)
        return response.json()

    # ============ EXCHANGE API (Auth Required) ============

    async def get_accounts(self) -> List[dict]:
        """Get all account balances."""
        headers = self._auth_headers()
        response = await self._client.get("/accounts", headers=headers)
        return response.json()

    async def place_order(
        self,
        market: str,
        side: str,  # "bid" (buy) or "ask" (sell)
        volume: Optional[float] = None,
        price: Optional[float] = None,
        ord_type: str = "limit"  # "limit", "price", "market"
    ) -> dict:
        """Place a new order."""
        data = {
            "market": market,
            "side": side,
            "ord_type": ord_type
        }
        if volume:
            data["volume"] = str(volume)
        if price:
            data["price"] = str(price)

        headers = self._auth_headers(query=data)
        response = await self._client.post(
            "/orders",
            headers=headers,
            json=data
        )
        return response.json()

    async def cancel_order(self, uuid: str) -> dict:
        """Cancel an order."""
        params = {"uuid": uuid}
        headers = self._auth_headers(query=params)
        response = await self._client.delete(
            "/order",
            headers=headers,
            params=params
        )
        return response.json()

    async def get_order(self, uuid: str) -> dict:
        """Get order details."""
        params = {"uuid": uuid}
        headers = self._auth_headers(query=params)
        response = await self._client.get(
            "/order",
            headers=headers,
            params=params
        )
        return response.json()

    def _auth_headers(self, query: dict = None) -> dict:
        """Generate authorization headers with JWT."""
        if not self.access_key or not self.secret_key:
            raise ValueError("API keys required for authenticated requests")

        token = generate_jwt_token(
            self.access_key,
            self.secret_key,
            query
        )
        return {"Authorization": f"Bearer {token}"}
```

### 5.3 JWT Authentication

```python
# backend/services/upbit/auth.py

import jwt
import uuid
import time
import hashlib
from urllib.parse import urlencode
from typing import Optional

def generate_jwt_token(
    access_key: str,
    secret_key: str,
    query: Optional[dict] = None
) -> str:
    """Generate JWT token for Upbit API authentication."""

    payload = {
        "access_key": access_key,
        "nonce": str(uuid.uuid4()),
        "timestamp": round(time.time() * 1000)
    }

    if query:
        query_string = urlencode(query).encode()
        m = hashlib.sha512()
        m.update(query_string)
        payload["query_hash"] = m.hexdigest()
        payload["query_hash_alg"] = "SHA512"

    return jwt.encode(payload, secret_key, algorithm="HS256")
```

### 5.4 Coin Analysis API Routes

```python
# backend/app/api/routes/coin_analysis.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.upbit.client import UpbitClient
from agents.graph.coin_trading_graph import get_coin_trading_graph

router = APIRouter(prefix="/coin", tags=["coin"])

class CoinAnalysisRequest(BaseModel):
    market: str  # e.g., "KRW-BTC", "KRW-ETH"

class CoinAnalysisResponse(BaseModel):
    session_id: str
    market: str
    status: str
    message: str

@router.post("/analysis/start", response_model=CoinAnalysisResponse)
async def start_coin_analysis(request: CoinAnalysisRequest):
    """Start a new coin analysis session."""
    # Validate market format
    if not request.market.startswith(("KRW-", "BTC-", "USDT-")):
        raise HTTPException(
            status_code=400,
            detail="Invalid market format. Use KRW-BTC, BTC-ETH, etc."
        )

    # Initialize Upbit client (no auth for quotation)
    client = UpbitClient()

    # Verify market exists
    markets = await client.get_markets()
    valid_markets = [m["market"] for m in markets]
    if request.market not in valid_markets:
        raise HTTPException(
            status_code=404,
            detail=f"Market {request.market} not found"
        )

    # Start analysis graph
    graph = get_coin_trading_graph()
    # ... (similar to stock analysis)

@router.get("/markets")
async def list_coin_markets(fiat: str = "KRW"):
    """List available coin markets."""
    client = UpbitClient()
    markets = await client.get_markets()
    filtered = [m for m in markets if m["market"].startswith(f"{fiat}-")]
    return {"markets": filtered}

@router.get("/ticker/{market}")
async def get_coin_ticker(market: str):
    """Get current ticker for a coin."""
    client = UpbitClient()
    ticker = await client.get_ticker([market])
    return ticker[0] if ticker else None

@router.get("/candles/{market}")
async def get_coin_candles(
    market: str,
    interval: str = "day",
    count: int = 100
):
    """Get OHLCV candles for a coin."""
    client = UpbitClient()

    if interval == "day":
        candles = await client.get_candles_days(market, count)
    elif interval.endswith("m"):
        unit = int(interval[:-1])
        candles = await client.get_candles_minutes(market, unit, count)
    else:
        raise HTTPException(status_code=400, detail="Invalid interval")

    return {"candles": candles}
```

---

## 6. Frontend Implementation

### 6.1 Tab Navigation Component

```tsx
// frontend/src/components/layout/MarketTabs.tsx

import { useState } from 'react';
import { TrendingUp, Bitcoin } from 'lucide-react';
import { useStore } from '@/store';

type MarketType = 'stock' | 'coin';

export function MarketTabs() {
  const [activeMarket, setActiveMarket] = useStore((state) => [
    state.activeMarket,
    state.setActiveMarket,
  ]);

  return (
    <div className="flex border-b border-border">
      <TabButton
        active={activeMarket === 'stock'}
        onClick={() => setActiveMarket('stock')}
        icon={<TrendingUp className="w-4 h-4" />}
        label="증권 (Stock)"
      />
      <TabButton
        active={activeMarket === 'coin'}
        onClick={() => setActiveMarket('coin')}
        icon={<Bitcoin className="w-4 h-4" />}
        label="코인 (Coin)"
      />
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ active, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-6 py-3 font-medium transition-colors
        ${active
          ? 'text-blue-400 border-b-2 border-blue-400'
          : 'text-gray-400 hover:text-gray-300'
        }`}
    >
      {icon}
      {label}
    </button>
  );
}
```

### 6.2 Coin Ticker Input

```tsx
// frontend/src/components/coin/CoinTickerInput.tsx

import { useState, useEffect } from 'react';
import { Search, Loader2, Bitcoin } from 'lucide-react';
import { useStore } from '@/store';
import { coinApiClient } from '@/api/coinClient';

export function CoinTickerInput() {
  const [search, setSearch] = useState('');
  const [markets, setMarkets] = useState<CoinMarket[]>([]);
  const [filtered, setFiltered] = useState<CoinMarket[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);

  const startCoinSession = useStore((state) => state.startCoinSession);

  // Fetch markets on mount
  useEffect(() => {
    coinApiClient.getMarkets().then(setMarkets);
  }, []);

  // Filter markets based on search
  useEffect(() => {
    if (search.length > 0) {
      const searchUpper = search.toUpperCase();
      setFiltered(
        markets.filter(
          (m) =>
            m.market.includes(searchUpper) ||
            m.korean_name.includes(search) ||
            m.english_name.toUpperCase().includes(searchUpper)
        ).slice(0, 10)
      );
      setShowDropdown(true);
    } else {
      setFiltered([]);
      setShowDropdown(false);
    }
  }, [search, markets]);

  const handleSelect = async (market: string) => {
    setIsLoading(true);
    setShowDropdown(false);
    setSearch('');

    try {
      await startCoinSession(market);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative">
      <div className="relative">
        <Bitcoin className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-amber-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="코인 검색 (예: BTC, 비트코인)"
          className="input pl-10 pr-12"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 animate-spin" />
        )}
      </div>

      {showDropdown && filtered.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-surface-light border border-border rounded-lg shadow-lg max-h-60 overflow-y-auto">
          {filtered.map((market) => (
            <button
              key={market.market}
              onClick={() => handleSelect(market.market)}
              className="w-full px-4 py-3 text-left hover:bg-surface flex items-center justify-between"
            >
              <div>
                <span className="font-medium">{market.market}</span>
                <span className="ml-2 text-sm text-gray-400">
                  {market.korean_name}
                </span>
              </div>
              <span className="text-xs text-gray-500">
                {market.english_name}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 6.3 Store Updates

```typescript
// frontend/src/store/index.ts (additions)

type MarketType = 'stock' | 'coin';

interface MarketState {
  activeMarket: MarketType;
  setActiveMarket: (market: MarketType) => void;

  // Coin-specific state
  coinSessionId: string | null;
  coinTicker: string;
  coinStatus: SessionStatus | 'idle';
  coinAnalyses: AnalysisSummary[];
  coinReasoningLog: string[];
  coinTradeProposal: TradeProposal | null;

  // Coin actions
  startCoinSession: (market: string) => Promise<void>;
  // ... similar to stock actions
}
```

---

## 7. Crypto-Specific Agents Modifications

### 7.1 Technical Agent Adaptations

```python
# Crypto-specific indicators to consider:
CRYPTO_INDICATORS = {
    "24h_volume": "24시간 거래량",
    "24h_change": "24시간 변동률",
    "52w_high_low": "52주 최고/최저",
    "orderbook_imbalance": "호가 불균형",
    "trade_velocity": "체결 속도",
}
```

### 7.2 Sentiment Agent Modifications

```python
# Crypto-specific sentiment sources:
CRYPTO_SENTIMENT_SOURCES = [
    "crypto_twitter",      # Twitter/X crypto influencers
    "reddit_cryptocurrency", # r/cryptocurrency, r/bitcoin
    "fear_greed_index",    # Crypto Fear & Greed Index
    "google_trends",       # Search interest
]
```

### 7.3 Risk Agent Modifications

```python
# Crypto-specific risk factors:
CRYPTO_RISK_FACTORS = {
    "volatility_24h": "24시간 변동성",
    "liquidity_score": "유동성 점수",
    "btc_correlation": "BTC 상관관계",
    "market_dominance": "시장 지배력",
    "exchange_risk": "거래소 리스크",
}
```

---

## 8. Environment Configuration

```env
# === Upbit API Configuration ===
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key

# API Mode: "live" for real trading, "paper" for simulation
UPBIT_TRADING_MODE=paper

# Rate limit settings
UPBIT_RATE_LIMIT_ORDERS=8      # per second
UPBIT_RATE_LIMIT_QUERIES=30    # per second
```

---

## 9. Implementation Phases

### Phase 1: Market Data Integration (1-2 weeks)
- [ ] Upbit API client 구현 (QUOTATION API)
- [ ] 캔들, 티커, 호가 데이터 조회
- [ ] 코인 분석 API 라우트 추가
- [ ] Frontend 탭 네비게이션 구현
- [ ] 코인 티커 검색/선택 UI

### Phase 2: Analysis Pipeline (2 weeks)
- [ ] coin_trading_graph.py 생성
- [ ] 기술적 분석 에이전트 코인 적응
- [ ] 감성 분석 에이전트 크립토 소스 추가
- [ ] 리스크 에이전트 암호화폐 요소 반영
- [ ] WebSocket 실시간 가격 스트리밍

### Phase 3: Trading Execution (1-2 weeks)
- [ ] EXCHANGE API 인증 구현
- [ ] 주문 생성/취소/조회 구현
- [ ] 잔고 조회 연동
- [ ] HITL 승인 플로우 통합
- [ ] 주문 상태 모니터링

### Phase 4: UI/UX Polish (1 week)
- [ ] 코인 전용 차트 컴포넌트
- [ ] 실시간 가격 업데이트
- [ ] 거래 내역 표시
- [ ] 반응형 디자인 검증

---

## 10. API References

### Sources
- [Upbit Global Docs](https://global-docs.upbit.com/reference/rest-api-guide)
- [pyupbit Library](https://github.com/sharebook-kr/pyupbit)
- [upbit-client PyPI](https://pypi.org/project/upbit-client/)

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-19 | AI Assistant | Initial specification |
