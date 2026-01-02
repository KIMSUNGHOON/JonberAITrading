# Agent System

다중 AI 에이전트 시스템 상세

---

## 개요

JonberAI Trading은 LangGraph 기반의 다중 에이전트 시스템을 사용합니다. 각 에이전트는 전문 영역을 담당하며, 병렬로 분석을 수행한 후 종합하여 매매 결정을 내립니다.

---

## 에이전트 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Analysis Workflow                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Technical   │  │ Fundamental  │  │  Sentiment   │       │
│  │   Analyst    │  │   Analyst    │  │   Analyst    │       │
│  │              │  │              │  │              │       │
│  │ - RSI, MACD  │  │ - PER, PBR   │  │ - 뉴스 분석  │       │
│  │ - 이동평균   │  │ - ROE, EPS   │  │ - 시장 심리  │       │
│  │ - 볼린저밴드 │  │ - 부채비율   │  │ - 애널리스트 │       │
│  │ - 추세 분석  │  │ - 성장성     │  │   리포트     │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            ▼                                 │
│                    ┌──────────────┐                          │
│                    │     Risk     │                          │
│                    │   Assessor   │                          │
│                    │              │                          │
│                    │ - 리스크 점수│                          │
│                    │ - 손절가     │                          │
│                    │ - 익절가     │                          │
│                    │ - 포지션크기 │                          │
│                    └──────┬───────┘                          │
│                           │                                  │
│                           ▼                                  │
│                    ┌──────────────┐                          │
│                    │  Synthesis   │                          │
│                    │   Agent      │                          │
│                    │              │                          │
│                    │ - 종합 분석  │                          │
│                    │ - 매매 결정  │                          │
│                    │ - 근거 정리  │                          │
│                    └──────────────┘                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 에이전트 상세

### Technical Analyst

**역할**: 기술적 지표 분석

**입력 데이터**:
- OHLCV (시가, 고가, 저가, 종가, 거래량)
- 기술적 지표 (RSI, MACD, Stochastic, etc.)

**분석 항목**:

| 지표 | 설명 |
|------|------|
| RSI | 과매수/과매도 판단 (70/30) |
| MACD | 추세 전환 신호 |
| Stochastic | 단기 모멘텀 |
| Bollinger Bands | 변동성 및 지지/저항 |
| 이동평균선 | 추세 방향 (SMA 20, 60, 120) |
| 거래량 | 거래량 추세 |

**출력**:
```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 ~ 1.0,
    "summary": "분석 요약",
    "key_factors": ["factor1", "factor2", ...],
    "signals": {
        "rsi": 35.2,
        "macd_histogram": 0.5,
        "trend": "bullish"
    }
}
```

---

### Fundamental Analyst

**역할**: 재무/펀더멘털 분석

**입력 데이터**:
- 재무제표 (손익계산서, 재무상태표)
- 밸류에이션 지표

**분석 항목**:

| 지표 | 설명 |
|------|------|
| PER | 주가수익비율 |
| PBR | 주가순자산비율 |
| ROE | 자기자본이익률 |
| EPS | 주당순이익 |
| 부채비율 | 재무 안정성 |
| 매출성장률 | 성장성 |

**출력**:
```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 ~ 1.0,
    "summary": "펀더멘털 분석 요약",
    "key_factors": ["저평가", "높은 ROE", ...],
    "signals": {
        "per": 12.5,
        "pbr": 1.2,
        "roe": 15.3
    }
}
```

---

### Sentiment Analyst

**역할**: 시장 심리/뉴스 분석

**입력 데이터**:
- 뉴스 기사 (Naver News API)
- 시장 동향

**분석 항목**:

| 항목 | 설명 |
|------|------|
| 뉴스 감성 | 긍정/부정/중립 비율 |
| 주요 이슈 | 핵심 뉴스 요약 |
| 업종 동향 | 관련 섹터 흐름 |

