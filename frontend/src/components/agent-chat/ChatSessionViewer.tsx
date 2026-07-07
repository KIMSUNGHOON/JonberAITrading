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
  TrendingUp,
  TrendingDown,
  Minus,
  AlertCircle,
} from 'lucide-react';
import { getAgentChatSessionDetail } from '@/api/client';
import { useAgentChatWebSocket } from '@/hooks/useAgentChatWebSocket';
import { pnlColor } from '@/utils/pnl';
import { ReadingPane } from '@/components/common/ReadingPane';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import type {
  AgentChatSessionDetail,
  AgentChatMessage,
  AgentChatDecision,
  AgentChatVote,
  AgentChatVoteType,
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
        <ReadingPane><MarkdownRenderer content={message.content} /></ReadingPane>
        {message.data && Object.keys(message.data).length > 0 && (
          <div className="mt-2 p-2 bg-elevated rounded text-xs text-muted">
            <pre className="overflow-x-auto">{JSON.stringify(message.data, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

const VOTE_LABEL: Record<AgentChatVoteType, string> = {
  STRONG_BUY: 'S.BUY',
  BUY: 'BUY',
  HOLD: 'HOLD',
  SELL: 'SELL',
  STRONG_SELL: 'S.SELL',
  ABSTAIN: 'ABS',
};

// Vote DIRECTIONAL color -> @/utils/pnl (app-wide ACTION map): STRONG_BUY/BUY
// bullish -> up, STRONG_SELL/SELL bearish -> down, HOLD neutral, ABSTAIN dim.
function voteColor(v: AgentChatVoteType): string {
  if (v === 'STRONG_BUY' || v === 'BUY') return pnlColor(1);
  if (v === 'SELL' || v === 'STRONG_SELL') return pnlColor(-1);
  if (v === 'HOLD') return 'text-muted';
  return 'text-dim';
}

export function VoteBlotter({ votes }: { votes: AgentChatVote[] }) {
  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr className="text-[10px] uppercase tracking-wide text-dim border-b border-hairline">
          <th className="text-left font-semibold px-2.5 py-1.5">Agent</th>
          <th className="text-right font-semibold px-2.5 py-1.5">Vote</th>
          <th className="text-right font-semibold px-2.5 py-1.5">Conf</th>
          <th className="text-right font-semibold px-2.5 py-1.5">Wgt</th>
          <th className="text-right font-semibold px-2.5 py-1.5">Score</th>
        </tr>
      </thead>
      <tbody className="text-muted">
        {votes.map((v, i) => {
          const config = agentConfig[v.agent_type] || agentConfig.moderator;
          return (
            <tr key={i} className="border-b border-hairline/60">
              <td className="text-left px-2.5 h-6">
                <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
                  <span className={`${config.color} text-[8px] leading-none`}>●</span>
                  {config.name}
                </span>
              </td>
              <td className={`text-right px-2.5 font-semibold ${voteColor(v.vote)}`}>{VOTE_LABEL[v.vote]}</td>
              <td className="text-right px-2.5 text-dim">{(v.confidence * 100).toFixed(0)}%</td>
              <td className="text-right px-2.5 text-muted">{v.weight.toFixed(2)}</td>
              <td className="text-right px-2.5 text-muted">{v.weighted_score.toFixed(2)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TicketKV({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="bg-card px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-dim">{label}</div>
      <div className={`text-sm font-medium tabular-nums ${valueClass ?? 'text-ink'}`}>{value}</div>
    </div>
  );
}

function ConsensusTicket({
  decision,
  ticker,
  stockName,
}: {
  decision: AgentChatDecision;
  ticker: string;
  stockName: string;
}) {
  const actionIcon =
    decision.action === 'BUY' || decision.action === 'ADD' ? (
      <TrendingUp className="w-4 h-4" />
    ) : decision.action === 'SELL' || decision.action === 'REDUCE' ? (
      <TrendingDown className="w-4 h-4" />
    ) : (
      <Minus className="w-4 h-4" />
    );

  // ACTION DIRECTIONAL -> @/utils/pnl (text-only badge; no card background).
  const actionColor =
    decision.action === 'BUY' || decision.action === 'ADD'
      ? pnlColor(1)
      : decision.action === 'SELL' || decision.action === 'REDUCE'
      ? pnlColor(-1)
      : 'text-muted';

  const consensusPct = Math.round(decision.consensus_level * 100);

  return (
    <div className="bg-card border border-hairline rounded">
      {/* Header: ACTION (text-only) + symbol + confidence */}
      <div className="flex items-center gap-2.5 px-3 py-2 border-b border-hairline">
        <span className={`inline-flex items-center gap-1.5 text-base font-bold ${actionColor}`}>
          {actionIcon}
          {decision.action}
        </span>
        <span className="text-sm text-ink font-semibold">{stockName}</span>
        <span className="text-xs text-dim">({ticker})</span>
        <span className="ml-auto text-xs text-muted">
          CONF <span className="text-ink font-bold tabular-nums">{(decision.confidence * 100).toFixed(0)}%</span>
        </span>
      </div>

      {/* Consensus bar + 75% display gate */}
      <div className="flex items-center gap-2.5 px-3 py-2 border-b border-hairline">
        <span className="text-[10px] text-muted">CONSENSUS</span>
        <span className="text-sm font-bold tabular-nums text-ink">{consensusPct}%</span>
        <div className="flex-1 h-1.5 rounded bg-elevated relative">
          <span
            className="absolute inset-y-0 left-0 rounded bg-accent transition-[width] duration-500"
            style={{ width: `${Math.min(100, Math.max(0, consensusPct))}%` }}
          />
          {/* 75% gate is a display constant, not an enforced backend threshold. */}
          <span className="absolute top-[-3px] bottom-[-3px] left-[75%] w-0.5 bg-warn" />
        </div>
        <span className="text-[11px] text-muted">gate 75%</span>
      </div>

      {/* Entry / Stop / Take KV */}
      <div className="grid grid-cols-3 gap-px bg-hairline border-b border-hairline">
        <TicketKV label="ENTRY" value={formatPrice(decision.entry_price)} />
        <TicketKV label="STOP" value={formatPrice(decision.stop_loss)} valueClass="text-down" />
        <TicketKV label="TAKE" value={formatPrice(decision.take_profit)} valueClass="text-up" />
      </div>

      {/* Rationale — editorial reading pane (prose) */}
      {decision.rationale && (
        <div className="px-3 py-2 border-b border-hairline">
          <div className="text-[10px] uppercase tracking-wide text-dim mb-1">Rationale</div>
          <ReadingPane>
            <MarkdownRenderer content={decision.rationale} />
          </ReadingPane>
        </div>
      )}

      {/* Key factors — dense list */}
      {decision.key_factors.length > 0 && (
        <div className="px-3 py-2 border-b border-hairline">
          <div className="text-[10px] uppercase tracking-wide text-dim mb-1">Key Factors</div>
          <ul className="text-xs text-muted space-y-0.5">
            {decision.key_factors.map((f, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-dim flex-none">·</span>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Dissent — dense list */}
      {decision.dissenting_opinions.length > 0 && (
        <div className="px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-dim mb-1">Dissent</div>
          <ul className="text-xs text-muted space-y-0.5">
            {decision.dissenting_opinions.map((o, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-dim flex-none">·</span>
                {o}
              </li>
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
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-hairline pb-2">
        <button onClick={onClose} className="flex items-center gap-1.5 text-xs text-muted hover:text-ink">
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <div className="ml-auto flex items-center gap-3">
          {isActiveSession && (
            <span className="text-[11px] font-mono">
              {isConnected ? (
                <span className="text-up">● live</span>
              ) : connectionState === 'connecting' || connectionState === 'reconnecting' ? (
                <span className="text-warn">◌ connecting…</span>
              ) : (
                <span className="text-muted">○ polling</span>
              )}
            </span>
          )}
          <button onClick={fetchSession} className="p-1 text-muted hover:text-ink hover:bg-elevated rounded">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Session strip */}
      <div className="border-b border-hairline pb-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-ink">{session.stock_name}</h2>
          <span className="text-xs text-dim">({session.ticker})</span>
          <span className="text-[10px] text-dim">· {session.id.slice(0, 8)}</span>
          <span
            className={`ml-auto text-[11px] font-mono uppercase ${
              session.status === 'decided'
                ? 'text-up'
                : session.status === 'error'
                ? 'text-down'
                : 'text-accent'
            }`}
          >
            {session.status}
          </span>
        </div>
        <div className="mt-1 flex gap-3 text-[11px] font-mono tabular-nums text-muted">
          <span>ROUNDS <span className="text-ink">{session.rounds.length}</span></span>
          <span>MSGS <span className="text-ink">{session.messages.length}</span></span>
          <span>VOTES <span className="text-ink">{session.votes.length}</span></span>
          <span>CONSENSUS <span className="text-ink">{(session.consensus_level * 100).toFixed(0)}%</span></span>
        </div>
      </div>

      {/* Decision (if available) */}
      {session.decision && (
        <ConsensusTicket
          decision={session.decision}
          ticker={session.ticker}
          stockName={session.stock_name}
        />
      )}

      {/* Votes */}
      {session.votes.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-dim mb-1.5">
            Agent Votes · {session.votes.length}
          </div>
          <VoteBlotter votes={session.votes} />
        </div>
      )}

      {/* Discussion */}
      <div>
        <div className="text-[10px] uppercase tracking-wide text-dim mb-1.5">
          Discussion · {session.messages.length}
        </div>
        <div className="space-y-1 max-h-[600px] overflow-y-auto">
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
