# Trading API

거래 API 레퍼런스

---

## 개요

Trading API는 자동매매 시스템을 제어하고, 포지션을 관리하며, 거래 대기열을 처리합니다.

---

## 시스템 제어

### 트레이딩 상태 조회

```http
GET /api/trading/status
```

**Response:**

```json
{
  "mode": "active",
  "is_market_open": true,
  "positions_count": 2,
  "queue_count": 3,
  "last_trade_at": "2026-01-03T10:30:00Z",
  "uptime_seconds": 3600
}
```

| 필드 | 설명 |
|------|------|
| `mode` | 현재 모드 (active/paused/stopped) |
| `is_market_open` | 장 운영 여부 |
| `positions_count` | 보유 포지션 수 |
| `queue_count` | 대기열 항목 수 |

---

### 트레이딩 시작

```http
POST /api/trading/start
```

**Response:**

```json
{
  "mode": "active",
  "message": "Trading started"
}
```

---

### 트레이딩 일시정지

```http
POST /api/trading/pause
```

**Response:**

```json
{
  "mode": "paused",
  "message": "Trading paused"
}
```

---

### 트레이딩 중지

```http
POST /api/trading/stop
```

**Response:**

```json
{
  "mode": "stopped",
  "message": "Trading stopped"
}
```

---

## 거래 대기열 (Trade Queue)

### 대기열 조회

```http
GET /api/trading/queue
```

**Response:**

```json
{
  "queue": [
    {
      "id": "queue-123",
      "ticker": "005930",
      "stock_name": "삼성전자",
      "action": "BUY",
      "quantity": 10,
      "target_price": 72000,
      "stop_loss": 69000,
      "take_profit": 78000,
      "status": "pending",
      "priority": 1,
      "created_at": "2026-01-03T10:00:00Z",
      "expires_at": "2026-01-03T15:30:00Z"
    }
  ],
  "total": 3
}
```

---

### 대기열에 추가

```http
POST /api/trading/queue
```

**Request Body:**

