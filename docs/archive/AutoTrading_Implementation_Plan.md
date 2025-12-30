# Auto-Trading Implementation Plan

## Overview

AI Agent 기반 자동매매 시스템 구현 계획서.
분석 → 승인 → 자동매매 → 리스크 관리 전 과정을 Agent가 담당.

---

## Phase 1: News API Integration

### 1.1 Naver News API

**API 정보:**
- Endpoint: `https://openapi.naver.com/v1/search/news.json`
- 일일 호출 제한: 25,000회
- 인증: CLIENT_ID, CLIENT_SECRET (발급 완료)

**구현 구조:**

```
backend/
├── services/
│   └── news/
│       ├── __init__.py
│       ├── base.py          # Abstract base class (확장 인터페이스)
│       ├── naver.py         # Naver News implementation
│       ├── cache.py         # Redis caching layer
│       └── sentiment.py     # News sentiment analysis
```

**확장 가능한 인터페이스:**

```python
# backend/services/news/base.py
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class NewsArticle(BaseModel):
    """뉴스 기사 모델"""
    title: str
    description: str
    link: str
    source: str
    pub_date: datetime
    sentiment: Optional[str] = None  # positive, neutral, negative
    relevance_score: Optional[float] = None

class NewsSearchResult(BaseModel):
    """뉴스 검색 결과"""
    query: str
    total: int
    articles: List[NewsArticle]
    cached: bool = False
    provider: str

class NewsProvider(ABC):
    """뉴스 제공자 추상 클래스"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name"""
        pass

    @property
    @abstractmethod
    def daily_limit(self) -> int:
        """Daily API call limit"""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        count: int = 10,
        sort: str = "date"  # date | sim (similarity)
    ) -> NewsSearchResult:
        """Search news articles"""
        pass

    @abstractmethod
    async def get_remaining_quota(self) -> int:
        """Get remaining API calls for today"""
        pass
```

**Naver 구현:**

```python
# backend/services/news/naver.py
import httpx
from datetime import datetime
from typing import List
import redis.asyncio as redis
from .base import NewsProvider, NewsArticle, NewsSearchResult

class NaverNewsProvider(NewsProvider):
    """Naver News Search API Provider"""

    BASE_URL = "https://openapi.naver.com/v1/search/news.json"
    DAILY_LIMIT = 25000

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redis_client: redis.Redis
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redis = redis_client
        self._http = httpx.AsyncClient()

    @property
    def name(self) -> str:
        return "naver"

    @property
    def daily_limit(self) -> int:
        return self.DAILY_LIMIT

    async def search(
        self,
        query: str,
        count: int = 10,
        sort: str = "date"
    ) -> NewsSearchResult:
        # Check cache first
        cache_key = f"news:naver:{query}:{count}:{sort}"
        cached = await self.redis.get(cache_key)
        if cached:
            return NewsSearchResult.model_validate_json(cached)

        # Check quota
        remaining = await self.get_remaining_quota()
        if remaining <= 0:
            raise QuotaExceededError("Naver API daily limit exceeded")

        # Make API request
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret
        }
        params = {
            "query": query,
            "display": count,
            "sort": sort
        }

        response = await self._http.get(
            self.BASE_URL,
            headers=headers,
            params=params
        )
        response.raise_for_status()
        data = response.json()

        # Increment usage counter
        await self._increment_usage()

        # Parse articles
        articles = [
            NewsArticle(
                title=self._clean_html(item["title"]),
                description=self._clean_html(item["description"]),
                link=item["link"],
                source=item.get("originallink", item["link"]),
                pub_date=self._parse_date(item["pubDate"])
            )
            for item in data.get("items", [])
        ]

        result = NewsSearchResult(
            query=query,
            total=data.get("total", 0),
            articles=articles,
            cached=False,
            provider=self.name
        )

        # Cache for 30 minutes
        await self.redis.setex(
            cache_key,
            1800,  # 30 minutes
            result.model_dump_json()
        )

        return result

    async def get_remaining_quota(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        usage_key = f"news:naver:usage:{today}"
        usage = await self.redis.get(usage_key)
        current = int(usage) if usage else 0
        return self.DAILY_LIMIT - current

    async def _increment_usage(self):
        today = datetime.now().strftime("%Y-%m-%d")
        usage_key = f"news:naver:usage:{today}"
        await self.redis.incr(usage_key)
        await self.redis.expire(usage_key, 86400)  # 24 hours

    @staticmethod
    def _clean_html(text: str) -> str:
        """Remove HTML tags from text"""
        import re
        return re.sub(r'<[^>]+>', '', text)

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse Naver date format"""
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
```

