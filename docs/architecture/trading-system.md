# Trading System Architecture

자동매매 시스템 아키텍처 상세

---

## 개요

자동매매 시스템은 분석 결과를 기반으로 실제 매매를 실행하고, 포지션을 모니터링하며, 리스크를 관리합니다.

---

## 시스템 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading System                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                   Coordinator                          │ │
│  │  - 매매 승인 처리                                      │ │
│  │  - Trade Queue 관리                                    │ │
│  │  - 장 시간 스케줄링                                    │ │
│  └────────────────────┬───────────────────────────────────┘ │
│                       │                                      │
│           ┌───────────┼───────────┐                         │
│           ▼           ▼           ▼                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │  Portfolio   │ │    Order     │ │    Risk      │        │
│  │    Agent     │ │    Agent     │ │   Monitor    │        │
│  │              │ │              │ │              │        │
│  │ - 포지션관리 │ │ - 주문실행   │ │ - 손절/익절  │        │
│  │ - 자금배분   │ │ - 체결확인   │ │ - 포지션감시 │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│           │              │               │                  │
│           └──────────────┼───────────────┘                  │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                 Market API Layer                       │ │
│  │  ┌──────────────┐  ┌──────────────┐                    │ │
│  │  │  Kiwoom API  │  │  Upbit API   │                    │ │
│  │  │  (한국주식)  │  │  (암호화폐)  │                    │ │
│  │  └──────────────┘  └──────────────┘                    │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 핵심 컴포넌트

### Coordinator

**역할**: 전체 자동매매 시스템 조율

**기능**:
- 매매 승인 처리 (`on_trade_approved`)
- Trade Queue 관리 (추가, 제거, 상태 변경)
- 장 시간 스케줄링
- Watch List 관리

**상태 관리**:
```python
class TradingMode(str, Enum):
    ACTIVE = "active"      # 활성 (자동매매 중)
    PAUSED = "paused"      # 일시정지
    STOPPED = "stopped"    # 중지
```

### Portfolio Agent

**역할**: 포트폴리오 및 자금 관리

**기능**:
- 현재 포지션 조회
- 가용 자금 확인
- 포지션 크기 계산
- 중복 매수 방지

**자금 배분 로직**:
```python
def calculate_position_size(
    available_cash: float,
    current_price: float,
    risk_score: int,
    max_position_pct: float = 10.0
) -> int:
    # 리스크 점수에 따른 최대 투자 비율 조정
    adjusted_pct = max_position_pct * (1 - risk_score * 0.05)

    # 최대 투자 금액
    max_investment = available_cash * (adjusted_pct / 100)

    # 수량 계산 (한국 주식은 1주 단위)
    quantity = int(max_investment / current_price)

    return quantity
```

### Order Agent

**역할**: 주문 실행 및 체결 관리

**기능**:
- 매수/매도 주문 실행
- 체결 확인
- 주문 실패 처리
- 체결 알림 발송

**주문 흐름**:
```
주문 요청 → 가격 확인 → API 호출 → 체결 대기 → 결과 처리
```

### Risk Monitor

**역할**: 포지션 모니터링 및 리스크 관리

**기능**:
- 실시간 가격 모니터링
- Stop-Loss 체크 및 실행
- Take-Profit 체크 및 실행
- 포지션 P&L 계산

**모니터링 로직**:
```python
async def check_position(position: Position):
    current_price = await get_current_price(position.ticker)

    # 손절 체크
    if current_price <= position.stop_loss:
        await execute_stop_loss(position)
        await notify_stop_loss_triggered(position)

    # 익절 체크
    elif current_price >= position.take_profit:
        await execute_take_profit(position)
        await notify_take_profit_triggered(position)
```

---

## Trade Queue

### 개요

Trade Queue는 실행 대기 중인 매매 주문을 관리합니다. 장이 마감된 시간에 승인된 주문은 다음 장 시작 시 실행됩니다.

### 상태

