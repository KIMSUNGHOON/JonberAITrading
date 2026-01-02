# Kiwoom API

키움증권 API 연동 레퍼런스

---

## 개요

키움증권 Open API를 통해 한국 주식 시장에 접근합니다. 모의투자와 실거래 모드를 지원합니다.

> **주의**: 실거래 전환 시 반드시 모의투자에서 충분한 테스트 후 진행하세요.

---

## 환경 설정

### 환경 변수

```env
# 키움 API 설정
KIWOOM_APP_KEY=your_app_key
KIWOOM_APP_SECRET=your_app_secret
KIWOOM_IS_MOCK=true  # 모의투자: true, 실거래: false

# 계좌 정보
KIWOOM_ACCOUNT_NO=12345678-01
```

### 모드 전환

```bash
# 모의투자 모드 (기본)
KIWOOM_IS_MOCK=true

# 실거래 모드 (주의!)
KIWOOM_IS_MOCK=false
```

---

## 시세 조회 API

### 현재가 조회

```http
GET /api/kr-stocks/{ticker}/price
```

**Response:**

```json
{
  "ticker": "005930",
  "name": "삼성전자",
  "price": 72000,
  "change": 1000,
  "change_rate": 1.41,
  "volume": 15000000,
  "trade_value": 1080000000000,
  "high": 72500,
  "low": 71000,
  "open": 71500,
  "prev_close": 71000,
  "market_cap": 4300000000000000,
  "per": 12.5,
  "pbr": 1.2,
  "timestamp": "2026-01-03T10:30:00Z"
}
```

---

### 호가 조회

```http
GET /api/kr-stocks/{ticker}/orderbook
```

**Response:**

```json
{
  "ticker": "005930",
  "timestamp": "2026-01-03T10:30:00Z",
  "asks": [
    {"price": 72100, "quantity": 5000},
    {"price": 72200, "quantity": 3000},
    {"price": 72300, "quantity": 2500},
    {"price": 72400, "quantity": 2000},
    {"price": 72500, "quantity": 1500}
  ],
  "bids": [
    {"price": 72000, "quantity": 4500},
    {"price": 71900, "quantity": 3500},
    {"price": 71800, "quantity": 3000},
    {"price": 71700, "quantity": 2500},
    {"price": 71600, "quantity": 2000}
  ],
  "total_ask_volume": 14000,
  "total_bid_volume": 15500
}
```

---

### 차트 데이터 조회

```http
GET /api/kr-stocks/{ticker}/chart
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `period` | string | day | day/week/month |
| `count` | int | 100 | 캔들 개수 |

**Response:**

```json
{
  "ticker": "005930",
  "period": "day",
  "candles": [
    {
      "date": "2026-01-03",
      "open": 71500,
      "high": 72500,
      "low": 71000,
      "close": 72000,
      "volume": 15000000
    }
  ]
}
```

---

## 주문 API

### 매수 주문

```http
POST /api/kiwoom/order/buy
```

**Request Body:**

```json
{
  "ticker": "005930",
  "quantity": 10,
  "order_type": "market",
  "limit_price": null
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `ticker` | string | Yes | 종목 코드 |
| `quantity` | int | Yes | 수량 |
| `order_type` | string | No | market/limit (기본: market) |
| `limit_price` | float | No | 지정가 (limit 주문 시) |

**Response:**

```json
{
  "order_id": "KW20260103001234",
  "ticker": "005930",
  "action": "BUY",
  "quantity": 10,
  "order_type": "market",
  "status": "submitted",
  "submitted_at": "2026-01-03T10:30:00Z"
}
```

---

### 매도 주문

```http
POST /api/kiwoom/order/sell
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

### 주문 취소

```http
DELETE /api/kiwoom/order/{order_id}
```

**Response:**

```json
{
  "order_id": "KW20260103001234",
  "status": "cancelled",
  "cancelled_at": "2026-01-03T10:31:00Z"
}
```

---

### 주문 상태 조회

```http
GET /api/kiwoom/order/{order_id}
```

**Response:**

```json
{
  "order_id": "KW20260103001234",
  "ticker": "005930",
  "action": "BUY",
  "quantity": 10,
  "filled_quantity": 10,
  "filled_price": 72100,
  "status": "filled",
  "submitted_at": "2026-01-03T10:30:00Z",
  "filled_at": "2026-01-03T10:30:05Z"
}
```

**Status Values:**

| 상태 | 설명 |
|------|------|
| `submitted` | 주문 접수 |
| `partial` | 부분 체결 |
| `filled` | 전량 체결 |
| `cancelled` | 취소됨 |
| `rejected` | 거부됨 |

---

## 계좌 API

### 잔고 조회

```http
GET /api/kiwoom/account/balance
```

**Response:**

```json
{
  "account_no": "12345678-01",
  "total_balance": 10000000,
  "available_balance": 8500000,
  "invested_amount": 1500000,
  "evaluation_amount": 1550000,
  "total_pnl": 50000,
  "total_pnl_percent": 3.33
}
```

---

### 보유 종목 조회

```http
GET /api/kiwoom/account/holdings
```

**Response:**

```json
{
  "holdings": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "quantity": 10,
      "avg_price": 72000,
      "current_price": 73500,
      "evaluation": 735000,
      "pnl": 15000,
      "pnl_percent": 2.08
    }
  ],
  "total_evaluation": 735000,
  "total_pnl": 15000
}
```

---

### 거래 내역 조회

```http
GET /api/kiwoom/account/trades
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `start_date` | date | - | 시작일 (YYYYMMDD) |
| `end_date` | date | - | 종료일 (YYYYMMDD) |

