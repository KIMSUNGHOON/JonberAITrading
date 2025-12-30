# Agentic AI Trading - Project Roadmap

> Last Updated: 2025-12-30
> Status: Active Development

---

## 프로젝트 개요

AI 기반 주식/코인 자동매매 시스템
- 병렬 분석, 실시간 모니터링
- Human-in-the-Loop (HITL) 승인 워크플로우
- 다중 에이전트 협업 트레이딩

---

## 완료된 기능 (Completed)

### Phase 1-4: Core Trading Platform ✅

| 기능 | Coin (Upbit) | Korea Stock (Kiwoom) |
|------|--------------|----------------------|
| Market Data API | ✅ | ✅ |
| Analysis Pipeline (LangGraph) | ✅ | ✅ |
| Real-time WebSocket | ✅ | ✅ |
| Multi-session Support | ✅ | ✅ |
| Trade Execution | ✅ | ✅ |
| Position Management | ✅ | ✅ |
| HITL Approval Flow | ✅ | ✅ |

### Phase 5-8: Parallel Analysis ✅

- [x] 동시 분석 3개 제한 (Semaphore)
- [x] 세션별 WebSocket 라우팅
- [x] 다중 세션 Store 구조
- [x] BasketWidget 분석 시작
- [x] Sidebar 페이지 네비게이션
- [x] AnalysisPage + History 통합

### Auto-Trading Foundation ✅

- [x] News API 연동 (Naver)
- [x] Sentiment Analysis 통합
- [x] Trading Coordinator 구조
- [x] Portfolio Agent (기본)
- [x] Order Agent (기본)
- [x] Risk Monitor (기본)
- [x] Approval → Auto-Trading 연결
- [x] Market Hours Service (KRX, Crypto)
- [x] Activity Logging System
- [x] TradingStatusWidget

---

## 현재 진행 중 (In Progress)

### Auto-Trading 고도화

**문제점 (사용자 피드백 2025-12-30):**
1. Approval 후 Auto-Trading에서 아무 action 없음
2. 장 마감 시 Wait Queue 없음 (다음 장 시작 대기 필요)
3. Agent Status가 너무 단순함 (각 Agent별 상세 상태 필요)
4. Dashboard에 Auto-Trading 상태 없음

**필요 기능:**
- [ ] Trade Queue 시스템 (장 마감 시 대기열)
- [ ] 미체결/체결 주문 상태 추적
- [ ] Agent별 상세 상태 표시 (Portfolio, Order, Risk)
- [ ] Dashboard Auto-Trading 위젯
- [ ] 실시간 체결 알림

---

## 개발 로드맵 (Upcoming)

### Phase A: Trade Queue & Order Tracking (High Priority)

**목표:** 장 마감 후 Approval → 다음 장 시작 시 자동 실행

```
[Approval] → [Trade Queue] → [Market Open Check] → [Order Execution]
                  ↓
            [Pending Orders UI]
```

**Tasks:**
- [ ] `TradingQueue` 모델 추가 (ticker, proposal, queued_at, status)
- [ ] Coordinator에 queue 로직 추가
- [ ] Market Open 시 Queue 처리
- [ ] Pending Orders UI 컴포넌트
- [ ] Queue 상태 API 엔드포인트

### Phase B: Enhanced Agent Status (High Priority)

**목표:** 각 Agent의 현재 Task 및 상태 실시간 표시

```
┌─────────────────────────────────────────────────────┐
│                  Agent Status                        │
├─────────────────────────────────────────────────────┤
│ Portfolio Agent: Calculating allocation for 005930   │
│ Order Agent: Waiting for market open                 │
│ Risk Monitor: Watching 3 positions                   │
│ Last Decision: BUY 005930 approved, queued          │
└─────────────────────────────────────────────────────┘
```

**Tasks:**
- [ ] Agent State 모델 확장 (current_task, last_action, etc.)
- [ ] Agent별 상태 로깅
- [ ] AgentStatusPanel 컴포넌트 개선
- [ ] Dashboard에 Agent Summary 위젯

### Phase C: Analysis Data Persistence (Medium Priority)

