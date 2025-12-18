# Feature Specification: Real-Time Agent Trading System

## 1. Executive Summary

This document outlines the feature specification and architecture for implementing **Real-Time Agent-to-Agent Communication** for autonomous trading decisions. When a user approves trading authority, the AI agents will continuously monitor markets, communicate with each other, and make collaborative position decisions in real-time.

---

## 2. Feature Overview

### 2.1 Current State
- **One-time Analysis**: User enters ticker → Agents analyze → Single trade proposal → User approves/rejects
- **No Continuous Monitoring**: Analysis is a point-in-time snapshot
- **No Agent Collaboration**: Agents work independently, synthesize results at the end

### 2.2 Target State
- **Continuous Trading Mode**: After approval, agents actively manage positions
- **Real-Time Market Monitoring**: Agents react to price changes, news, and market events
- **Agent-to-Agent Dialogue**: Agents discuss and debate trading decisions in real-time
- **Dynamic Position Management**: Automatic stop-loss, take-profit, and position adjustments

---

## 3. Functional Requirements

### 3.1 Trading Mode Activation
| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | User can enable "Auto-Trading Mode" after initial analysis approval | P0 |
| F-02 | System displays clear risk disclosure before enabling | P0 |
| F-03 | User can set max position size, max loss tolerance, trading hours | P0 |
| F-04 | User can disable auto-trading at any time (immediate effect) | P0 |

### 3.2 Agent Communication Protocol
| ID | Requirement | Priority |
|----|-------------|----------|
| F-05 | Agents can send structured messages to other agents | P0 |
| F-06 | Messages include: sender, recipient, message_type, content, timestamp | P0 |
| F-07 | Message types: ALERT, QUESTION, PROPOSAL, VOTE, DECISION | P0 |
| F-08 | All agent communications are logged and displayed to user | P1 |

### 3.3 Decision Making
| ID | Requirement | Priority |
|----|-------------|----------|
| F-09 | Agents use consensus voting for position changes | P0 |
| F-10 | Minimum 3 of 5 agents must agree for action | P0 |
| F-11 | Risk Agent has veto power on high-risk decisions | P0 |
| F-12 | Decisions must be made within configurable timeout (default: 30s) | P1 |

### 3.4 Position Management
| ID | Requirement | Priority |
|----|-------------|----------|
| F-13 | System monitors all open positions in real-time | P0 |
| F-14 | Automatic stop-loss execution when price hits threshold | P0 |
| F-15 | Automatic take-profit execution when price hits target | P0 |
| F-16 | Dynamic position sizing based on portfolio risk | P1 |
| F-17 | Trailing stop-loss support | P2 |

### 3.5 User Interface
| ID | Requirement | Priority |
|----|-------------|----------|
| F-18 | Real-time agent conversation display (chat-like) | P0 |
| F-19 | Position P&L dashboard with live updates | P0 |
| F-20 | Alert notifications for significant events | P0 |
| F-21 | Historical agent decision log | P1 |

---

## 4. Technical Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                              │
├─────────────────────────────────────────────────────────────────────┤
│  AgentChatPanel │ PositionDashboard │ ControlPanel │ AlertCenter    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                                  │
├─────────────────────────────────────────────────────────────────────┤
│  TradingSessionManager │ AgentOrchestrator │ PositionManager         │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Agent Communication Layer                          │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │Technical│◄─┤Fundament│◄─┤Sentiment│◄─┤  Risk   │◄─┤Execution│   │
│  │ Agent   │  │ Agent   │  │ Agent   │  │ Agent   │  │ Agent   │   │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘   │
│       │            │            │            │            │         │
│       └────────────┴────────────┴────────────┴────────────┘         │
│                              │                                       │
│                    Agent Message Bus (Redis PubSub)                  │
└─────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     External Services                                │
├─────────────────────────────────────────────────────────────────────┤
│  Market Data (yfinance) │ News API │ LLM Server │ Broker API         │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Details

#### 4.2.1 Agent Communication Layer

**AgentMessageBus** - Central message routing system
```python
class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    sender: AgentType
    recipients: list[AgentType] | Literal["all"]
    message_type: MessageType  # ALERT, QUESTION, PROPOSAL, VOTE, DECISION
    content: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reply_to: str | None = None
    requires_response: bool = False
    response_timeout: int = 30  # seconds

class MessageType(str, Enum):
    ALERT = "alert"           # Market event notification
    QUESTION = "question"     # Request for opinion
    PROPOSAL = "proposal"     # Trading action proposal
    VOTE = "vote"            # Vote on a proposal
    DECISION = "decision"    # Final decision announcement
    UPDATE = "update"        # Status update
```

**AgentOrchestrator** - Coordinates agent interactions
```python
class AgentOrchestrator:
    async def broadcast(self, message: AgentMessage) -> None
    async def request_votes(self, proposal: Proposal) -> VoteResult
    async def execute_decision(self, decision: Decision) -> ExecutionResult
    async def handle_market_event(self, event: MarketEvent) -> None
```

