"""
Agent Group Chat Service

Multi-agent discussion system for autonomous trading decisions.
Agents discuss, debate, and vote on trading opportunities within
user's watch list.

Key Components:
- ChatSession: Complete discussion session
- AgentMessage: Individual messages in chat
- AgentVote: Agent's voting decision
- TradeDecision: Final trading decision

Agents:
- TechnicalDiscussionAgent: Chart and indicator analysis
- FundamentalDiscussionAgent: Valuation and financials
- SentimentDiscussionAgent: News and market psychology
- RiskDiscussionAgent: Risk evaluation and position sizing
- ModeratorAgent: Facilitates discussion and makes final decision
"""

from services.agent_chat.models import (
    AgentMessage,
    AgentType,
    AgentVote,
    ChatRound,
    ChatSession,
    DecisionAction,
    MarketContext,
    MessageType,
    SessionStatus,
    TradeDecision,
    VoteType,
)

from services.agent_chat.agents import (
    BaseDiscussionAgent,
    TechnicalDiscussionAgent,
    FundamentalDiscussionAgent,
    SentimentDiscussionAgent,
    RiskDiscussionAgent,
    ModeratorAgent,
)

from services.agent_chat.chat_room import ChatRoom
from services.agent_chat.coordinator import (
    ChatCoordinator,
    get_chat_coordinator,
    get_chat_coordinator_sync,
)
from services.agent_chat.position_manager import (
    PositionManager,
    PositionManagerConfig,
    PositionEventType,
    PositionAction,
    MonitoredPosition,
    PositionEvent,
    PositionDecision,
    get_position_manager,
    get_position_manager_sync,
    POSITION_EVENT_KOREAN,
    get_event_korean,
)

__all__ = [
    # Models
    "AgentMessage",
    "AgentType",
    "AgentVote",
    "ChatRound",
    "ChatSession",
    "DecisionAction",
    "MarketContext",
    "MessageType",
    "SessionStatus",
    "TradeDecision",
    "VoteType",
    # Agents
    "BaseDiscussionAgent",
    "TechnicalDiscussionAgent",
    "FundamentalDiscussionAgent",
    "SentimentDiscussionAgent",
    "RiskDiscussionAgent",
    "ModeratorAgent",
    # Chat Management
    "ChatRoom",
    "ChatCoordinator",
    "get_chat_coordinator",
    "get_chat_coordinator_sync",
    # Position Management
    "PositionManager",
    "PositionManagerConfig",
    "PositionEventType",
    "PositionAction",
    "MonitoredPosition",
    "PositionEvent",
    "PositionDecision",
    "get_position_manager",
    "get_position_manager_sync",
    "POSITION_EVENT_KOREAN",
    "get_event_korean",
]
