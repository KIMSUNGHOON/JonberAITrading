# API Reference

JonberAI Trading API 문서

---

## 개요

JonberAI Trading은 RESTful API와 WebSocket을 통해 모든 기능을 제공합니다.

**Base URL**: `http://localhost:8000`

**Swagger UI**: `http://localhost:8000/docs`

---

## 인증

현재 버전에서는 로컬 환경을 대상으로 하므로 인증이 필요하지 않습니다.

---

## API 구조

### 분석 API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/kr-stocks/analyze` | POST | 한국 주식 분석 시작 |
| `/api/kr-stocks/sessions` | GET | 세션 목록 |
| `/api/kr-stocks/sessions/{id}` | GET | 세션 상세 |
| `/api/kr-stocks/sessions/{id}/cancel` | POST | 세션 취소 |
| `/api/coin/analyze` | POST | 코인 분석 시작 |
| `/api/coin/sessions` | GET | 코인 세션 목록 |

### 자동매매 API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/trading/status` | GET | 시스템 상태 |
| `/api/trading/start` | POST | 시작 |
| `/api/trading/stop` | POST | 중지 |
| `/api/trading/pause` | POST | 일시정지 |
| `/api/trading/resume` | POST | 재개 |
| `/api/trading/queue` | GET | Trade Queue |
| `/api/trading/portfolio` | GET | 포트폴리오 |
| `/api/trading/positions` | GET | 포지션 |
| `/api/trading/market-status` | GET | 장 상태 |

### 승인 API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/approval/pending` | GET | 대기 중인 승인 목록 |
| `/api/approval/pending/{id}` | GET | 승인 상세 |
| `/api/approval/decide` | POST | 승인/거부 결정 |

### Agent Chat API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/agent-chat/status` | GET | Coordinator 상태 |
| `/api/agent-chat/start` | POST | 시작 |
| `/api/agent-chat/stop` | POST | 중지 |
| `/api/agent-chat/discuss` | POST | 수동 토론 |
| `/api/agent-chat/sessions` | GET | 세션 히스토리 |
| `/api/agent-chat/positions` | GET | 모니터링 포지션 |

### Watch List API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/trading/watch-list` | GET | Watch List 조회 |
| `/api/trading/watch-list` | POST | Watch List 추가 |
| `/api/trading/watch-list/{ticker}` | DELETE | Watch List 제거 |
| `/api/trading/watch-list/convert` | POST | Trade Queue로 변환 |

### Scanner API

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/scanner/start` | POST | 스캔 시작 |
| `/api/scanner/pause` | POST | 일시정지 |
| `/api/scanner/resume` | POST | 재개 |
| `/api/scanner/stop` | POST | 중지 |
| `/api/scanner/progress` | GET | 진행 상황 |
| `/api/scanner/results` | GET | 스캔 결과 |

---

## WebSocket API

### 분석 세션 스트림

**Endpoint**: `/ws/session/{session_id}`

**메시지 타입**:

| Type | 설명 |
|------|------|
| `reasoning` | 실시간 분석 로그 |
| `status` | 상태 변경 |
| `proposal` | 매매 제안 |
| `position` | 포지션 업데이트 |
| `complete` | 분석 완료 |

**예시**:
```json
{
  "type": "reasoning",
  "data": "RSI 지표 분석 중...",
  "session_id": "abc123"
}
```

### 체결 알림 스트림

**Endpoint**: `/ws/trade-notifications`

**메시지 타입**:

| Type | 설명 |
|------|------|
| `trade_executed` | 체결 완료 |
| `trade_queued` | 대기열 추가 |
| `trade_rejected` | 거래 거부 |
| `watch_added` | 관심종목 추가 |
| `stop_loss_triggered` | 손절 발동 |
| `take_profit_triggered` | 익절 발동 |

**예시**:
```json
{
  "type": "trade_executed",
  "data": {
    "ticker": "005930",
    "stock_name": "삼성전자",
    "action": "BUY",
    "quantity": 10,
    "price": 72000,
    "total_amount": 720000,
    "timestamp": "2026-01-03T10:30:00Z"
  }
}
```

### 실시간 시세 스트림

**Endpoint**: `/ws/ticker`

**구독 메시지**:
```json
{
  "action": "subscribe",
  "markets": ["KRW-BTC", "KRW-ETH"]
}
```

**시세 데이터**:
```json
{
  "type": "ticker",
  "market": "KRW-BTC",
  "trade_price": 145000000,
  "change": "RISE",
  "change_rate": 0.025
}
```

---

## 공통 응답 형식

### 성공 응답

```json
{
  "success": true,
  "data": { ... }
}
```

### 에러 응답

```json
{
  "detail": "Error message",
  "status_code": 400
}
```

---

## 상태 코드

| 코드 | 설명 |
|------|------|
| 200 | 성공 |
| 201 | 생성됨 |
| 400 | 잘못된 요청 |
| 404 | 리소스 없음 |
| 422 | 유효성 검사 실패 |
| 500 | 서버 오류 |

---

## 상세 API 문서

- [Analysis API](analysis.md)
- [Trading API](trading.md)
- [WebSocket API](websocket.md)
- [Kiwoom API Reference](kiwoom.md)
