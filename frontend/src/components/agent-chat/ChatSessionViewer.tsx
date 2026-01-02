/**
 * ChatSessionViewer Component
 *
 * Displays the full discussion of a chat session.
 * Shows messages from all agents and the final decision.
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
} from 'lucide-react';
import { getAgentChatSessionDetail } from '@/api/client';
import type {
  AgentChatSessionDetail,
  AgentChatMessage,
  AgentChatDecision,
  AgentChatVote,
  AgentChatAgentType,
} from '@/types';

interface ChatSessionViewerProps {
  sessionId: string;
  onClose: () => void;
}

const agentConfig: Record<
  AgentChatAgentType,
  { icon: React.ReactNode; color: string; bgColor: string; name: string }
> = {
  technical: {
    icon: <BarChart2 className="w-4 h-4" />,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
    name: 'Technical',
  },
  fundamental: {
    icon: <DollarSign className="w-4 h-4" />,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    name: 'Fundamental',
  },
  sentiment: {
    icon: <Newspaper className="w-4 h-4" />,
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
    name: 'Sentiment',
  },
  risk: {
    icon: <Shield className="w-4 h-4" />,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20',
    name: 'Risk',
  },
  moderator: {
    icon: <User className="w-4 h-4" />,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/20',
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
    <div className="flex gap-3 p-3 hover:bg-gray-800/50 rounded-lg">
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${config.bgColor}`}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`font-medium ${config.color}`}>{message.agent_name}</span>
          <span className="text-xs text-gray-500">{formatTime(message.timestamp)}</span>
          {message.confidence !== null && (
            <span className="text-xs px-1.5 py-0.5 bg-gray-700 rounded text-gray-400">
              {(message.confidence * 100).toFixed(0)}% confidence
            </span>
          )}
        </div>
        <div className="text-sm text-gray-300 whitespace-pre-wrap">{message.content}</div>
        {message.data && Object.keys(message.data).length > 0 && (
          <div className="mt-2 p-2 bg-gray-800 rounded text-xs text-gray-400">
            <pre className="overflow-x-auto">{JSON.stringify(message.data, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

function VoteCard({ vote }: { vote: AgentChatVote }) {
  const config = agentConfig[vote.agent_type] || agentConfig.moderator;
  const voteColor =
    vote.vote === 'STRONG_BUY' || vote.vote === 'BUY'
      ? 'text-green-400'
      : vote.vote === 'STRONG_SELL' || vote.vote === 'SELL'
      ? 'text-red-400'
      : 'text-gray-400';

  return (
    <div className="p-3 bg-gray-800 rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-6 h-6 rounded-full flex items-center justify-center ${config.bgColor}`}>
            {config.icon}
          </div>
          <span className={`text-sm font-medium ${config.color}`}>{config.name}</span>
        </div>
        <span className={`font-bold ${voteColor}`}>{vote.vote}</span>
      </div>
      <div className="text-xs text-gray-400 space-y-1">
        <div className="flex justify-between">
          <span>Confidence:</span>
          <span>{(vote.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span>Weight:</span>
          <span>{vote.weight}</span>
        </div>
        <div className="flex justify-between">
          <span>Score:</span>
          <span>{vote.weighted_score.toFixed(2)}</span>
        </div>
      </div>
      {vote.reasoning && (
        <p className="mt-2 text-xs text-gray-500">{vote.reasoning}</p>
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

  const actionColor =
    decision.action === 'BUY' || decision.action === 'ADD'
      ? 'text-green-400 bg-green-500/20 border-green-500/30'
      : decision.action === 'SELL' || decision.action === 'REDUCE'
      ? 'text-red-400 bg-red-500/20 border-red-500/30'
      : 'text-gray-400 bg-gray-500/20 border-gray-500/30';

  return (
    <div className={`p-6 rounded-xl border ${actionColor}`}>
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
        <div className="p-3 bg-gray-900/50 rounded-lg">
          <div className="text-xs text-gray-400">Consensus</div>
          <div className="text-lg font-medium text-white">
            {(decision.consensus_level * 100).toFixed(0)}%
          </div>
        </div>
        <div className="p-3 bg-gray-900/50 rounded-lg">
          <div className="text-xs text-gray-400">Entry Price</div>
          <div className="text-lg font-medium text-white">{formatPrice(decision.entry_price)}</div>
        </div>
        <div className="p-3 bg-gray-900/50 rounded-lg">
          <div className="text-xs text-gray-400">Stop Loss</div>
          <div className="text-lg font-medium text-red-400">{formatPrice(decision.stop_loss)}</div>
        </div>
        <div className="p-3 bg-gray-900/50 rounded-lg">
          <div className="text-xs text-gray-400">Take Profit</div>
          <div className="text-lg font-medium text-green-400">{formatPrice(decision.take_profit)}</div>
        </div>
      </div>

      {decision.rationale && (
        <div className="mb-4">
          <div className="text-sm font-medium text-gray-300 mb-2">Rationale</div>
          <p className="text-sm text-gray-400">{decision.rationale}</p>
        </div>
      )}

      {decision.key_factors.length > 0 && (
        <div className="mb-4">
          <div className="text-sm font-medium text-gray-300 mb-2">Key Factors</div>
          <ul className="list-disc list-inside text-sm text-gray-400 space-y-1">
            {decision.key_factors.map((factor, i) => (
              <li key={i}>{factor}</li>
            ))}
          </ul>
        </div>
      )}

      {decision.dissenting_opinions.length > 0 && (
        <div>
          <div className="text-sm font-medium text-gray-300 mb-2">Dissenting Opinions</div>
          <ul className="list-disc list-inside text-sm text-gray-400 space-y-1">
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

  useEffect(() => {
    fetchSession();
    // Poll for updates if session is still active
    const interval = setInterval(() => {
      if (
        session &&
        ['initializing', 'analyzing', 'discussing', 'voting'].includes(session.status)
      ) {
        fetchSession();
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchSession, session?.status]);

  useEffect(() => {
    // Auto-scroll to bottom when new messages arrive
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session?.messages.length]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <button
          onClick={onClose}
          className="flex items-center gap-2 text-gray-400 hover:text-white mb-4"
        >
          <ArrowLeft className="w-5 h-5" />
          Back
        </button>
        <div className="flex items-center gap-3 text-red-400">
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
          className="flex items-center gap-2 text-gray-400 hover:text-white"
        >
          <ArrowLeft className="w-5 h-5" />
          Back to Dashboard
        </button>
        <button
          onClick={fetchSession}
          className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
        >
          <RefreshCw className="w-5 h-5" />
        </button>
      </div>

      {/* Session Info */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-white">
              {session.stock_name} ({session.ticker})
            </h2>
            <p className="text-sm text-gray-400">
              Session: {session.id.slice(0, 8)}...
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`px-3 py-1 rounded-full text-sm ${
                session.status === 'decided'
                  ? 'bg-green-500/20 text-green-400'
                  : session.status === 'error'
                  ? 'bg-red-500/20 text-red-400'
                  : 'bg-blue-500/20 text-blue-400'
              }`}
            >
              {session.status}
            </span>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 text-center">
          <div className="p-3 bg-gray-800 rounded-lg">
            <div className="text-lg font-bold text-white">{session.rounds.length}</div>
            <div className="text-xs text-gray-400">Rounds</div>
          </div>
          <div className="p-3 bg-gray-800 rounded-lg">
            <div className="text-lg font-bold text-white">{session.messages.length}</div>
            <div className="text-xs text-gray-400">Messages</div>
          </div>
          <div className="p-3 bg-gray-800 rounded-lg">
            <div className="text-lg font-bold text-white">{session.votes.length}</div>
            <div className="text-xs text-gray-400">Votes</div>
          </div>
          <div className="p-3 bg-gray-800 rounded-lg">
            <div className="text-lg font-bold text-white">
              {(session.consensus_level * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-gray-400">Consensus</div>
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
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-green-400" />
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
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-blue-400" />
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