**News Service (통합 서비스):**

```python
# backend/services/news/__init__.py
from typing import Optional
from .base import NewsProvider, NewsSearchResult
from .naver import NaverNewsProvider

class NewsService:
    """News aggregation service with fallback support"""

    def __init__(self):
        self.providers: dict[str, NewsProvider] = {}
        self.primary_provider: Optional[str] = None

    def register_provider(
        self,
        provider: NewsProvider,
        primary: bool = False
    ):
        self.providers[provider.name] = provider
        if primary or self.primary_provider is None:
            self.primary_provider = provider.name

    async def search(
        self,
        query: str,
        count: int = 10,
        provider: Optional[str] = None
    ) -> NewsSearchResult:
        """Search news with automatic fallback"""
        provider_name = provider or self.primary_provider

        if provider_name not in self.providers:
            raise ValueError(f"Unknown provider: {provider_name}")

        news_provider = self.providers[provider_name]

        # Try primary provider
        try:
            remaining = await news_provider.get_remaining_quota()
            if remaining > 0:
                return await news_provider.search(query, count)
        except Exception as e:
            print(f"[NewsService] Primary provider failed: {e}")

        # Fallback to other providers
        for name, fallback in self.providers.items():
            if name == provider_name:
                continue
            try:
                remaining = await fallback.get_remaining_quota()
                if remaining > 0:
                    return await fallback.search(query, count)
            except Exception:
                continue

        raise Exception("All news providers exhausted")
```

### 1.2 API Endpoints

```python
# backend/app/api/routes/news.py
from fastapi import APIRouter, Depends, HTTPException
from backend.services.news import NewsService, NewsSearchResult

router = APIRouter(prefix="/api/news", tags=["news"])

@router.get("/search/{query}", response_model=NewsSearchResult)
async def search_news(
    query: str,
    count: int = 10,
    news_service: NewsService = Depends(get_news_service)
):
    """종목 관련 뉴스 검색"""
    try:
        return await news_service.search(query, count)
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/quota")
async def get_quota(
    news_service: NewsService = Depends(get_news_service)
):
    """API 사용량 조회"""
    quotas = {}
    for name, provider in news_service.providers.items():
        quotas[name] = {
            "daily_limit": provider.daily_limit,
            "remaining": await provider.get_remaining_quota()
        }
    return quotas

@router.get("/stock/{stock_code}")
async def get_stock_news(
    stock_code: str,
    stock_name: Optional[str] = None,
    count: int = 10,
    news_service: NewsService = Depends(get_news_service)
):
    """특정 종목 뉴스 검색 (종목코드 + 종목명 조합)"""
    query = stock_name if stock_name else stock_code
    return await news_service.search(f"{query} 주식", count)
```

### 1.3 Sentiment Analysis Integration

```python
# backend/services/news/sentiment.py
from typing import List
from .base import NewsArticle

class NewsSentimentAnalyzer:
    """LLM 기반 뉴스 감성 분석"""

    def __init__(self, llm_provider):
        self.llm = llm_provider

    async def analyze_articles(
        self,
        articles: List[NewsArticle],
        stock_name: str
    ) -> dict:
        """뉴스 기사들의 종합 감성 분석"""
        if not articles:
            return {
                "sentiment": "neutral",
                "score": 0,
                "summary": "관련 뉴스 없음",
                "key_points": []
            }

        titles = "\n".join([f"- {a.title}" for a in articles[:10]])

        prompt = f"""
        다음은 '{stock_name}' 관련 최근 뉴스 제목입니다:

        {titles}

        위 뉴스들을 분석하여 다음 JSON 형식으로 응답하세요:
        {{
            "sentiment": "positive" | "neutral" | "negative",
            "score": -100 ~ 100 (부정 ~ 긍정),
            "summary": "2-3문장 요약",
            "key_points": ["주요 포인트1", "주요 포인트2"],
            "risk_factors": ["리스크 요인"] (있는 경우만)
        }}
        """

        response = await self.llm.generate(prompt)
        return self._parse_response(response)
```

