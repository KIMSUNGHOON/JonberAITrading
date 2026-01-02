# Auto Trading Guide

자동매매 사용 가이드

---

## 개요

JonberAI Trading의 자동매매 시스템은 분석 결과를 기반으로 매매를 실행하고, 포지션을 모니터링하며, 손절/익절을 자동으로 관리합니다.

---

## 시스템 시작하기

### Trading Dashboard 접근

1. 좌측 사이드바에서 **Auto Trading** 메뉴 선택
2. Trading Dashboard 화면 확인

### 시스템 활성화

```
┌────────────────────────────────────────────┐
│  Trading System                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  Start   │ │  Pause   │ │   Stop   │   │
│  └──────────┘ └──────────┘ └──────────┘   │
│                                            │
│  Status: [Stopped] → [Active]              │
└────────────────────────────────────────────┘
```

**버튼 설명**:
- **Start**: 시스템 활성화
- **Pause**: 일시정지 (모니터링 유지, 신규 주문 중지)
- **Stop**: 완전 중지

---

## Trade Queue

### 개요

Trade Queue는 실행 대기 중인 매매 주문 목록입니다.

### 상태

| 상태 | 설명 | 색상 |
|------|------|------|
| `PENDING` | 대기 중 | 노랑 |
| `EXECUTING` | 실행 중 | 파랑 |
| `COMPLETED` | 완료 | 초록 |
| `FAILED` | 실패 | 빨강 |
| `CANCELLED` | 취소됨 | 회색 |

### Queue 항목 예시

```
┌────────────────────────────────────────────┐
│  Trade Queue                               │
├────────────────────────────────────────────┤
│  1. 삼성전자 (005930)                      │
│     BUY 10주 @ 72,000원                    │
│     상태: PENDING                          │
│     예상 실행: 09:00 (장 시작)             │
│     [취소]                                 │
├────────────────────────────────────────────┤
│  2. SK하이닉스 (000660)                    │
│     BUY 5주 @ 180,000원                    │
│     상태: PENDING                          │
│     예상 실행: 09:00 (장 시작)             │
│     [취소]                                 │
└────────────────────────────────────────────┘
```

### 장 마감 시 동작

- 장 마감 후 승인된 주문은 다음 장 시작 시 실행
- 대기 시간 및 예상 실행 시간 표시
- 카운트다운 타이머 제공

---

## 포지션 관리

### 현재 포지션

```
┌────────────────────────────────────────────┐
│  Active Positions                          │
├────────────────────────────────────────────┤
│  삼성전자 (005930)                         │
│  ├─ 수량: 10주                             │
│  ├─ 평균단가: 72,000원                     │
│  ├─ 현재가: 73,500원                       │
│  ├─ 손익: +15,000원 (+2.08%)               │
│  ├─ 손절가: 69,000원                       │
│  └─ 익절가: 78,000원                       │
└────────────────────────────────────────────┘
```

### 손절/익절 모니터링

시스템이 자동으로 모니터링:

1. **손절 (Stop-Loss)**
   - 현재가가 손절가 이하로 하락 시 자동 매도
   - Telegram/WebSocket 알림 발송

2. **익절 (Take-Profit)**
   - 현재가가 익절가 이상으로 상승 시 자동 매도
   - Telegram/WebSocket 알림 발송

---

## 포트폴리오 현황

### 자산 요약

```
┌────────────────────────────────────────────┐
│  Portfolio Summary                         │
├────────────────────────────────────────────┤
│  총 자산: 10,000,000원                     │
│  ├─ 예수금: 7,500,000원                    │
│  └─ 주식평가: 2,500,000원                  │
│                                            │
│  일일 손익: +50,000원 (+0.50%)             │
│  총 손익: +150,000원 (+1.50%)              │
└────────────────────────────────────────────┘
```

---

## 리스크 설정

### 기본 파라미터

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| Stop-Loss % | 3% | 기본 손절 비율 |
| Take-Profit % | 5% | 기본 익절 비율 |
| Max Position % | 10% | 종목당 최대 비중 |
| Max Daily Trades | 10 | 일일 최대 거래 수 |

### 파라미터 수정

API를 통해 수정 가능:

```bash
curl -X PUT http://localhost:8000/api/trading/settings \
  -H "Content-Type: application/json" \
  -d '{
    "stop_loss_pct": 3.0,
    "take_profit_pct": 5.0,
    "max_position_pct": 10.0
  }'
```

---

## Watch List

### 개요

Watch List는 매수 타이밍을 기다리는 관심 종목 목록입니다.

### 추가 방법

1. 분석 결과에서 WATCH 액션 승인
2. 수동으로 API 호출

### Watch List → Trade Queue 변환

관심 종목이 매수 조건을 충족하면 Trade Queue로 이동:

```bash
curl -X POST http://localhost:8000/api/trading/watch-list/convert \
  -H "Content-Type: application/json" \
  -d '{"ticker": "005930"}'
```

---

## 알림 설정

### Telegram 알림

`.env` 파일에서 설정:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ENABLED=true
TELEGRAM_NOTIFY_TRADE_ALERTS=true
TELEGRAM_NOTIFY_POSITION_UPDATES=true
```

### WebSocket 알림

Frontend에서 자동 연결. 추가 설정 불필요.

---

## 주의사항

!!! danger "실거래 전환"
    `KIWOOM_IS_MOCK=false` 설정 시 실제 자금으로 거래됩니다.
    충분한 모의투자 테스트 후 전환하세요.

!!! warning "장 시간 확인"
    - 한국 주식: 09:00-15:30 (주말/공휴일 휴장)
    - 암호화폐: 24시간 (연중무휴)

!!! tip "리스크 관리"
    - 초기에는 작은 금액으로 시작
    - 손절가는 반드시 설정
    - 한 종목에 과도한 비중 투자 자제

---

## 문제 해결

### 주문이 실행되지 않는 경우

1. 시스템 상태 확인 (Active 인지)
2. 장 시간 확인
3. 잔고 확인
4. API 연결 상태 확인

### 손절/익절이 작동하지 않는 경우

1. Risk Monitor 상태 확인
2. 포지션이 정상 등록되었는지 확인
3. 현재가 조회 API 상태 확인

---

## 다음 단계

- [Agent Chat Guide](agent-chat.md): Agent Group Chat
- [Notifications Guide](notifications.md): 알림 설정 상세
- [API Reference](../api/trading.md): Trading API 상세