#### 4.2.2 Trading Session States

```
┌──────────────┐
│    IDLE      │
└──────┬───────┘
       │ start_analysis()
       ▼
┌──────────────┐
│   ANALYZING  │
└──────┬───────┘
       │ analysis_complete()
       ▼
┌──────────────┐     reject()    ┌──────────────┐
│   PROPOSAL   │ ───────────────►│ RE_ANALYZING │
└──────┬───────┘                 └──────┬───────┘
       │ approve()                      │
       ▼                                │
┌──────────────┐                        │
│AUTO_TRADING  │◄───────────────────────┘
│   ENABLED    │
└──────┬───────┘
       │ (continuous loop)
       ▼
┌────────────────────────────────────────┐
│         ACTIVE TRADING LOOP            │
│  ┌─────────────────────────────────┐   │
│  │  Monitor Market ──► Detect Event │   │
│  │         │                        │   │
│  │         ▼                        │   │
│  │  Agent Discussion ──► Vote       │   │
│  │         │                        │   │
│  │         ▼                        │   │
│  │  Execute Decision ──► Update     │   │
│  └─────────────────────────────────┘   │
└──────────────┬─────────────────────────┘
               │ stop() or max_loss_hit
               ▼
┌──────────────┐
│   STOPPED    │
└──────────────┘
```

#### 4.2.3 Agent Decision Protocol

**Proposal Flow**:
1. Any agent can create a `PROPOSAL` message
2. Orchestrator broadcasts to all agents
3. Each agent responds with `VOTE` (approve/reject/abstain + reasoning)
4. Orchestrator tallies votes
5. Risk Agent can veto if risk threshold exceeded
6. `DECISION` message broadcast with final outcome
7. Execution Agent executes if approved

**Example Agent Conversation**:
```
[Technical Agent]: ALERT - AAPL broke above 200-day SMA ($178.50)
                   Strong bullish signal confirmed by volume surge

[Fundamental Agent]: QUESTION - Any recent earnings or news that
                     might explain this move?

[Sentiment Agent]: UPDATE - News sentiment score: 0.72 (positive)
                   Recent headlines: "Apple AI features drive iPhone demand"

[Technical Agent]: PROPOSAL - Increase position by 20%
                   Entry: $179.00, New Stop: $175.00, Target: $190.00
                   Rationale: Breakout with volume confirmation + positive sentiment

[Fundamental Agent]: VOTE - APPROVE
                     P/E still reasonable, strong cash position supports growth

[Sentiment Agent]: VOTE - APPROVE
                   Market sentiment aligned with technical breakout

[Risk Agent]: VOTE - APPROVE with modification
              Reduce position increase to 15% to maintain portfolio balance
              Current portfolio exposure: 12% → 27% with 20% increase

[Execution Agent]: VOTE - APPROVE
                   Sufficient liquidity, spread within acceptable range

[Orchestrator]: DECISION - APPROVED (modified)
                Action: Increase position by 15%
                4 of 5 agents approved, Risk Agent modification accepted
```

### 4.3 Data Models

#### 4.3.1 Trading Session Extended State
```python
class AutoTradingConfig(BaseModel):
    enabled: bool = False
    max_position_pct: float = 25.0      # Max % of portfolio per position
    max_daily_loss_pct: float = 5.0     # Stop trading if daily loss exceeds
    max_trades_per_day: int = 10
    trading_hours_start: time = time(9, 30)  # EST
    trading_hours_end: time = time(16, 0)
    require_confirmation_above: float = 10000  # USD, trades above need manual approval

class ActivePosition(BaseModel):
    id: str
    ticker: str
    quantity: int
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    trailing_stop_pct: float | None
    opened_at: datetime
    pnl: float  # Computed property
    pnl_pct: float  # Computed property

class TradingSessionState(TypedDict):
    # ... existing fields ...
    auto_trading_config: AutoTradingConfig
    active_positions: list[ActivePosition]
    agent_messages: list[AgentMessage]
    pending_proposals: list[Proposal]
    daily_pnl: float
    daily_trade_count: int
```

#### 4.3.2 WebSocket Message Types
```python
class WSMessageType(str, Enum):
    # Existing
    REASONING = "reasoning"
    STATUS = "status"
    PROPOSAL = "proposal"
    POSITION = "position"
    COMPLETE = "complete"

    # New for auto-trading
    AGENT_MESSAGE = "agent_message"    # Agent-to-agent communication
    POSITION_UPDATE = "position_update" # P&L updates
    MARKET_ALERT = "market_alert"      # Significant market events
    TRADE_EXECUTED = "trade_executed"  # Trade execution confirmation
    DECISION = "decision"              # Agent consensus decision
```

### 4.4 Backend Services