### 1.4 Tasks

- [ ] `backend/services/news/base.py` - 확장 인터페이스 구현
- [ ] `backend/services/news/naver.py` - Naver API 구현
- [ ] `backend/services/news/cache.py` - Redis 캐싱 레이어
- [ ] `backend/services/news/sentiment.py` - 감성 분석
- [ ] `backend/app/api/routes/news.py` - API 엔드포인트
- [ ] Sentiment Agent에 뉴스 데이터 통합
- [ ] 자동매매 중 뉴스 알림 기능

---

## Phase 2: Auto-Trading Architecture

### 2.1 Agent 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                     Auto-Trading System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Portfolio    │    │    Order     │    │    Risk      │      │
│  │   Agent      │    │    Agent     │    │   Monitor    │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                    │               │
│         └───────────────────┼────────────────────┘               │
│                             │                                    │
│                    ┌────────▼────────┐                          │
│                    │  Execution      │                          │
│                    │  Coordinator    │                          │
│                    └────────┬────────┘                          │
│                             │                                    │
│         ┌───────────────────┼───────────────────┐               │
│         │                   │                   │               │
│  ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐        │
│  │ Kiwoom API  │    │   WebSocket │    │   Database  │        │
│  │  (Orders)   │    │   (Updates) │    │ (Positions) │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Agent 역할 정의

#### Portfolio Agent

**책임:**
- 계좌 잔고 분석
- 최적 비중 계산 (단일 종목, 전체 주식, 예수금)
- 리밸런싱 전략 수립
- 신규 종목 편입 시 비중 조정

**입력:**
- 현재 계좌 정보 (잔고, 포지션)
- 승인된 Trade Proposal
- 리스크 파라미터

**출력:**
- 실행할 주문 목록
- 비중 조정 계획
- 리밸런싱 제안

```python
# backend/agents/trading/portfolio_agent.py
class PortfolioAgent:
    """포트폴리오 관리 Agent"""

    async def calculate_allocation(
        self,
        account: AccountInfo,
        proposal: TradeProposal,
        risk_params: RiskParameters
    ) -> AllocationPlan:
        """신규 종목 비중 계산"""

        # 1. 현재 포트폴리오 분석
        current_positions = account.positions
        total_equity = account.total_equity
        available_cash = account.available_cash

        # 2. 리스크 기반 비중 계산
        # - 리스크 점수가 높을수록 낮은 비중
        # - 계좌 잔고에 따른 최대 비중 조정
        max_position_pct = self._calculate_max_position(
            risk_score=proposal.risk_score,
            total_equity=total_equity
        )

        # 3. 주문 수량 계산
        target_amount = total_equity * max_position_pct
        quantity = int(target_amount / proposal.entry_price)

        return AllocationPlan(
            ticker=proposal.ticker,
            action=proposal.action,
            quantity=quantity,
            position_pct=max_position_pct,
            estimated_amount=quantity * proposal.entry_price
        )

    async def suggest_rebalancing(
        self,
        account: AccountInfo,
        market_data: dict
    ) -> RebalancingPlan:
        """리밸런싱 제안 생성"""
        pass
```

#### Order Agent

**책임:**
- 키움 API를 통한 주문 실행
- 분할 매수/매도 전략
- 체결 확인 및 상태 관리
- Rate Limit 준수

