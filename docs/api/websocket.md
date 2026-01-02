# WebSocket API

WebSocket API 레퍼런스

---

## 개요

WebSocket API는 실시간 양방향 통신을 제공합니다. 분석 진행 상황, 거래 알림, 포지션 업데이트 등을 실시간으로 수신할 수 있습니다.

---

## 엔드포인트

| 엔드포인트 | 설명 |
|------------|------|
| `/ws/trade-notifications` | 거래 알림 |
| `/api/kr-stocks/ws/{session_id}` | 분석 세션 업데이트 |
| `/api/agent-chat/ws/{session_id}` | Agent Chat 메시지 |

---

## 거래 알림 WebSocket

### 연결

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/trade-notifications');

ws.onopen = () => {
  console.log('Connected to trade notifications');
};

ws.onmessage = (event) => {
  const notification = JSON.parse(event.data);
  handleNotification(notification);
};

ws.onclose = () => {
  console.log('Disconnected');
  // 재연결 로직
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};
```

### 메시지 타입

#### 연결 확인

```json
{
  "type": "connected",
  "message": "Connected to trade notifications",
  "timestamp": "2026-01-03T10:00:00Z"
}
```

#### 거래 체결 (trade_executed)

```json
{
  "type": "trade_executed",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "action": "BUY",
  "quantity": 10,
  "price": 72100,
  "total_amount": 721000,
  "timestamp": "2026-01-03T10:30:00Z"
}
```

#### 대기열 추가 (trade_queued)

```json
{
  "type": "trade_queued",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "action": "BUY",
  "quantity": 10,
  "target_price": 72000,
  "queue_position": 1,
  "timestamp": "2026-01-03T10:00:00Z"
}
```

#### 거래 거부 (trade_rejected)

```json
{
  "type": "trade_rejected",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "reason": "Insufficient balance",
  "timestamp": "2026-01-03T10:00:00Z"
}
```

#### Watch 추가 (watch_added)

```json
{
  "type": "watch_added",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "reason": "과매도 영역 진입",
  "timestamp": "2026-01-03T10:00:00Z"
}
```

#### 손절 발동 (stop_loss_triggered)

```json
{
  "type": "stop_loss_triggered",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "trigger_price": 68900,
  "stop_loss": 69000,
  "quantity": 10,
  "loss": -31000,
  "loss_percent": -4.3,
  "timestamp": "2026-01-03T10:00:00Z"
}
```

#### 익절 발동 (take_profit_triggered)

```json
{
  "type": "take_profit_triggered",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "trigger_price": 78100,
  "take_profit": 78000,
  "quantity": 10,
  "profit": 60000,
  "profit_percent": 8.3,
  "timestamp": "2026-01-03T10:00:00Z"
}
```

### Ping/Pong

연결 유지를 위한 핑퐁:

```javascript
// 클라이언트에서 ping 전송
ws.send('ping');