#### 4.4.1 New Service: MarketMonitor
```python
class MarketMonitor:
    """Continuously monitors market data and triggers events"""

    async def start(self, tickers: list[str]) -> None:
        """Start monitoring specified tickers"""

    async def stop(self) -> None:
        """Stop all monitoring"""

    async def on_price_update(self, ticker: str, price: float) -> None:
        """Handle price updates, check stop-loss/take-profit"""

    async def on_volume_spike(self, ticker: str, volume: int) -> None:
        """Detect unusual volume activity"""

    async def on_news_event(self, ticker: str, news: NewsItem) -> None:
        """Handle breaking news events"""
```

#### 4.4.2 New Service: PositionManager
```python
class PositionManager:
    """Manages active positions and executes orders"""

    async def open_position(self, order: Order) -> Position:
        """Execute buy/sell order and create position"""

    async def close_position(self, position_id: str, reason: str) -> CloseResult:
        """Close position with reason logging"""

    async def update_stops(self, position_id: str, stop_loss: float, take_profit: float) -> None:
        """Update stop-loss and take-profit levels"""

    async def check_risk_limits(self, proposed_order: Order) -> RiskCheckResult:
        """Verify order doesn't violate risk limits"""
```

### 4.5 Frontend Components

#### 4.5.1 New Component: AgentChatPanel
```tsx
interface AgentChatPanelProps {
  messages: AgentMessage[];
  isAutoTradingEnabled: boolean;
}

function AgentChatPanel({ messages, isAutoTradingEnabled }: AgentChatPanelProps) {
  // Display real-time agent conversation
  // Different colors/icons for each agent
  // Collapsible vote summaries
  // Decision highlights
}
```

#### 4.5.2 New Component: AutoTradingControl
```tsx
interface AutoTradingControlProps {
  config: AutoTradingConfig;
  onConfigChange: (config: AutoTradingConfig) => void;
  onEnable: () => void;
  onDisable: () => void;
}

function AutoTradingControl({ ... }: AutoTradingControlProps) {
  // Risk disclosure agreement
  // Configuration sliders/inputs
  // Enable/Disable toggle
  // Current status indicator
}
```

#### 4.5.3 New Component: PositionsDashboard
```tsx
interface PositionsDashboardProps {
  positions: ActivePosition[];
  dailyPnL: number;
  totalPnL: number;
}

function PositionsDashboard({ ... }: PositionsDashboardProps) {
  // Real-time P&L display
  // Position cards with charts
  // Manual close buttons
  // Stop-loss/take-profit editing
}
```

---

## 5. Implementation Plan

### Phase 1: Foundation (2-3 weeks)
- [ ] Implement AgentMessageBus with Redis PubSub
- [ ] Create AgentMessage data models
- [ ] Add agent_messages to TradingState
- [ ] Implement basic agent-to-agent messaging in nodes
- [ ] Add WebSocket streaming for agent messages

### Phase 2: Decision Protocol (2 weeks)
- [ ] Implement proposal creation logic
- [ ] Implement voting mechanism
- [ ] Add Risk Agent veto capability
- [ ] Create AgentOrchestrator service
- [ ] Add decision timeout handling

### Phase 3: Market Monitoring (2 weeks)
- [ ] Implement MarketMonitor service
- [ ] Add price alert triggers
- [ ] Integrate news feed monitoring
- [ ] Create event-driven agent activation

### Phase 4: Position Management (2 weeks)
- [ ] Implement PositionManager service
- [ ] Add stop-loss/take-profit execution
- [ ] Create position tracking database
- [ ] Implement P&L calculations

### Phase 5: Frontend UI (2-3 weeks)
- [ ] Build AgentChatPanel component
- [ ] Create AutoTradingControl panel
- [ ] Implement PositionsDashboard
- [ ] Add notification system
- [ ] Mobile-responsive design

### Phase 6: Testing & Polish (1-2 weeks)
- [ ] Integration testing
- [ ] Load testing for real-time updates
- [ ] Security audit
- [ ] Documentation
- [ ] User acceptance testing

---

## 6. Risk Considerations

### 6.1 Technical Risks
| Risk | Mitigation |
|------|------------|
| WebSocket connection drops | Implement reconnection with exponential backoff |
| Agent timeout during voting | Default to safe action (hold/no trade) on timeout |
| LLM latency spikes | Cache common responses, implement circuit breaker |
| Data inconsistency | Use Redis transactions, implement saga pattern |

### 6.2 Business Risks
| Risk | Mitigation |
|------|------------|
| Financial loss from auto-trading | Strict risk limits, user-configurable max loss |
| Regulatory concerns | Clear disclaimers, paper trading mode, audit logs |
| User trust issues | Transparency in agent decisions, full audit trail |

---

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Agent message latency | < 100ms p95 |
| Decision time (proposal to execution) | < 5 seconds |
| Position update frequency | Real-time (< 1s delay) |
| System uptime | 99.9% during market hours |
| User satisfaction (auto-trading feature) | > 4.0/5.0 rating |

---

## 8. Future Enhancements

- Multi-asset portfolio management
- Custom trading strategies (momentum, mean-reversion)
- Backtesting with historical data
- Social trading (follow successful configurations)
- Advanced risk models (VaR, stress testing)
- Integration with multiple brokers

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-18 | AI Assistant | Initial specification |