**키움 API Rate Limit 고려:**
```python
# backend/services/kiwoom/rate_limiter.py
class KiwoomRateLimiter:
    """키움 API Rate Limit 관리"""

    # 키움 제한: 초당 5회, 분당 100회
    RATE_LIMIT_PER_SECOND = 5
    RATE_LIMIT_PER_MINUTE = 100

    def __init__(self, redis_client):
        self.redis = redis_client

    async def acquire(self) -> bool:
        """Rate limit 확인 및 획득"""
        now = datetime.now()
        second_key = f"kiwoom:rate:{now.strftime('%Y%m%d%H%M%S')}"
        minute_key = f"kiwoom:rate:{now.strftime('%Y%m%d%H%M')}"

        # 초당 제한 확인
        second_count = await self.redis.incr(second_key)
        await self.redis.expire(second_key, 2)
        if second_count > self.RATE_LIMIT_PER_SECOND:
            return False

        # 분당 제한 확인
        minute_count = await self.redis.incr(minute_key)
        await self.redis.expire(minute_key, 120)
        if minute_count > self.RATE_LIMIT_PER_MINUTE:
            return False

        return True

    async def wait_for_slot(self, timeout: float = 10.0):
        """Rate limit 슬롯 대기"""
        start = time.time()
        while time.time() - start < timeout:
            if await self.acquire():
                return True
            await asyncio.sleep(0.2)
        raise RateLimitExceeded("Kiwoom rate limit timeout")
```

**Order Agent 구현:**
```python
# backend/agents/trading/order_agent.py
class OrderAgent:
    """주문 실행 Agent"""

    def __init__(
        self,
        kiwoom_client: KiwoomClient,
        rate_limiter: KiwoomRateLimiter
    ):
        self.kiwoom = kiwoom_client
        self.limiter = rate_limiter

    async def execute_order(
        self,
        order: OrderRequest
    ) -> OrderResult:
        """주문 실행"""
        # Rate limit 확인
        await self.limiter.wait_for_slot()

        # 분할 매수/매도 결정
        if order.quantity > 100:
            return await self._execute_split_order(order)
        else:
            return await self._execute_single_order(order)

    async def _execute_split_order(
        self,
        order: OrderRequest,
        splits: int = 3
    ) -> OrderResult:
        """분할 주문 실행"""
        quantity_per_split = order.quantity // splits
        results = []

        for i in range(splits):
            # 마지막은 나머지 수량
            qty = quantity_per_split if i < splits - 1 \
                else order.quantity - (quantity_per_split * (splits - 1))

            await self.limiter.wait_for_slot()
            result = await self.kiwoom.place_order(
                ticker=order.ticker,
                action=order.action,
                quantity=qty,
                price=order.price,
                order_type=order.order_type
            )
            results.append(result)

            # 분할 주문 간 간격
            await asyncio.sleep(1)

        return self._aggregate_results(results)
```

#### Risk Monitor

**책임:**
- 실시간 포지션 모니터링
- 손절/익절 조건 체크
- 급등락 감지 및 자동매매 일시정지
- 뉴스 기반 리스크 알림
- 사용자 알림 전송