**Response:**

```json
{
  "trades": [
    {
      "trade_id": "T20260103001234",
      "ticker": "005930",
      "name": "삼성전자",
      "action": "BUY",
      "quantity": 10,
      "price": 72100,
      "amount": 721000,
      "fee": 1442,
      "tax": 0,
      "traded_at": "2026-01-03T10:30:05Z"
    }
  ]
}
```

---

## 시장 정보 API

### 장 운영 상태

```http
GET /api/kiwoom/market/status
```

**Response:**

```json
{
  "market": "KOSPI",
  "status": "open",
  "current_time": "2026-01-03T10:30:00Z",
  "open_time": "09:00",
  "close_time": "15:30",
  "is_trading_day": true,
  "message": "정규장 운영 중"
}
```

**Status Values:**

| 상태 | 설명 |
|------|------|
| `pre_market` | 장전 |
| `open` | 정규장 |
| `break` | 점심시간 (해당 없음) |
| `closed` | 장마감 |
| `holiday` | 휴장일 |

---

### 거래일 확인

```http
GET /api/kiwoom/market/trading-days
```

**Query Parameters:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `month` | string | 조회 월 (YYYYMM) |

**Response:**

```json
{
  "month": "202601",
  "trading_days": ["20260102", "20260103", "20260106", "..."],
  "holidays": [
    {"date": "20260101", "name": "신정"}
  ]
}
```

---

## 에러 코드

| 코드 | 설명 |
|------|------|
| `AUTH_FAILED` | 인증 실패 |
| `INVALID_TICKER` | 잘못된 종목 코드 |
| `INSUFFICIENT_BALANCE` | 잔고 부족 |
| `MARKET_CLOSED` | 장 마감 |
| `ORDER_REJECTED` | 주문 거부 |
| `QUANTITY_LIMIT` | 수량 제한 초과 |
| `PRICE_LIMIT` | 가격 제한 초과 |

---

## 사용 예시

### Python

```python
import requests

BASE_URL = "http://localhost:8000/api/kiwoom"

# 현재가 조회
price = requests.get(f"{BASE_URL}/../kr-stocks/005930/price").json()
print(f"삼성전자: {price['price']:,}원")

# 매수 주문
order = requests.post(
    f"{BASE_URL}/order/buy",
    json={
        "ticker": "005930",
        "quantity": 10,
        "order_type": "market"
    }
).json()
print(f"주문번호: {order['order_id']}")

# 잔고 확인
balance = requests.get(f"{BASE_URL}/account/balance").json()
print(f"가용 잔고: {balance['available_balance']:,}원")
```

---

## 주의사항

1. **모의투자 테스트**: 실거래 전 반드시 모의투자에서 충분한 테스트
2. **호가 확인**: 주문 전 호가창 확인 권장
3. **장 운영 시간**: 09:00-15:30 (한국 시간)
4. **API 제한**: 초당 요청 수 제한 있음
5. **계좌 보안**: API 키 및 계좌 정보 보안 유의

---

## 다음 단계

- [Trading API](trading.md): 자동매매 API
- [Analysis API](analysis.md): 분석 API
- [WebSocket API](websocket.md): 실시간 통신