**목표:** 완료된 분석 데이터 영구 저장

**Tasks:**
- [ ] `DetailedAnalysisResults` 타입 정의
- [ ] History에 분석 결과 저장
- [ ] AnalysisDetailPage 데이터 표시

### Phase D: Technical Indicators (Medium Priority)

**목표:** RSI, MACD, 볼린저 밴드 등 기술적 지표

**Tasks:**
- [ ] `TechnicalIndicators` 서비스
- [ ] `/api/indicators/{ticker}` 엔드포인트
- [ ] 차트 지표 오버레이

### Phase E: External Data Sources (Low Priority)

**목표:** OpenDART 재무제표, 추가 뉴스 소스

**Tasks:**
- [ ] OpenDART API 연동
- [ ] 재무제표 데이터 표시
- [ ] 공시 알림 기능

---

## 아키텍처 개요

### Backend Structure
```
backend/
├── app/
│   ├── api/routes/          # API 엔드포인트
│   │   ├── trading.py       # Auto-trading API
│   │   ├── approval.py      # HITL Approval
│   │   └── websocket.py     # Real-time updates
│   └── dependencies.py      # DI (Kiwoom singleton)
├── services/
│   ├── trading/             # Auto-trading 서비스
│   │   ├── coordinator.py   # Execution Coordinator
│   │   ├── portfolio_agent.py
│   │   ├── order_agent.py
│   │   ├── risk_monitor.py
│   │   ├── market_hours.py  # Market open/close
│   │   └── models.py        # Trading models
│   ├── kiwoom/              # 키움 API
│   ├── upbit/               # 업비트 API
│   └── news/                # 뉴스 서비스
└── agents/                  # LangGraph Agents
    ├── graph/               # Analysis workflows
    └── subagents/           # Specialist agents
```

### Frontend Structure
```
frontend/src/
├── components/
│   ├── trading/             # Auto-trading 컴포넌트
│   │   ├── TradingDashboard.tsx
│   │   └── TradingStatusWidget.tsx
│   ├── kiwoom/              # 한국주식
│   ├── coin/                # 코인
│   └── analysis/            # 분석 UI
├── store/                   # Zustand state
├── api/                     # API clients
└── pages/                   # Page components
```

### Agent Workflow
```
[Analysis Request]
       ↓
[Technical Agent] ─┬─ [Fundamental Agent]
                   │
                   ├─ [Sentiment Agent]
                   │
                   └─ [Risk Agent]
       ↓
[Trade Proposal]
       ↓
[HITL Approval] ──────────────────────┐
       ↓                              │
[Portfolio Agent] → [Order Agent] → [Risk Monitor]
       │                │                │
       └────────────────┴────────────────┘
                        ↓
              [Execution Coordinator]
                        ↓
              [Kiwoom/Upbit API]
```

---

## 환경 설정

### 필수 환경 변수
```env
# LLM
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=deepseek-r1:14b

# Kiwoom (한국주식)
KIWOOM_APP_KEY=...
KIWOOM_APP_SECRET=...
KIWOOM_ACCOUNT_NUMBER=...
KIWOOM_IS_MOCK=true

# Upbit (코인)
UPBIT_ACCESS_KEY=...
UPBIT_SECRET_KEY=...
UPBIT_TRADING_MODE=paper

# News
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...

# Redis
REDIS_URL=redis://localhost:6379
```

---

## 관련 문서

- `CLAUDE.md` - Claude Code 개발 지침
- `docs/UI_ARCHITECTURE.md` - UI 구조
- `docs/OPENDART_API_GUIDE.md` - OpenDART API 가이드

### 아카이브 (완료된 기능)
- `docs/archive/TODO.md` - 이전 개발 추적
- `docs/archive/FEATURE_SPEC_COIN_TRADING.md`
- `docs/archive/FEATURE_SPEC_REALTIME_AGENT_TRADING.md`
- `docs/archive/AutoTrading_Implementation_Plan.md`
- `docs/archive/KIWOOM_API_IMPLEMENTATION_PLAN.md`
- `docs/archive/UI_UX_Basket_Feature_Proposal.md`