```python
class TradeQueueStatus(str, Enum):
    PENDING = "pending"        # 대기 중
    EXECUTING = "executing"    # 실행 중
    COMPLETED = "completed"    # 완료
    FAILED = "failed"          # 실패
    CANCELLED = "cancelled"    # 취소
```

### Queue 항목

```python
@dataclass
class TradeQueueItem:
    id: str
    session_id: str
    ticker: str
    stock_name: str
    action: str  # BUY, SELL
    quantity: int
    target_price: float
    stop_loss: float
    take_profit: float
    status: TradeQueueStatus
    created_at: datetime
    executed_at: Optional[datetime]
    error_message: Optional[str]
```

---

## 장 시간 관리

### Market Hours Service

| 시장 | 장 시간 | 휴장일 |
|------|---------|--------|
| KRX (한국) | 09:00 - 15:30 | 주말, 공휴일 |
| Crypto | 24/7 | 없음 |

### 스케줄링 로직

```python
async def process_trade_queue():
    while True:
        if is_market_open():
            pending_trades = get_pending_trades()
            for trade in pending_trades:
                await execute_trade(trade)
        await asyncio.sleep(60)  # 1분마다 체크
```

---

## 알림 시스템

### Telegram 알림

| 이벤트 | 알림 내용 |
|--------|-----------|
| 거래 제안 | 종목, 액션, 가격, 근거 |
| 거래 체결 | 종목, 수량, 체결가, 총액 |
| 거래 거부 | 종목, 거부 사유 |
| 손절 발동 | 종목, 트리거가, 손실률 |
| 익절 발동 | 종목, 트리거가, 수익률 |
| 시스템 상태 | 시작/중지/오류 |

### WebSocket 알림

```typescript
// 알림 타입
type TradeNotificationType =
  | 'trade_executed'      // 체결 완료
  | 'trade_queued'        // 대기열 추가
  | 'trade_rejected'      // 거래 거부
  | 'watch_added'         // 관심종목 추가
  | 'stop_loss_triggered' // 손절 발동
  | 'take_profit_triggered'; // 익절 발동
```

---

## TradeAction 유형

| 액션 | 설명 | 조건 |
|------|------|------|
| `BUY` | 신규 매수 | 미보유 + 매수 신호 |
| `SELL` | 전량 매도 | 보유 중 + 매도 신호 |
| `HOLD` | 보유 유지 | 보유 중 + 중립 |
| `ADD` | 추가 매수 | 보유 중 + 강한 매수 신호 |
| `REDUCE` | 부분 매도 | 보유 중 + 약한 매도 신호 |
| `WATCH` | 모니터링 | 미보유 + 관심 |
| `AVOID` | 매수 회피 | 미보유 + 강한 매도 신호 |

---

## API 엔드포인트

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/trading/status` | GET | 시스템 상태 |
| `/api/trading/start` | POST | 시스템 시작 |
| `/api/trading/stop` | POST | 시스템 중지 |
| `/api/trading/pause` | POST | 일시정지 |
| `/api/trading/resume` | POST | 재개 |
| `/api/trading/queue` | GET | Trade Queue 조회 |
| `/api/trading/queue/{id}` | DELETE | 주문 취소 |
| `/api/trading/portfolio` | GET | 포트폴리오 조회 |
| `/api/trading/positions` | GET | 포지션 조회 |
| `/api/trading/market-status` | GET | 장 상태 조회 |

---

## 에러 처리

### 주문 실패 처리

```python
try:
    result = await execute_order(trade)
except OrderFailedException as e:
    trade.status = TradeQueueStatus.FAILED
    trade.error_message = str(e)
    await notify_order_failed(trade)
except NetworkException:
    # 재시도 로직
    await retry_order(trade, max_retries=3)
```

### 재시도 정책

| 오류 유형 | 재시도 횟수 | 대기 시간 |
|-----------|-------------|-----------|
| 네트워크 오류 | 3회 | 5초 |
| API 오류 | 2회 | 10초 |
| 주문 거부 | 0회 | - |
