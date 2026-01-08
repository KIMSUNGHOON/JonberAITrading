# Analysis API

분석 API 레퍼런스

---

## 개요

분석 API는 주식 종목에 대한 AI 기반 분석을 수행합니다. 다중 에이전트가 기술적, 펀더멘털, 감성 분석을 병렬로 수행하고 종합 의견을 제공합니다.

---

## Endpoints

### 분석 시작

```http
POST /api/kr-stocks/analyze
```

**Request Body:**

```json
{
  "stk_cd": "005930"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `stk_cd` | string | Yes | 종목 코드 (6자리) |

**Response:**

```json
{
  "session_id": "session-abc123",
  "status": "analyzing",
  "message": "분석이 시작되었습니다."
}
```

---

### 세션 상태 조회

```http
GET /api/kr-stocks/sessions/{session_id}
```

**Response:**

```json
{
  "session_id": "session-abc123",
  "status": "awaiting_approval",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "created_at": "2026-01-03T10:00:00Z",
  "analysis": {
    "technical": {
      "signal": "BUY",
      "confidence": 0.72,
      "indicators": {
        "rsi": 35.2,
        "macd": "golden_cross",
        "trend": "reversal"
      },
      "summary": "RSI 과매도, MACD 골든크로스 임박"
    },
    "fundamental": {
      "signal": "BUY",
      "confidence": 0.68,
      "metrics": {
        "per": 12.5,
        "pbr": 1.2,
        "roe": 15.3
      },
      "summary": "저평가 상태, 재무 건전성 양호"
    },
    "sentiment": {
      "signal": "BUY",
      "confidence": 0.65,
      "news_sentiment": "positive",
      "summary": "최근 뉴스 긍정적, 업종 상승세"
    },
    "risk": {
      "score": 4,
      "max_score": 10,
      "stop_loss": 69000,
      "take_profit": 78000,
      "position_size_percent": 5
    }
  },
  "recommendation": {
    "action": "BUY",
    "confidence": 0.69,
    "entry_price": 72000,
    "quantity": 10,
    "stop_loss": 69000,
    "take_profit": 78000,
    "rationale": "기술적 과매도, 펀더멘털 저평가, 긍정적 뉴스"
  }
}
```

**Status Values:**

| 상태 | 설명 |
|------|------|
| `analyzing` | 분석 진행 중 |
| `awaiting_approval` | 사용자 승인 대기 |
| `approved` | 승인됨 (실행 대기) |
| `rejected` | 거부됨 |
| `executed` | 실행 완료 |
| `failed` | 분석 실패 |

---

### 모든 세션 조회

```http
GET /api/kr-stocks/sessions
```

**Query Parameters:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `status` | string | - | 상태 필터 |
| `limit` | int | 20 | 반환 개수 |
| `offset` | int | 0 | 시작 위치 |

**Response:**

```json
{
  "sessions": [
    {
      "session_id": "session-abc123",
      "ticker": "005930",
      "stock_name": "삼성전자",
      "status": "awaiting_approval",
      "created_at": "2026-01-03T10:00:00Z"
    }
  ],
  "total": 15,
  "limit": 20,
  "offset": 0
}
```

---

### 분석 취소

```http
DELETE /api/kr-stocks/sessions/{session_id}
```

**Response:**

```json
{
  "session_id": "session-abc123",
  "status": "cancelled",
  "message": "분석이 취소되었습니다."
}
```

---

## WebSocket 실시간 업데이트

### 분석 진행 상황 구독

```javascript
const ws = new WebSocket('ws://localhost:8000/api/kr-stocks/ws/{session_id}');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

**Message Types:**

```json
// 에이전트 시작
{
  "type": "agent_start",
  "agent": "technical",
  "timestamp": "2026-01-03T10:00:05Z"
}

// 에이전트 진행
{
  "type": "agent_progress",
  "agent": "technical",
  "progress": 50,
  "message": "RSI 분석 중..."
}

// 에이전트 완료
{
  "type": "agent_complete",
  "agent": "technical",
  "result": {
    "signal": "BUY",
    "confidence": 0.72
  }
}

// 분석 완료
{
  "type": "analysis_complete",
  "recommendation": { ... }
}
```

---

## 분석 옵션

### 상세 분석 요청

```http
POST /api/kr-stocks/analyze
```

```json
{
  "stk_cd": "005930",
  "options": {
    "include_news": true,
    "include_financials": true,
    "lookback_days": 90,
    "technical_indicators": ["RSI", "MACD", "BB", "SMA"],
    "risk_tolerance": "moderate"
  }
}
```

| 옵션 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `include_news` | bool | true | 뉴스 분석 포함 |
| `include_financials` | bool | true | 재무 분석 포함 |
| `lookback_days` | int | 60 | 기술 분석 기간 |
| `technical_indicators` | array | all | 사용할 지표 |
| `risk_tolerance` | string | moderate | 리스크 허용도 |

---

## 에러 응답

```json
{
  "error": {
    "code": "ANALYSIS_FAILED",
    "message": "분석 중 오류가 발생했습니다.",
    "details": "Market data unavailable"
  }
}
```

| 에러 코드 | HTTP 상태 | 설명 |
|-----------|-----------|------|
| `INVALID_TICKER` | 400 | 잘못된 종목 코드 |
| `SESSION_NOT_FOUND` | 404 | 세션을 찾을 수 없음 |
| `ANALYSIS_FAILED` | 500 | 분석 실패 |
| `MARKET_CLOSED` | 503 | 장 마감 (실시간 데이터 불가) |

---

## 사용 예시

### Python

```python
import requests

# 분석 시작
response = requests.post(
    "http://localhost:8000/api/kr-stocks/analyze",
    json={"stk_cd": "005930"}
)
session_id = response.json()["session_id"]

# 결과 확인
result = requests.get(
    f"http://localhost:8000/api/kr-stocks/sessions/{session_id}"
)
print(result.json())
```

### JavaScript

```javascript
// 분석 시작
const response = await fetch('/api/kr-stocks/analyze', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ stk_cd: '005930' })
});
const { session_id } = await response.json();

// WebSocket으로 실시간 업데이트
const ws = new WebSocket(`ws://localhost:8000/api/kr-stocks/ws/${session_id}`);
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## 다음 단계

- [Trading API](trading.md): 거래 API
- [WebSocket API](websocket.md): 실시간 통신
- [Approval API](../architecture/trading-system.md): 승인 워크플로우