```json
{
  "ticker": "005930",
  "action": "BUY",
  "quantity": 10,
  "target_price": 72000,
  "stop_loss": 69000,
  "take_profit": 78000,
  "priority": 1
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `ticker` | string | Yes | 종목 코드 |
| `action` | string | Yes | BUY/SELL/ADD/REDUCE |
| `quantity` | int | Yes | 수량 |
| `target_price` | float | No | 목표가 |
| `stop_loss` | float | No | 손절가 |
| `take_profit` | float | No | 익절가 |
| `priority` | int | No | 우선순위 (1=높음) |

**Response:**

```json
{
  "id": "queue-456",
  "status": "pending",
  "message": "Added to queue"
}
```

---

### 대기열 항목 삭제

```http
DELETE /api/trading/queue/{queue_id}
```

**Response:**

```json
{
  "id": "queue-123",
  "status": "cancelled",
  "message": "Removed from queue"
}
```

---

### 대기열 전체 삭제

```http
DELETE /api/trading/queue
```

**Response:**

```json
{
  "cleared": 3,
  "message": "Queue cleared"
}
```

---

## 포지션 관리

### 포지션 조회

```http
GET /api/trading/positions
```

**Response:**

```json
{
  "positions": [
    {
      "id": "pos-123",
      "ticker": "005930",
      "stock_name": "삼성전자",
      "quantity": 10,
      "entry_price": 72000,
      "current_price": 73500,
      "pnl": 15000,
      "pnl_percent": 2.08,
      "stop_loss": 69000,
      "take_profit": 78000,
      "opened_at": "2026-01-03T09:30:00Z"
    }
  ],
  "total_pnl": 15000,
  "total_value": 735000
}
```

---

### 포지션 업데이트

```http
PATCH /api/trading/positions/{position_id}
```

**Request Body:**

```json
{
  "stop_loss": 70000,
  "take_profit": 80000
}
```

**Response:**

```json
{
  "id": "pos-123",
  "stop_loss": 70000,
  "take_profit": 80000,
  "message": "Position updated"
}
```

---

### 포지션 청산

```http
POST /api/trading/positions/{position_id}/close
```

**Query Parameters:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `reason` | string | 청산 사유 (manual/stop_loss/take_profit) |

**Response:**

```json
{
  "id": "pos-123",
  "ticker": "005930",
  "quantity": 10,
  "entry_price": 72000,
  "exit_price": 73500,
  "pnl": 15000,
  "pnl_percent": 2.08,
  "status": "closed",
  "reason": "manual"
}
```

---

## Watch List

### Watch List 조회

```http
GET /api/trading/watch-list
```

**Response:**

```json
{
  "items": [
    {
      "ticker": "005930",
      "stock_name": "삼성전자",
      "reason": "과매도 영역 진입",
      "signal": "WATCH",
      "added_at": "2026-01-03T10:00:00Z"
    }
  ],
  "total": 5
}
```

---

### Watch List에 추가

```http
POST /api/trading/watch-list
```

**Request Body:**

```json
{
  "ticker": "005930",
  "reason": "과매도 영역 진입"
}
```

---

### Watch List에서 삭제

```http
DELETE /api/trading/watch-list/{ticker}
```

---

### Watch 항목을 대기열로 전환

```http
POST /api/trading/watch-list/{ticker}/convert
```

**Request Body:**

```json
{
  "action": "BUY",
  "quantity": 10,
  "target_price": 72000,
  "stop_loss": 69000,
  "take_profit": 78000
}
```

---

## 거래 실행

### 즉시 매수

```http
POST /api/trading/execute/buy
```

**Request Body:**

```json
{
  "ticker": "005930",
  "quantity": 10,
  "order_type": "market",
  "limit_price": null,
  "stop_loss": 69000,
  "take_profit": 78000
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `ticker` | string | Yes | 종목 코드 |
| `quantity` | int | Yes | 수량 |
| `order_type` | string | No | market/limit (기본: market) |
| `limit_price` | float | No | 지정가 (limit 주문 시) |
| `stop_loss` | float | No | 손절가 |
| `take_profit` | float | No | 익절가 |

**Response:**

```json
{
  "order_id": "order-789",
  "ticker": "005930",
  "action": "BUY",
  "quantity": 10,
  "filled_price": 72100,
  "total_amount": 721000,
  "status": "filled",
  "filled_at": "2026-01-03T10:30:00Z"
}
```

---

### 즉시 매도

```http
POST /api/trading/execute/sell
```

**Request Body:**

```json
{
  "ticker": "005930",
  "quantity": 10,
  "order_type": "market"
}
```

---

## 거래 내역

### 거래 내역 조회

```http
GET /api/trading/history
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `start_date` | date | - | 시작일 |
| `end_date` | date | - | 종료일 |
| `ticker` | string | - | 종목 필터 |
| `action` | string | - | 액션 필터 |
| `limit` | int | 50 | 반환 개수 |

**Response:**

```json
{
  "trades": [
    {
      "id": "trade-123",
      "ticker": "005930",
      "stock_name": "삼성전자",
      "action": "BUY",
      "quantity": 10,
      "price": 72100,
      "total_amount": 721000,
      "executed_at": "2026-01-03T10:30:00Z"
    }
  ],
  "total": 25,
  "summary": {
    "total_trades": 25,
    "profitable_trades": 18,
    "total_pnl": 250000,
    "win_rate": 72
  }
}
```

---

## 에러 응답

| 에러 코드 | HTTP 상태 | 설명 |
|-----------|-----------|------|
| `MARKET_CLOSED` | 400 | 장 마감 |
| `INSUFFICIENT_BALANCE` | 400 | 잔고 부족 |
| `POSITION_NOT_FOUND` | 404 | 포지션 없음 |
| `ORDER_REJECTED` | 400 | 주문 거부 |
| `QUEUE_FULL` | 400 | 대기열 가득 참 |

---

## 다음 단계

- [WebSocket API](websocket.md): 실시간 알림
- [Analysis API](analysis.md): 분석 API
- [Kiwoom API](kiwoom.md): 키움 API 연동