**손절/익절 모드:**
```python
# backend/agents/trading/risk_monitor.py
from enum import Enum

class StopLossMode(Enum):
    USER_APPROVAL = "user_approval"  # 사용자 승인 필요
    AGENT_AUTO = "agent_auto"        # Agent 자동 실행

class RiskMonitor:
    """리스크 모니터링 Agent"""

    def __init__(
        self,
        kiwoom_client: KiwoomClient,
        news_service: NewsService,
        notification_service: NotificationService
    ):
        self.kiwoom = kiwoom_client
        self.news = news_service
        self.notifier = notification_service
        self.watching: dict[str, WatchConfig] = {}
        self.paused = False

    async def start_watching(
        self,
        position: Position,
        stop_loss: float,
        take_profit: float,
        mode: StopLossMode = StopLossMode.USER_APPROVAL
    ):
        """포지션 모니터링 시작"""
        config = WatchConfig(
            ticker=position.ticker,
            entry_price=position.avg_price,
            quantity=position.quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            mode=mode
        )
        self.watching[position.ticker] = config

    async def check_positions(self):
        """전체 포지션 체크 (주기적 실행)"""
        if self.paused:
            return

        for ticker, config in self.watching.items():
            current_price = await self.kiwoom.get_current_price(ticker)

            # 급등락 체크 (일일 ±10%)
            change_pct = (current_price - config.entry_price) / config.entry_price * 100
            if abs(change_pct) >= 10:
                await self._handle_sudden_move(ticker, change_pct, current_price)
                continue

            # 손절 체크
            if current_price <= config.stop_loss:
                await self._handle_stop_loss(config, current_price)

            # 익절 체크
            elif current_price >= config.take_profit:
                await self._handle_take_profit(config, current_price)

    async def _handle_sudden_move(
        self,
        ticker: str,
        change_pct: float,
        current_price: float
    ):
        """급등락 처리: 일시정지 + 알림"""
        # 자동매매 일시정지
        self.paused = True

        # 뉴스 확인
        news = await self.news.search(f"{ticker} 주식", count=5)

        # 사용자 알림
        await self.notifier.send_alert(
            type="SUDDEN_MOVE",
            ticker=ticker,
            data={
                "change_pct": change_pct,
                "current_price": current_price,
                "direction": "up" if change_pct > 0 else "down",
                "recent_news": [n.title for n in news.articles[:3]],
                "action_required": True,
                "options": ["RESUME", "CLOSE_POSITION", "ADJUST_STOP_LOSS"]
            }
        )

    async def _handle_stop_loss(
        self,
        config: WatchConfig,
        current_price: float
    ):
        """손절 처리"""
        if config.mode == StopLossMode.AGENT_AUTO:
            # Agent 자동 실행
            await self._execute_stop_loss(config)
        else:
            # 사용자 승인 요청
            await self.notifier.send_alert(
                type="STOP_LOSS_TRIGGERED",
                ticker=config.ticker,
                data={
                    "entry_price": config.entry_price,
                    "current_price": current_price,
                    "stop_loss": config.stop_loss,
                    "loss_pct": (current_price - config.entry_price) / config.entry_price * 100,
                    "action_required": True,
                    "options": ["EXECUTE_STOP_LOSS", "ADJUST_STOP_LOSS", "HOLD"]
                }
            )

    async def pause(self):
        """자동매매 일시정지"""
        self.paused = True
        await self.notifier.send_alert(
            type="TRADING_PAUSED",
            data={"reason": "Manual pause requested"}
        )

    async def resume(self):
        """자동매매 재개"""
        self.paused = False
        await self.notifier.send_alert(
            type="TRADING_RESUMED",
            data={}
        )
```

### 2.3 Execution Flow

```
[User Approval]
       │
       ▼
┌──────────────────┐
│ Portfolio Agent  │ ◄── 계좌 정보, 리스크 파라미터
│  - 비중 계산     │
│  - 리밸런싱 체크 │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Order Agent    │ ◄── Rate Limit 관리
│  - 분할 주문     │
│  - 체결 확인     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Risk Monitor    │ ◄── 실시간 가격, 뉴스
│  - 손절/익절     │
│  - 급등락 감지   │
│  - 알림 전송     │
└──────────────────┘
```

### 2.4 State Management

```python
# backend/models/trading_state.py
from enum import Enum
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class TradingMode(Enum):
    ACTIVE = "active"        # 정상 운영
    PAUSED = "paused"        # 일시정지
    STOPPED = "stopped"      # 완전 중지

class PositionStatus(Enum):
    PENDING = "pending"      # 주문 대기
    PARTIAL = "partial"      # 부분 체결
    FILLED = "filled"        # 전량 체결
    CLOSED = "closed"        # 청산 완료

class ManagedPosition(BaseModel):
    """관리 중인 포지션"""
    ticker: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float

    # 손절/익절 설정
    stop_loss: float
    take_profit: float
    stop_loss_mode: StopLossMode

    # 메타데이터
    entry_time: datetime
    last_updated: datetime
    status: PositionStatus

    # 분석 참조
    analysis_session_id: Optional[str] = None
    risk_score: Optional[int] = None

class TradingState(BaseModel):
    """자동매매 전체 상태"""
    mode: TradingMode
    positions: List[ManagedPosition]
    pending_orders: List[OrderRequest]

    # 계좌 요약
    total_equity: float
    available_cash: float
    stock_value: float
    total_pnl: float
    total_pnl_pct: float

    # 리스크 지표
    cash_ratio: float          # 예수금 비중
    max_single_position: float # 최대 단일 종목 비중

    # 알림 설정
    alerts_enabled: bool
    last_alert: Optional[datetime]
```

### 2.5 WebSocket Updates

