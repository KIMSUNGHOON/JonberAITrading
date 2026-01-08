# Notifications Guide

알림 설정 가이드

---

## 개요

JonberAI Trading은 두 가지 알림 채널을 지원합니다:

1. **Telegram**: 모바일/데스크톱 푸시 알림
2. **WebSocket**: 웹 UI 실시간 토스트 알림

---

## Telegram 알림

### 봇 생성

1. Telegram에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령 입력
3. 봇 이름 및 username 설정
4. **Bot Token** 저장

### Chat ID 확인

1. 생성한 봇과 대화 시작 (`/start` 입력)
2. 브라우저에서 접속:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. 응답에서 `chat.id` 확인

### 환경 변수 설정

`.env` 파일:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
TELEGRAM_ENABLED=true
```

### 알림 종류별 설정

```env
# 거래 관련 알림
TELEGRAM_NOTIFY_TRADE_ALERTS=true

# 포지션 업데이트 알림
TELEGRAM_NOTIFY_POSITION_UPDATES=true

# 분석 완료 알림
TELEGRAM_NOTIFY_ANALYSIS_COMPLETE=true

# 시스템 상태 알림
TELEGRAM_NOTIFY_SYSTEM_STATUS=true
```

### 알림 예시

**거래 제안**:
```
📊 매매 제안: 삼성전자 (005930)
━━━━━━━━━━━━━━━━━━━
▶ 액션: BUY
▶ 진입가: 72,000원
▶ 수량: 10주
▶ 손절가: 69,000원
▶ 익절가: 78,000원
▶ 리스크: 4/10

📝 근거:
기술적 과매도, 펀더멘털 저평가
```

**거래 체결**:
```
✅ 거래 체결
━━━━━━━━━━━━━━━━━━━
종목: 삼성전자 (005930)
액션: BUY
수량: 10주
체결가: 72,100원
총액: 721,000원
```

**손절 발동**:
```
🔴 손절 발동
━━━━━━━━━━━━━━━━━━━
종목: 삼성전자 (005930)
트리거가: 68,900원
손절가: 69,000원
손실: -31,000원 (-4.3%)
```

**익절 발동**:
```
🟢 익절 발동
━━━━━━━━━━━━━━━━━━━
종목: 삼성전자 (005930)
트리거가: 78,100원
익절가: 78,000원
수익: +60,000원 (+8.3%)
```

---

## WebSocket 알림

### 자동 연결

Frontend 앱 실행 시 자동으로 WebSocket 연결됩니다.

### 알림 UI

```
┌────────────────────────────────────┐
│ ✅ BUY 삼성전자: 10주 @ 72,000원   │
│    10:30                           │
│                               [X]  │
└────────────────────────────────────┘
```

### 알림 타입별 스타일

| 타입 | 색상 | 아이콘 |
|------|------|--------|
| `trade_executed` | 초록 | ✅ |
| `trade_queued` | 파랑 | ⏰ |
| `trade_rejected` | 주황 | ⚠️ |
| `watch_added` | 파랑 | 👁️ |
| `stop_loss_triggered` | 빨강 | 📉 |
| `take_profit_triggered` | 초록 | 📈 |

### 알림 설정

`App.tsx`에서 설정:

```tsx
<TradeNotificationToast
  maxToasts={5}        // 최대 표시 개수
  duration={5000}      // 자동 닫힘 시간 (ms)
  position="top-right" // 위치
/>
```

### 위치 옵션

- `top-right` (기본)
- `top-center`
- `bottom-right`
- `bottom-center`

---

## 알림 테스트

### Telegram 테스트

```bash
curl -X POST http://localhost:8000/api/telegram/test \
  -H "Content-Type: application/json" \
  -d '{"message": "테스트 메시지입니다."}'
```

### WebSocket 테스트

브라우저 콘솔에서:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/trade-notifications');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## 문제 해결

### Telegram 알림이 오지 않는 경우

1. Bot Token 확인
2. Chat ID 확인
3. `TELEGRAM_ENABLED=true` 확인
4. 봇과 대화를 시작했는지 확인

### WebSocket 연결 실패

1. Backend 서버 실행 확인
2. 브라우저 콘솔에서 오류 확인
3. WebSocket URL 확인 (`ws://localhost:8000`)

### 알림이 중복되는 경우

- 여러 탭에서 앱 실행 중인지 확인
- 각 탭마다 독립적인 WebSocket 연결

---

## 고급 설정

### 알림 필터링

특정 종목만 알림:

```python
# backend/services/telegram/config.py
NOTIFY_TICKERS = ["005930", "000660"]  # 삼성전자, SK하이닉스만
```

### 무음 시간 설정

특정 시간대 알림 무음:

```python
QUIET_HOURS_START = "22:00"
QUIET_HOURS_END = "08:00"
```

---

## 다음 단계

- [Analysis Guide](analysis.md): 분석 기능
- [Trading Guide](trading.md): 자동매매
- [Agent Chat Guide](agent-chat.md): Agent Group Chat
