# UI Architecture - Agentic Trading

## 1. Sitemap (페이지 구조)

```
App
├── Dashboard (currentView: 'dashboard')
│   ├── Stock Market View
│   │   ├── DashboardSummary / WelcomePanel
│   │   ├── PositionCard
│   │   ├── BasketWidget
│   │   └── AnalysisQueueWidget
│   │
│   ├── Coin Market View
│   │   ├── DashboardSummary / WelcomePanel
│   │   ├── CoinAccountBalance
│   │   ├── CoinPositionPanel
│   │   ├── CoinOpenOrders
│   │   ├── CoinTradeHistory
│   │   ├── BasketWidget
│   │   ├── AnalysisQueueWidget
│   │   └── CoinMarketDashboard
│   │
│   └── Kiwoom (KR Stock) Market View
│       ├── DashboardSummary / WelcomePanel
│       ├── KiwoomAccountBalance
│       ├── KiwoomPositionPanel
│       ├── KiwoomTickerInput
│       ├── KiwoomOpenOrders
│       ├── BasketWidget
│       └── AnalysisQueueWidget
│
├── Analysis Page (currentView: 'analysis')
│   ├── WorkflowProgress (분석 단계 진행률)
│   ├── ChartPanel (종목 차트)
│   ├── CoinInfo / PositionCard
│   ├── Trading Panels (PositionPanel, OpenOrders)
│   ├── AnalysisPanel (분석 결과)
│   └── AnalysisQueueWidget
│
├── Basket Page (currentView: 'basket')
│   └── BasketWidget (expanded)
│
├── History Page (currentView: 'history')
│   └── Analysis History List (filterable)
│
├── Positions Page (currentView: 'positions')
│   ├── Coin Positions (CoinAccountBalance, CoinPositionPanel)
│   └── Kiwoom Positions (KiwoomAccountBalance, KiwoomPositionPanel)
│
└── Charts Page (currentView: 'charts')
    └── [Placeholder - Advanced Charts]
```

## 2. Component Tree (컴포넌트 계층)

```
App
├── ErrorBoundary
│   ├── Header
│   │   ├── Logo
│   │   ├── Status Indicator
│   │   ├── ChatToggleButton
│   │   └── Settings Button
│   │
│   ├── Sidebar
│   │   ├── MarketTabs (Stock | Crypto | Korea)
│   │   └── NavItems
│   │       ├── Analysis → Dashboard
│   │       ├── Charts → ChartsPage
│   │       ├── Positions → PositionsPage
│   │       ├── My Basket → BasketPage
│   │       ├── History → HistoryPage
│   │       ├── Documentation
│   │       ├── Help
│   │       └── Settings
│   │
│   ├── MainContent
│   │   ├── [Page Routing based on currentView]
│   │   │   ├── Dashboard → Market-specific dashboard
│   │   │   ├── BasketPage
│   │   │   ├── HistoryPage
│   │   │   ├── PositionsPage
│   │   │   └── ChartsPage
│   │   │
│   │   └── [Analysis View - when session active]
│   │       ├── WorkflowProgress
│   │       ├── ChartPanel
│   │       ├── AnalysisPanel
│   │       ├── PositionCard
│   │       └── AnalysisQueueWidget
│   │
│   ├── MobileNav (mobile only)
│   │
│   ├── ApprovalDialog (modal)
│   │   └── ProposalCard
│   │
│   ├── SettingsModal (modal)
│   │
│   ├── ChatPopup (floating)
│   │   └── ChatPanel
│   │       └── ProposalChatMessage
│   │
│   └── ReasoningSlidePanel (slide panel)
│       └── ReasoningLog
```

## 3. UI/UX Function Tree (기능 트리)

```
Agentic Trading App
│
├── 마켓 선택 (Market Selection)
│   ├── US Stock (stock)
│   ├── Crypto (coin) - Upbit API
│   └── KR Stock (kiwoom) - Kiwoom API
│
├── 분석 시작 (Start Analysis)
│   ├── 개별 종목 분석
│   │   ├── TickerInput (Stock)
│   │   ├── CoinTickerInput (Coin)
│   │   └── KiwoomTickerInput (Kiwoom)
│   │
│   └── 다중 종목 분석 (Basket)
│       ├── 종목 검색 & 추가
│       ├── 개별 분석 시작
│       └── 전체 분석 시작 (최대 3개 동시)
│
├── 분석 진행 (Analysis Progress)
│   ├── WorkflowProgress (단계 표시)
│   │   ├── Technical Analysis
│   │   ├── Fundamental Analysis
│   │   ├── Sentiment Analysis
│   │   ├── Risk Assessment
│   │   └── Strategic Decision
│   │
│   ├── AnalysisQueueWidget (분석 중인 종목)
│   │   ├── 진행률 표시
│   │   ├── Reasoning 미리보기
│   │   └── 세션 전환
│   │
│   └── ReasoningLog (실시간 추론 로그)
│
├── 거래 제안 (Trade Proposal)
│   ├── ApprovalDialog
│   │   ├── ProposalCard (상세 정보)
│   │   ├── 승인 (Approve)
│   │   ├── 거절 (Reject)
│   │   └── 재분석 (Re-analyze)
│   │
│   └── ChatPanel
│       ├── ProposalChatMessage
│       ├── 번역 (Korean ↔ English)
│       └── AI 대화
│
├── 포지션 관리 (Position Management)
│   ├── PositionCard
│   ├── CoinPositionPanel
│   ├── KiwoomPositionPanel
│   └── 주문 현황 (OpenOrders)
│
├── 계좌 정보 (Account Info)
│   ├── CoinAccountBalance
│   └── KiwoomAccountBalance
│
├── 분석 기록 (History)
│   ├── HistoryPage
│   │   ├── 마켓별 필터
│   │   ├── 상태별 필터 (completed/cancelled/error)
│   │   └── 검색
│   │
│   └── RecentAnalysisWidget (대시보드)
│
└── 설정 (Settings)
    ├── API 키 설정 (Upbit, Kiwoom)
    ├── LLM 설정
    └── 테마 설정
```

