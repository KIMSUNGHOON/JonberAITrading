# Analysis Guide

종목 분석 사용 가이드

---

## 개요

JonberAI Trading의 분석 기능은 4개의 전문 AI 에이전트가 병렬로 분석을 수행하여 종합적인 매매 신호를 제공합니다.

---

## 분석 시작하기

### Web UI 사용

1. 좌측 사이드바에서 **Analysis** 메뉴 선택
2. 종목 입력란에 종목 코드 입력
   - 한국 주식: `005930` (삼성전자)
   - 암호화폐: `KRW-BTC`
3. **Analyze** 버튼 클릭

### API 사용

```bash
# 한국 주식 분석
curl -X POST http://localhost:8000/api/kr-stocks/analyze \
  -H "Content-Type: application/json" \
  -d '{"stk_cd": "005930"}'

# 암호화폐 분석
curl -X POST http://localhost:8000/api/coin/analyze \
  -H "Content-Type: application/json" \
  -d '{"market": "KRW-BTC"}'
```

---

## 분석 과정

### 1. 데이터 수집

- 주가 데이터 (OHLCV)
- 기술적 지표 (RSI, MACD, 등)
- 재무 데이터 (PER, PBR, ROE, 등)
- 뉴스 기사

### 2. 에이전트 분석 (병렬 실행)

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Technical   │  │ Fundamental  │  │  Sentiment   │  │     Risk     │
│   Analyst    │  │   Analyst    │  │   Analyst    │  │   Assessor   │
│              │  │              │  │              │  │              │
│ 기술적 지표  │  │  재무 분석   │  │  감성 분석   │  │  리스크 평가 │
│   분석       │  │              │  │              │  │              │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                  │                  │                  │
       └──────────────────┴──────────────────┴──────────────────┘
                                   │
                                   ▼
                          ┌──────────────┐
                          │   Synthesis  │
                          │    Agent     │
                          │              │
                          │ 종합 분석 및 │
                          │  매매 결정   │
                          └──────────────┘
```

### 3. 실시간 로그

분석 진행 중 실시간으로 각 에이전트의 추론 과정이 표시됩니다:

```
[Technical] RSI 분석 중...
[Technical] RSI: 35.2 - 과매도 영역 근접
[Technical] MACD 히스토그램 양전환 확인
[Fundamental] PER 12.5 - 업종 평균 대비 저평가
[Sentiment] 최근 뉴스 긍정적 (15건 중 10건 호재)
[Risk] 리스크 점수: 4/10 (낮음)
[Synthesis] 종합 분석 완료 - BUY 신호 (신뢰도 75%)
```

---

## 분석 결과 이해하기

### 에이전트별 결과

각 에이전트는 다음 정보를 제공합니다:

| 항목 | 설명 |
|------|------|
| **Signal** | BUY, SELL, HOLD 중 하나 |
| **Confidence** | 신뢰도 (0-100%) |
| **Summary** | 분석 요약 |
| **Key Factors** | 핵심 근거 목록 |

### Technical Analyst 결과 예시

```json
{
  "signal": "BUY",
  "confidence": 72,
  "summary": "RSI 과매도, MACD 골든크로스, 20일선 지지",
  "indicators": {
    "rsi": 35.2,
    "macd_histogram": 0.5,
    "trend": "bullish"
  },
  "key_factors": [
    "RSI 35.2 - 과매도 영역",
    "MACD 히스토그램 양전환",
    "20일 이동평균선 지지 확인"
  ]
}
```

### Fundamental Analyst 결과 예시

```json
{
  "signal": "BUY",
  "confidence": 68,
  "summary": "저평가, 양호한 재무건전성",
  "metrics": {
    "per": 12.5,
    "pbr": 1.2,
    "roe": 15.3
  },
  "key_factors": [
    "PER 12.5 - 업종 평균 15.0 대비 저평가",
    "ROE 15.3% - 업종 상위권",
    "부채비율 45% - 안정적"
  ]
}
```

---

## 매매 제안 (Trade Proposal)

### 제안 항목

| 항목 | 설명 |
|------|------|
| **Action** | BUY, SELL, HOLD, WATCH, AVOID |
| **Entry Price** | 진입가 |
| **Quantity** | 추천 수량 |
| **Stop Loss** | 손절가 |
| **Take Profit** | 익절가 |
| **Risk Score** | 리스크 점수 (1-10) |
| **Rationale** | 매매 근거 |

### 제안 예시

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 매매 제안: 삼성전자 (005930)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ 액션: BUY
▶ 진입가: 72,000원
▶ 수량: 10주
▶ 손절가: 69,000원 (-4.2%)
▶ 익절가: 78,000원 (+8.3%)
▶ 리스크: 4/10

📝 근거:
- 기술적: RSI 과매도, MACD 골든크로스
- 펀더멘털: PER 저평가, 높은 ROE
- 감성: 뉴스 긍정적, 업종 상승세
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 승인/거부 결정

### 승인 (Approve)

- Trade Queue에 추가됨
- 장 시간에 자동 실행
- Telegram/WebSocket 알림 발송

### 거부 (Reject)

- 피드백과 함께 재분석 요청 가능
- 피드백은 에이전트에게 전달되어 재분석 시 반영

### 수정 (Modify)

- 수량, 손절가, 익절가 수정 가능
- 수정된 값으로 실행

### 취소 (Cancel)

- 분석 세션 종료
- 아무 액션도 취하지 않음

---

## 팁과 주의사항

!!! tip "최적의 분석 시간"
    - 장 시작 전 (08:30-09:00): 전일 마감 데이터 기반 분석
    - 장 중 (09:00-15:30): 실시간 데이터 반영
    - 장 마감 후: 당일 종가 기반 분석

!!! warning "리스크 관리"
    - 높은 리스크 점수(7+)의 종목은 신중하게 판단
    - 손절가는 반드시 설정된 가격 이하에서 유지
    - 한 종목에 과도한 비중 투자 자제

!!! info "신뢰도 해석"
    - 80%+: 강한 신호, 높은 신뢰
    - 60-80%: 보통 신호
    - 60% 미만: 약한 신호, 추가 검토 필요

---

## 다음 단계

- [Auto Trading Guide](trading.md): 자동매매 설정
- [Agent Chat Guide](agent-chat.md): Agent Group Chat 사용법
- [Notifications Guide](notifications.md): 알림 설정