// 서버 응답
// "pong"
```

---

## 분석 세션 WebSocket

### 연결

```javascript
const sessionId = 'session-abc123';
const ws = new WebSocket(`ws://localhost:8000/api/kr-stocks/ws/${sessionId}`);
```

### 메시지 타입

#### 에이전트 시작

```json
{
  "type": "agent_start",
  "agent": "technical",
  "agent_name": "Technical Analyst",
  "timestamp": "2026-01-03T10:00:05Z"
}
```

#### 에이전트 진행

```json
{
  "type": "agent_progress",
  "agent": "technical",
  "progress": 50,
  "message": "RSI 분석 중...",
  "timestamp": "2026-01-03T10:00:10Z"
}
```

#### 에이전트 완료

```json
{
  "type": "agent_complete",
  "agent": "technical",
  "result": {
    "signal": "BUY",
    "confidence": 0.72,
    "summary": "RSI 과매도, 반등 예상"
  },
  "timestamp": "2026-01-03T10:00:30Z"
}
```

#### 분석 완료

```json
{
  "type": "analysis_complete",
  "recommendation": {
    "action": "BUY",
    "confidence": 0.69,
    "entry_price": 72000,
    "stop_loss": 69000,
    "take_profit": 78000
  },
  "timestamp": "2026-01-03T10:01:00Z"
}
```

#### 승인 대기

```json
{
  "type": "awaiting_approval",
  "session_id": "session-abc123",
  "timestamp": "2026-01-03T10:01:00Z"
}
```

#### 에러

```json
{
  "type": "error",
  "message": "Analysis failed: Market data unavailable",
  "timestamp": "2026-01-03T10:00:15Z"
}
```

---

## Agent Chat WebSocket

### 연결

```javascript
const chatSessionId = 'chat-xyz789';
const ws = new WebSocket(`ws://localhost:8000/api/agent-chat/ws/${chatSessionId}`);
```

### 메시지 타입

#### 채팅 메시지

```json
{
  "type": "message",
  "agent": "Technical Agent",
  "content": "RSI 35.2로 과매도 영역입니다. 단기 반등 가능성이 높습니다.",
  "timestamp": "2026-01-03T10:00:10Z"
}
```

#### 투표 시작

```json
{
  "type": "vote_start",
  "message": "투표를 시작합니다.",
  "timestamp": "2026-01-03T10:02:00Z"
}
```

#### 투표 결과

```json
{
  "type": "vote",
  "results": {
    "BUY": 4,
    "SELL": 0,
    "HOLD": 0
  },
  "consensus": true,
  "consensus_rate": 100,
  "timestamp": "2026-01-03T10:02:30Z"
}
```

#### 결정

```json
{
  "type": "decision",
  "action": "BUY",
  "ticker": "005930",
  "stock_name": "삼성전자",
  "entry_price": 72000,
  "quantity": 10,
  "stop_loss": 69000,
  "take_profit": 78000,
  "confidence": 68.75,
  "timestamp": "2026-01-03T10:03:00Z"
}
```

---

## React Hook 사용 예시

### useTradeNotifications

```tsx
import { useTradeNotifications } from '@/hooks/useTradeNotifications';

function TradingDashboard() {
  const { notifications, isConnected, clearNotification } = useTradeNotifications();

  return (
    <div>
      <span>Status: {isConnected ? 'Connected' : 'Disconnected'}</span>

      {notifications.map((notification) => (
        <div key={notification.id}>
          <span>{notification.type}: {notification.ticker}</span>
          <button onClick={() => clearNotification(notification.id)}>
            Close
          </button>
        </div>
      ))}
    </div>
  );
}
```

### 커스텀 WebSocket Hook

```tsx
function useAnalysisSession(sessionId: string) {
  const [messages, setMessages] = useState<any[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    const ws = new WebSocket(
      `ws://localhost:8000/api/kr-stocks/ws/${sessionId}`
    );

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages((prev) => [...prev, data]);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [sessionId]);

  return { messages };
}
```

---

## 연결 관리

### 자동 재연결

```javascript
class WebSocketClient {
  constructor(url) {
    this.url = url;
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      console.log('Connected');
    };

    this.ws.onclose = () => {
      console.log('Disconnected, reconnecting...');
      setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(
        this.reconnectDelay * 2,
        this.maxReconnectDelay
      );
    };
  }
}
```

### 연결 상태 확인

```javascript
// 주기적 핑
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send('ping');
  }
}, 30000);
```

---

## 에러 처리

| 코드 | 설명 |
|------|------|
| 1000 | 정상 종료 |
| 1001 | 서버 종료 |
| 1006 | 비정상 종료 |
| 1011 | 서버 에러 |

```javascript
ws.onclose = (event) => {
  switch (event.code) {
    case 1000:
      console.log('Normal closure');
      break;
    case 1006:
      console.log('Connection lost, reconnecting...');
      reconnect();
      break;
    default:
      console.log(`Closed with code: ${event.code}`);
  }
};
```

---

## 다음 단계

- [Analysis API](analysis.md): 분석 API
- [Trading API](trading.md): 거래 API
- [Kiwoom API](kiwoom.md): 키움 API 연동
