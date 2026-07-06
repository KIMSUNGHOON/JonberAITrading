/**
 * ChatSessionViewer Component
 *
 * Displays the full discussion of a chat session.
 * Shows messages from all agents and the final decision.
 * Uses WebSocket for real-time updates.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ArrowLeft,
  RefreshCw,
  User,
  BarChart2,
  DollarSign,
  Newspaper,
  Shield,
  MessageSquare,
  CheckCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertCircle,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { getAgentChatSessionDetail } from '@/api/client';
import { useAgentChatWebSocket } from '@/hooks/useAgentChatWebSocket';
import { pnlColor } from '@/utils/pnl';
import type {
  AgentChatSessionDetail,
  AgentChatMessage,
  AgentChatDecision,
  AgentChatVote,
  AgentChatAgentType,
  AgentChatSessionStatus,
} from '@/types';

interface ChatSessionViewerProps {
  sessionId: string;
  onClose: () => void;
}

// Agent-category IDENTITY map (not directional) -> which analyst produced
// this message/vote. Colors stay raw hues per category; `fundamental`'s green
// is agent-category identity, NOT a bullish vote (see voteColor/actionColor
// below for the actual DIRECTIONAL BUY/SELL colors -> @/utils/pnl).
const agentConfig: Record<
  AgentChatAgentType,
  { icon: React.ReactNode; color: string; bgColor: string; name: string }
> = {
  technical: {
    icon: <BarChart2 className="w-4 h-4" />,
    color: 'text-blue-400', // color-ok: agent-category identity, not directional
    bgColor: 'bg-blue-500/20', // color-ok: agent-category identity, not directional
    name: 'Technical',
  },
  fundamental: {
    icon: <DollarSign className="w-4 h-4" />,
    color: 'text-green-400', // color-ok: agent-category identity (fundamental analyst), not directional
    bgColor: 'bg-green-500/20', // color-ok: agent-category identity (fundamental analyst), not directional
    name: 'Fundamental',
  },
  sentiment: {
    icon: <Newspaper className="w-4 h-4" />,
    color: 'text-purple-400', // color-ok: agent-category identity, not directional
    bgColor: 'bg-purple-500/20', // color-ok: agent-category identity, not directional
    name: 'Sentiment',
  },
  risk: {
    icon: <Shield className="w-4 h-4" />,
    color: 'text-yellow-400', // color-ok: agent-category identity, not directional
    bgColor: 'bg-yellow-500/20', // color-ok: agent-category identity, not directional
    name: 'Risk',
  },
  moderator: {
    icon: <User className="w-4 h-4" />,
    color: 'text-muted',
    bgColor: 'bg-muted/20',
    name: 'Moderator',
  },
};

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatPrice(price: number | null): string {
  if (price === null) return '-';
  return price.toLocaleString('ko-KR') + ' KRW';
}

function MessageBubble({ message }: { message: AgentChatMessage }) {
  const config = agentConfig[message.agent_type] || agentConfig.moderator;

  return (
    <div className="flex gap-3 p-3 hover:bg-elevated/50 rounded-lg">
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${config.bgColor}`}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`font-medium ${config.color}`}>{message.agent_name}</span>
          <span className="text-xs text-dim">{formatTime(message.timestamp)}</span>
          {message.confidence !== null && (
            <span className="text-xs px-1.5 py-0.5 bg-elevated rounded text-muted tabular-nums">
              {(message.confidence * 100).toFixed(0)}% confidence
            </span>
          )}
        </div>
        <div className="text-sm text-ink whitespace-pre-wrap">{message.content}</div>
        {message.data && Object.keys(message.data).length > 0 && (
          <div className="mt-2 p-2 bg-elevated rounded text-xs text-muted">
            <pre className="overflow-x-auto">{JSON.stringify(message.data, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

function VoteCard({ vote }: { vote: AgentChatVote }) {
  const config = agentConfig[vote.agent_type] || agentConfig.moderator;
  // Vote DIRECTIONAL map -> @/utils/pnl. App-wide ACTION map: STRONG_BUY/BUY
  // bullish -> pnlColor(1) (up/green), STRONG_SELL/SELL bearish -> pnlColor(-1)
  // (down/red), HOLD -> muted (non-directional).
  const voteColor =
    vote.vote === 'STRONG_BUY' || vote.vote === 'BUY'
      ? pnlColor(1)
      : vote.vote === 'STRONG_SELL' || vote.vote === 'SELL'
      ? pnlColor(-1)
      : 'text-muted';

  return (
    <div className="p-3 bg-elevated rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-6 h-6 rounded-full flex items-center justify-center ${config.bgColor}`}>
            {config.icon}
          </div>
          <span className={`text-sm font-medium ${config.color}`}>{config.name}</span>
        </div>
        <span className={`font-bold ${voteColor}`}>{vote.vote}</span>
      </div>
      <div className="text-xs text-muted space-y-1">
        <div className="flex justify-between">
          <span>Confidence:</span>
          <span className="tabular-nums">{(vote.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span>Weight:</span>
          <span className="tabular-nums">{vote.weight}</span>
        </div>
        <div className="flex justify-between">
          <span>Score:</span>
          <span className="tabular-nums">{vote.weighted_score.toFixed(2)}</span>
        </div>
      </div>
      {vote.reasoning && (
        <p className="mt-2 text-xs text-dim">{vote.reasoning}</p>
      )}
    </div>
  );
}

function DecisionPanel({ decision, ticker, stockName }: { decision: AgentChatDecision; ticker: string; stockName: string }) {
  const actionIcon =
    decision.action === 'BUY' || decision.action === 'ADD' ? (
      <TrendingUp className="w-6 h-6" />
    ) : decision.action === 'SELL' || decision.action === 'REDUCE' ? (
      <TrendingDown className="w-6 h-6" />
    ) : (
      <Minus className="w-6 h-6" />
    );

  // Decision-action DIRECTIONAL map -> @/utils/pnl semantics. App-wide ACTION
  // map (ScannerResultsPage/AnalysisDetailPage): BUY/ADD bullish -> up/green,
  // SELL/REDUCE bearish -> down/red, else neutral.
  const actionColor =
    decision.action === 'BUY' || decision.action === 'ADD'
      ? `${pnlColor(1)} bg-up/20 border-up/30`
      : decision.action === 'SELL' || decision.action === 'REDUCE'
      ? `${pnlColor(-1)} bg-down/20 border-down/30`
      : 'text-muted bg-muted/20 border-hairline';

  return (
    <div className={`p-6 rounded border ${actionColor}`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          {actionIcon}
          <div>
            <div className="text-2xl font-bold">{decision.action}</div>
            <div className="text-sm opacity-75">{stockName} ({ticker})</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold">{(decision.confidence * 100).toFixed(0)}%</div>
          <div className="text-sm opacity-75">Confidence</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="p-3 bg-elevated rounded-lg">
          <div className="text-xs text-muted">Consensus</div>
          <div className="text-lg font-medium text-ink tabular-nums">
            {(decision.consensus_level * 100).toFixed(0)}%
          </div>
        </div>
        <div className="p-3 bg-elevated rounded-lg">
          <div className="text-xs text-muted">Entry Price</div>
          <div className="text-lg font-medium text-ink tabular-nums">{formatPrice(decision.entry_price)}</div>
        </div>
        <div className="p-3 bg-elevated rounded-lg">
          <div className="text-xs text-muted">Stop Loss</div>
          <div className="text-lg font-medium text-down tabular-nums">{formatPrice(decision.stop_loss)}</div>
        </div>
        <div className="p-3 bg-elevated rounded-lg">
          <div className="text-xs text-muted">Take Profit</div>
          <div className="text-lg font-medium text-up tabular-nums">{formatPrice(decision.take_profit)}</div>
        </div>
      </div>

      {decision.rationale && (
        <div className="mb-4">
          <div className="text-sm font-medium text-ink mb-2">Rationale</div>
          <p className="text-sm text-muted">{decision.rationale}</p>
        </div>
      )}

      {decision.key_factors.length > 0 && (
        <div className="mb-4">
          <div className="text-sm font-medium text-ink mb-2">Key Factors</div>
          <ul className="list-disc list-inside text-sm text-muted space-y-1">
            {decision.key_factors.map((factor, i) => (
              <li key={i}>{factor}</li>
            ))}
          </ul>
        </div>
      )}

      {decision.dissenting_opinions.length > 0 && (
        <div>
          <div className="text-sm font-medium text-ink mb-2">Dissenting Opinions</div>
          <ul className="list-disc list-inside text-sm text-muted space-y-1">
            {decision.dissenting_opinions.map((opinion, i) => (
              <li key={i}>{opinion}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ChatSessionViewer({ sessionId, onClose }: ChatSessionViewerProps) {
  const [session, setSession] = useState<AgentChatSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Determine if session is active (needs real-time updates)
  const isActiveSession = session && ['initializing', 'analyzing', 'discussing', 'voting'].includes(session.status);

  // WebSocket for real-time updates
  const { isConnected, connectionState } = useAgentChatWebSocket({
    sessionId: isActiveSession ? sessionId : null, // Only connect for active sessions
    autoConnect: true,
    onMessage: useCallback((message: AgentChatMessage) => {
      setSession((prev) => {
        if (!prev) return prev;
        // Check if message already exists
        if (prev.messages.some((m) => m.id === message.id)) {
          return prev;
        }
        return {
          ...prev,
          messages: [...prev.messages, message],
        };
      });
    }, []),
    onStatusChange: useCallback((_status: AgentChatSessionStatus, updatedSession: AgentChatSessionDetail) => {
      setSession(updatedSession);
    }, []),
    onVote: useCallback((vote: AgentChatVote) => {
      setSession((prev) => {
        if (!prev) return prev;
        // Check if vote from this agent already exists
        if (prev.votes.some((v) => v.agent_type === vote.agent_type)) {
          return prev;
        }
        return {
          ...prev,
          votes: [...prev.votes, vote],
        };
      });
    }, []),
    onDecision: useCallback((decision: AgentChatDecision) => {
      setSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          decision,
          status: 'decided' as AgentChatSessionStatus,
        };
      });
    }, []),
    onError: useCallback((wsError: string) => {
      console.error('[ChatSessionViewer] WebSocket error:', wsError);
    }, []),
  });

  const fetchSession = useCallback(async () => {
    try {
      setError(null);
      const data = await getAgentChatSessionDetail(sessionId);
      setSession(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load session');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Initial fetch
  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  // Fallback polling when WebSocket is not connected and session is active
  useEffect(() => {
    if (!isActiveSession || isConnected) return;

    // Poll as fallback when WebSocket is not connected
    const interval = setInterval(() => {
      fetchSession();
    }, 5000);
    return () => clearInterval(interval);
  }, [isActiveSession, isConnected, fetchSession]);

  useEffect(() => {
    // Auto-scroll to bottom when new messages arrive
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session?.messages.length]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-card rounded border border-hairline p-6">
        <button
          onClick={onClose}
          className="flex items-center gap-2 text-muted hover:text-ink mb-4"
        >
          <ArrowLeft className="w-5 h-5" />
          Back
        </button>
        <div className="flex items-center gap-3 text-down">
          <AlertCircle className="w-5 h-5" />
          {error}
        </div>
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button
          onClick={onClose}
          className="flex items-center gap-2 text-muted hover:text-ink"
        >
          <ArrowLeft className="w-5 h-5" />
          Back to Dashboard
        </button>
        <div className="flex items-center gap-3">
          {/* WebSocket Connection Status */}
          {isActiveSession && (
            <div className="flex items-center gap-2">
              {isConnected ? (
                <div className="flex items-center gap-1.5 px-2 py-1 bg-up/10 rounded-lg">
                  <Wifi className="w-4 h-4 text-up" />
                  <span className="text-xs text-up">Live</span>
                </div>
              ) : connectionState === 'connecting' || connectionState === 'reconnecting' ? (
                <div className="flex items-center gap-1.5 px-2 py-1 bg-warn/10 rounded-lg">
                  <RefreshCw className="w-4 h-4 text-warn animate-spin" />
                  <span className="text-xs text-warn">Connecting...</span>
                </div>
              ) : (
                <div className="flex items-center gap-1.5 px-2 py-1 bg-muted/10 rounded-lg">
                  <WifiOff className="w-4 h-4 text-muted" />
                  <span className="text-xs text-muted">Polling</span>
                </div>
              )}
            </div>
          )}
          <button
            onClick={fetchSession}
            className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Session Info */}
      <div className="bg-card rounded border border-hairline p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-ink">
              {session.stock_name} ({session.ticker})
            </h2>
            <p className="text-sm text-muted">
              Session: {session.id.slice(0, 8)}...
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`px-3 py-1 rounded-full text-sm ${
                session.status === 'decided'
                  ? 'bg-up/20 text-up'
                  : session.status === 'error'
                  ? 'bg-down/20 text-down'
                  : 'bg-accent/20 text-accent'
              }`}
            >
              {session.status}
            </span>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 text-center">
          <div className="p-3 bg-elevated rounded-lg">
            <div className="text-lg font-bold text-ink tabular-nums">{session.rounds.length}</div>
            <div className="text-xs text-muted">Rounds</div>
          </div>
          <div className="p-3 bg-elevated rounded-lg">
            <div className="text-lg font-bold text-ink tabular-nums">{session.messages.length}</div>
            <div className="text-xs text-muted">Messages</div>
          </div>
          <div className="p-3 bg-elevated rounded-lg">
            <div className="text-lg font-bold text-ink tabular-nums">{session.votes.length}</div>
            <div className="text-xs text-muted">Votes</div>
          </div>
          <div className="p-3 bg-elevated rounded-lg">
            <div className="text-lg font-bold text-ink tabular-nums">
              {(session.consensus_level * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-muted">Consensus</div>
          </div>
        </div>
      </div>

      {/* Decision (if available) */}
      {session.decision && (
        <DecisionPanel
          decision={session.decision}
          ticker={session.ticker}
          stockName={session.stock_name}
        />
      )}

      {/* Votes */}
      {session.votes.length > 0 && (
        <div className="bg-card rounded border border-hairline p-6">
          <h3 className="text-lg font-medium text-ink mb-4 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-accent" />
            Agent Votes
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {session.votes.map((vote, i) => (
              <VoteCard key={i} vote={vote} />
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="bg-card rounded border border-hairline p-6">
        <h3 className="text-lg font-medium text-ink mb-4 flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-accent" />
          Discussion ({session.messages.length} messages)
        </h3>
        <div className="space-y-2 max-h-[600px] overflow-y-auto">
          {session.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>
    </div>
  );
}

export default ChatSessionViewer;