**출력**:
```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 ~ 1.0,
    "summary": "감성 분석 요약",
    "key_factors": ["호재 뉴스", "업종 상승세", ...],
    "signals": {
        "news_sentiment": "positive",
        "news_count": 15
    }
}
```

---

### Risk Assessor

**역할**: 리스크 평가 및 포지션 사이징

**입력 데이터**:
- 다른 에이전트들의 분석 결과
- 현재 포트폴리오 상태
- 시장 변동성

**분석 항목**:

| 항목 | 설명 |
|------|------|
| 리스크 점수 | 1-10 스케일 |
| 손절가 | 추천 손절 가격 |
| 익절가 | 추천 익절 가격 |
| 포지션 크기 | 추천 투자 비중 |

**출력**:
```python
{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 ~ 1.0,
    "summary": "리스크 분석 요약",
    "key_factors": ["높은 변동성", "지지선 근접", ...],
    "signals": {
        "risk_score": 6,
        "suggested_stop_loss": 49000,
        "suggested_take_profit": 55000,
        "max_position_pct": 5.0
    }
}
```

---

## Agent Group Chat

### 개요

Agent Group Chat은 에이전트들이 토론하고 합의하여 매매 결정을 내리는 시스템입니다.

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Group Chat                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │Technical │  │Fundament.│  │Sentiment │  │   Risk   │    │
│  │  Agent   │  │  Agent   │  │  Agent   │  │  Agent   │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       │             │             │             │           │
│       └─────────────┴─────────────┴─────────────┘           │
│                           │                                  │
│                           ▼                                  │
│                    ┌──────────────┐                          │
│                    │  Moderator   │                          │
│                    │    Agent     │                          │
│                    │              │                          │
│                    │ - 토론 진행  │                          │
│                    │ - 투표 관리  │                          │
│                    │ - 합의 도출  │                          │
│                    └──────────────┘                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 토론 프로세스

1. **기회 감지**: Watch List 모니터링으로 투자 기회 감지
2. **토론 시작**: Moderator가 토론 세션 시작
3. **의견 제시**: 각 Agent가 분석 결과 및 의견 제시
4. **투표**: 매매 방향에 대한 투표
5. **합의 도출**: 과반수 합의 시 매매 결정
6. **실행**: HITL 승인 후 실행

### API 엔드포인트

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/agent-chat/status` | GET | Coordinator 상태 |
| `/api/agent-chat/start` | POST | 시작 |
| `/api/agent-chat/stop` | POST | 중지 |
| `/api/agent-chat/discuss` | POST | 수동 토론 시작 |
| `/api/agent-chat/sessions` | GET | 세션 히스토리 |
| `/api/agent-chat/positions` | GET | 모니터링 포지션 |
| `/api/agent-chat/ws/{id}` | WS | 실시간 스트림 |

---

## LLM 프롬프트 구조

각 에이전트는 전문화된 시스템 프롬프트를 사용합니다:

```python
# 예: Technical Analyst
SYSTEM_PROMPT = """
당신은 기술적 분석 전문가입니다.
주어진 차트 데이터와 기술적 지표를 분석하여 매매 신호를 제공합니다.

분석 항목:
1. 추세 분석 (이동평균선)
2. 모멘텀 지표 (RSI, MACD, Stochastic)
3. 변동성 분석 (Bollinger Bands, ATR)
4. 지지/저항 수준
5. 거래량 분석

출력 형식:
- signal: BUY, SELL, HOLD 중 하나
- confidence: 0.0 ~ 1.0 사이의 신뢰도
- summary: 분석 요약 (한글)
- key_factors: 핵심 요인 목록
"""
```

---

## 성능 최적화

### 병렬 처리

```python
# 4개 에이전트 병렬 실행
async def analyze_parallel():
    results = await asyncio.gather(
        technical_agent.analyze(data),
        fundamental_agent.analyze(data),
        sentiment_agent.analyze(data),
        risk_agent.analyze(data),
    )
    return results
```

### 캐싱

- 시장 데이터: 1분 캐싱
- LLM 응답: 세션 내 캐싱
- 분석 결과: SQLite 영구 저장
