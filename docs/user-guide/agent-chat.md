# Agent Group Chat Guide

Agent Group Chat 사용 가이드

---

## 개요

Agent Group Chat은 AI 에이전트들이 토론하고 합의하여 매매 결정을 내리는 시스템입니다. 사용자는 토론 과정을 실시간으로 관찰하고, 최종 결정에 대해 승인/거부할 수 있습니다.

---

## 접근 방법

1. 좌측 사이드바에서 **Agent Chat** 메뉴 선택
2. Agent Chat Dashboard 화면 확인

---

## Dashboard 구성

```
┌─────────────────────────────────────────────────────────────┐
│  Agent Chat Dashboard                                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │  Coordinator Status     │  │  Active Sessions         │  │
│  │  ├─ Status: Active      │  │  ├─ Session 1: 삼성전자  │  │
│  │  ├─ Watch List: 5종목   │  │  │   진행중 (3/4 투표)   │  │
│  │  └─ Positions: 2개      │  │  ├─ Session 2: SK하이닉스│  │
│  │                         │  │  │   완료 (BUY 합의)     │  │
│  │  [Start] [Stop]         │  │  └─ ...                  │  │
│  └─────────────────────────┘  └──────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Chat Session Viewer                                  │   │
│  │  ──────────────────────────────────────────────────── │   │
│  │  [Technical Agent] RSI 35.2로 과매도 영역입니다.      │   │
│  │  단기 반등 가능성이 높습니다.                         │   │
│  │                                                        │   │
│  │  [Fundamental Agent] PER 12.5로 저평가 상태입니다.    │   │
│  │  재무 건전성도 양호합니다.                            │   │
│  │                                                        │   │
│  │  [Sentiment Agent] 최근 뉴스가 긍정적입니다.          │   │
│  │  업종 전반적으로 상승세입니다.                        │   │
│  │                                                        │   │
│  │  [Risk Agent] 리스크 점수 4/10으로 낮습니다.          │   │
│  │  손절가 69,000원, 익절가 78,000원 제안합니다.         │   │
│  │  ──────────────────────────────────────────────────── │   │
│  │  [Moderator] 투표를 시작합니다.                       │   │
│  │  BUY: 4표, SELL: 0표, HOLD: 0표                       │   │
│  │  → BUY 합의 (만장일치)                                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 시스템 시작/중지

### 시작

```bash
curl -X POST http://localhost:8000/api/agent-chat/start
```

또는 Dashboard의 **Start** 버튼 클릭

### 중지

```bash
curl -X POST http://localhost:8000/api/agent-chat/stop
```

또는 Dashboard의 **Stop** 버튼 클릭

---

## 토론 프로세스

### 1. 기회 감지

Coordinator가 Watch List를 5분마다 모니터링하여 투자 기회 감지:

- 가격 변동 감지
- 기술적 지표 변화
- 뉴스/이슈 발생

### 2. 토론 시작

Moderator Agent가 토론 세션을 시작:

```
[Moderator] 삼성전자(005930)에 대한 토론을 시작합니다.
현재가: 72,000원, 전일대비: +1.5%
각 Agent는 분석 결과를 공유해주세요.
```

### 3. 에이전트 의견 제시

각 전문 에이전트가 순차적으로 의견 제시:

```
[Technical Agent]
- RSI: 35.2 (과매도)
- MACD: 골든크로스 임박
- 추세: 하락 후 반등 시도
→ 의견: BUY (신뢰도 72%)

[Fundamental Agent]
- PER: 12.5 (저평가)
- ROE: 15.3% (양호)
- 부채비율: 45% (안정)
→ 의견: BUY (신뢰도 68%)

[Sentiment Agent]
- 뉴스 감성: 긍정적
- 최근 15건 중 10건 호재
- 업종 동향: 상승세
→ 의견: BUY (신뢰도 65%)

[Risk Agent]
- 리스크 점수: 4/10 (낮음)
- 변동성: 보통
- 제안 손절가: 69,000원
- 제안 익절가: 78,000원
→ 의견: BUY (신뢰도 70%)
```

### 4. 토론 및 반론

에이전트 간 의견 교환:

```
[Technical Agent]
Fundamental Agent의 저평가 분석에 동의합니다.
기술적으로도 지지선 근처에서 반등 신호가 보입니다.

[Risk Agent]
다만 시장 전반적인 불확실성을 고려하여
포지션 크기는 보수적으로 5%를 제안합니다.
```

### 5. 투표

Moderator가 투표 진행:

```
[Moderator] 투표를 시작합니다.
- BUY: Technical(72%), Fundamental(68%), Sentiment(65%), Risk(70%)
- SELL: 없음
- HOLD: 없음

결과: BUY 만장일치 (평균 신뢰도 68.75%)
```

### 6. 합의 및 결정

과반수 합의 시 매매 결정 도출:

```
[Moderator] 합의가 이루어졌습니다.
결정: BUY 삼성전자(005930)
- 진입가: 72,000원
- 수량: 10주
- 손절가: 69,000원
- 익절가: 78,000원

사용자 승인을 기다립니다...
```

---

## 수동 토론 시작

특정 종목에 대해 수동으로 토론 시작:

```bash
curl -X POST http://localhost:8000/api/agent-chat/discuss \
  -H "Content-Type: application/json" \
  -d '{"ticker": "005930"}'
```

---

## 세션 히스토리

완료된 토론 세션 조회:

```bash
curl http://localhost:8000/api/agent-chat/sessions
```

응답 예시:

```json
{
  "sessions": [
    {
      "id": "session-123",
      "ticker": "005930",
      "stock_name": "삼성전자",
      "decision": "BUY",
      "consensus_rate": 100,
      "confidence": 68.75,
      "created_at": "2026-01-03T10:00:00Z",
      "completed_at": "2026-01-03T10:05:00Z"
    }
  ]
}
```

---

## 포지션 모니터링

Agent Chat에서 관리 중인 포지션:

```bash
curl http://localhost:8000/api/agent-chat/positions
```

```json
{
  "positions": [
    {
      "ticker": "005930",
      "stock_name": "삼성전자",
      "quantity": 10,
      "entry_price": 72000,
      "current_price": 73500,
      "pnl": 15000,
      "pnl_percent": 2.08,
      "stop_loss": 69000,
      "take_profit": 78000
    }
  ]
}
```

---

## WebSocket 실시간 스트림

토론 세션 실시간 구독:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/agent-chat/ws/session-123');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log(message);
  // { type: 'message', agent: 'Technical Agent', content: '...' }
  // { type: 'vote', results: { BUY: 4, SELL: 0, HOLD: 0 } }
  // { type: 'decision', action: 'BUY', ... }
};
```

---

## 설정

### Coordinator 설정

| 설정 | 설명 | 기본값 |
|------|------|--------|
| 모니터링 주기 | Watch List 체크 간격 | 5분 |
| 최소 합의율 | 결정을 위한 최소 합의 비율 | 50% |
| 토론 타임아웃 | 최대 토론 시간 | 10분 |

---

## 다음 단계

- [Notifications Guide](notifications.md): 알림 설정
- [Analysis Guide](analysis.md): 분석 기능
- [Trading Guide](trading.md): 자동매매