## 4. State Management (상태 관리)

```
Zustand Store
│
├── Market State
│   ├── activeMarket: 'stock' | 'coin' | 'kiwoom'
│   └── stockRegion: 'us' | 'kr'
│
├── Stock State
│   ├── activeSessionId
│   ├── ticker
│   ├── status
│   ├── currentStage
│   ├── reasoningLog[]
│   ├── analyses[]
│   ├── tradeProposal
│   ├── activePosition
│   └── history[]
│
├── Coin State
│   ├── activeSessionId
│   ├── market
│   ├── koreanName
│   ├── status
│   ├── currentStage
│   ├── reasoningLog[]
│   ├── analyses[]
│   ├── tradeProposal
│   └── history[]
│
├── Kiwoom State (Multi-session)
│   ├── sessions[] ← 다중 세션 지원
│   │   ├── sessionId
│   │   ├── ticker
│   │   ├── displayName
│   │   ├── status
│   │   ├── currentStage
│   │   ├── reasoningLog[]
│   │   ├── tradeProposal
│   │   └── awaitingApproval
│   │
│   ├── activeSessionId
│   ├── maxConcurrentSessions: 3
│   └── history[]
│
├── Basket State
│   ├── items[]
│   ├── maxItems: 10
│   └── isUpdating
│
├── UI State
│   ├── currentView: 'dashboard' | 'analysis' | 'basket' | 'history' | 'positions' | 'charts'
│   ├── showApprovalDialog
│   ├── showChartPanel
│   ├── showSettingsModal
│   ├── chatPopupOpen
│   ├── sidebarCollapsed
│   └── hasVisited
│
└── Chat State
    ├── messages[]
    └── isTyping
```

## 5. Data Flow (데이터 흐름)

```
User Action
    │
    ▼
┌─────────────────┐
│  UI Component   │ ← Zustand Store (read)
└────────┬────────┘
         │
         ▼ (dispatch action)
┌─────────────────┐
│  Zustand Store  │
└────────┬────────┘
         │
         ▼ (API call)
┌─────────────────┐
│  API Client     │ ─────────────────┐
└────────┬────────┘                  │
         │                           │
         ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│  REST API       │         │  WebSocket      │
│  /api/...       │         │  /ws/{session}  │
└────────┬────────┘         └────────┬────────┘
         │                           │
         ▼                           │
┌─────────────────┐                  │
│  Backend        │◄─────────────────┘
│  (FastAPI)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LangGraph      │
│  (Agent Flow)   │
└─────────────────┘
```

## 6. Page Navigation Flow (페이지 네비게이션)

```
┌─────────────────────────────────────────────────────────────┐
│                         App                                  │
├───────────────┬─────────────────────────────────────────────┤
│   Sidebar     │              MainContent                     │
│               │                                              │
│ ┌───────────┐ │  currentView                                │
│ │ Dashboard │◄├──────────────► Dashboard (종합 대시보드)     │
│ │ Analysis  │◄├──────────────► Analysis (분석 Workflow)      │
│ │ Charts    │◄├──────────────► ChartsPage                    │
│ │ Positions │◄├──────────────► PositionsPage                 │
│ │ My Basket │◄├──────────────► BasketPage                    │
│ │ History   │◄├──────────────► HistoryPage                   │
│ └───────────┘ │                                              │
│               │  ┌────────────────────────────────────────┐  │
│ MarketTabs    │  │  Dashboard Content                     │  │
│ ┌───────────┐ │  │  (변경: activeMarket에 따라 다른 위젯) │  │
│ │ Stock     │ │  │                                        │  │
│ │ Crypto    │ │  │  ┌─────────┐ ┌─────────┐ ┌─────────┐  │  │
│ │ Korea     │ │  │  │ Account │ │Position │ │ Orders  │  │  │
│ └───────────┘ │  │  └─────────┘ └─────────┘ └─────────┘  │  │
│               │  │                                        │  │
│               │  │  ┌─────────┐ ┌───────────────────────┐│  │
│               │  │  │ Basket  │ │ AnalysisQueueWidget   ││  │
│               │  │  └─────────┘ └───────────────────────┘│  │
│               │  └────────────────────────────────────────┘  │
└───────────────┴─────────────────────────────────────────────┘
```