```python
# 자동매매 상태 실시간 업데이트
@router.websocket("/ws/trading/{user_id}")
async def trading_websocket(websocket: WebSocket, user_id: str):
    await websocket.accept()

    try:
        while True:
            # 상태 업데이트 전송
            state = await get_trading_state(user_id)
            await websocket.send_json({
                "type": "state_update",
                "data": state.model_dump()
            })

            # 알림 전송
            alerts = await get_pending_alerts(user_id)
            for alert in alerts:
                await websocket.send_json({
                    "type": "alert",
                    "data": alert
                })

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
```

### 2.6 Frontend Components

```typescript
// frontend/src/components/trading/TradingDashboard.tsx
interface TradingDashboardProps {
  state: TradingState;
  onPause: () => void;
  onResume: () => void;
  onAlertAction: (alertId: string, action: string) => void;
}

// frontend/src/components/trading/PositionCard.tsx
interface PositionCardProps {
  position: ManagedPosition;
  onAdjustStopLoss: (newValue: number) => void;
  onClosePosition: () => void;
}

// frontend/src/components/trading/AlertDialog.tsx
interface AlertDialogProps {
  alert: TradingAlert;
  onAction: (action: string) => void;
}
```

---

## Phase 3: Integration

### 3.1 분석 → 자동매매 연결

```python
# backend/app/api/routes/approval.py 수정
@router.post("/approval")
async def submit_approval(request: ApprovalRequest):
    if request.decision == "approved":
        # 기존 로직...

        # 자동매매 시스템에 전달
        await execution_coordinator.on_trade_approved(
            session_id=request.session_id,
            proposal=trade_proposal,
            user_settings=await get_user_trading_settings(request.user_id)
        )
```

### 3.2 Settings

```python
# backend/models/user_settings.py
class TradingSettings(BaseModel):
    """사용자 자동매매 설정"""

    # 손절/익절 모드
    stop_loss_mode: StopLossMode = StopLossMode.USER_APPROVAL
    take_profit_mode: StopLossMode = StopLossMode.USER_APPROVAL

    # 알림 설정
    alerts_enabled: bool = True
    alert_channels: List[str] = ["websocket", "push"]

    # 자동매매 제한
    max_daily_trades: int = 10
    max_single_position_pct: float = 0.15  # 15%
    min_cash_ratio: float = 0.20           # 20%
```

---

## Implementation Order

### Week 1: News API
1. [ ] News provider interface 구현
2. [ ] Naver News API 연동
3. [ ] Redis caching layer
4. [ ] API endpoints
5. [ ] Sentiment Agent 통합

### Week 2: Portfolio & Order Agents
1. [ ] Portfolio Agent 기본 구현
2. [ ] 비중 계산 로직
3. [ ] Order Agent 기본 구현
4. [ ] Kiwoom Rate Limiter
5. [ ] 분할 주문 로직

### Week 3: Risk Monitor
1. [ ] Risk Monitor 기본 구현
2. [ ] 손절/익절 로직 (두 가지 모드)
3. [ ] 급등락 감지
4. [ ] 알림 시스템
5. [ ] Pause/Resume 기능

### Week 4: Integration & UI
1. [ ] Approval → 자동매매 연결
2. [ ] Trading WebSocket
3. [ ] Frontend Dashboard
4. [ ] Position 관리 UI
5. [ ] Alert 처리 UI

---

## Environment Variables

```env
# .env 추가 항목

# Naver News API
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret

# Trading Settings
MAX_SINGLE_POSITION_PCT=0.15
MIN_CASH_RATIO=0.20
MAX_DAILY_TRADES=10

# Kiwoom Rate Limits
KIWOOM_RATE_PER_SECOND=5
KIWOOM_RATE_PER_MINUTE=100
```

---

## Risk Considerations

1. **API Rate Limits**
   - Naver: 25,000/일 → 캐싱 필수
   - Kiwoom: 5/초, 100/분 → Rate Limiter 필수

2. **자동매매 안전장치**
   - 급등락 시 자동 일시정지
   - 일일 최대 거래 횟수 제한
   - 최소 예수금 비중 유지

3. **장애 대응**
   - WebSocket 재연결 로직
   - 주문 실패 시 재시도 + 알림
   - 시스템 오류 시 자동매매 중지
