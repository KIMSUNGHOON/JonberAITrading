/**
 * ChatSessionList Component
 *
 * Displays a list of chat sessions with their status and decisions.
 */

import {
  MessageSquare,
  CheckCircle,
  XCircle,
  Clock,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  ChevronRight,
} from 'lucide-react';
import type { AgentChatSessionSummary, AgentChatDecisionAction } from '@/types';

interface ChatSessionListProps {
  sessions: AgentChatSessionSummary[];
  onSelectSession: (sessionId: string) => void;
}

const statusConfig: Record<
  string,
  { icon: React.ReactNode; color: string; bgColor: string }
> = {
  initializing: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/20',
  },
  analyzing: {
    icon: <Clock className="w-4 h-4 animate-spin" />,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
  },
  discussing: {
    icon: <MessageSquare className="w-4 h-4" />,
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
  },
  voting: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20',
  },
  decided: {
    icon: <CheckCircle className="w-4 h-4" />,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
  },
  cancelled: {
    icon: <XCircle className="w-4 h-4" />,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/20',
  },
  error: {
    icon: <AlertTriangle className="w-4 h-4" />,
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
  },
};

const decisionConfig: Record<
  AgentChatDecisionAction,
  { icon: React.ReactNode; color: string; label: string }
> = {
  BUY: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'text-green-400',
    label: 'BUY',
  },
  SELL: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: 'text-red-400',
    label: 'SELL',
  },
  HOLD: {
    icon: <Minus className="w-4 h-4" />,
    color: 'text-gray-400',
    label: 'HOLD',
  },
  ADD: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: 'text-green-400',
    label: 'ADD',
  },
  REDUCE: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: 'text-orange-400',
    label: 'REDUCE',
  },
  WATCH: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-yellow-400',
    label: 'WATCH',
  },
  NO_ACTION: {
    icon: <Minus className="w-4 h-4" />,
    color: 'text-gray-400',
    label: 'NO ACTION',
  },
};

function formatDate(dateString: string | null): string {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatConsensus(level: number | null): string {
  if (level === null) return '-';
  return `${(level * 100).toFixed(0)}%`;
}

export function ChatSessionList({ sessions, onSelectSession }: ChatSessionListProps) {
  if (sessions.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 className="text-lg font-medium text-white mb-4">Recent Sessions</h3>
        <div className="text-center py-8 text-gray-500">
          <MessageSquare className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No discussion sessions yet</p>
          <p className="text-sm mt-1">
            Start the coordinator to begin automatic monitoring
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
      <h3 className="text-lg font-medium text-white mb-4">Recent Sessions</h3>
      <div className="space-y-2">
        {sessions.map((session) => {
          const statusCfg = statusConfig[session.status] || statusConfig.error;
          const decisionCfg = session.decision_action
            ? decisionConfig[session.decision_action]
            : null;

          return (
            <div
              key={session.id}
              className="flex items-center justify-between p-4 bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-700 transition-colors"
              onClick={() => onSelectSession(session.id)}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="text-white font-medium truncate">
                    {session.stock_name}
                  </span>
                  <span className="text-gray-500 text-sm">({session.ticker})</span>
                </div>
                <div className="flex items-center gap-4 mt-1 text-sm">
                  <span className="text-gray-400">
                    {formatDate(session.started_at)}
                  </span>
                  <span className="text-gray-500">
                    {session.total_messages} messages, {session.total_rounds} rounds
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {/* Consensus Level */}
                {session.consensus_level !== null && (
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">
                      {formatConsensus(session.consensus_level)}
                    </div>
                    <div className="text-xs text-gray-500">Consensus</div>
                  </div>
                )}

                {/* Decision Badge */}
                {decisionCfg && (
                  <div
                    className={`flex items-center gap-1 px-2 py-1 rounded ${decisionCfg.color} bg-gray-700`}
                  >
                    {decisionCfg.icon}
                    <span className="text-xs font-medium">{decisionCfg.label}</span>
                  </div>
                )}

                {/* Status Badge */}
                <div
                  className={`flex items-center gap-1 px-2 py-1 rounded ${statusCfg.color} ${statusCfg.bgColor}`}
                >
                  {statusCfg.icon}
                  <span className="text-xs capitalize">{session.status}</span>
                </div>

                <ChevronRight className="w-5 h-5 text-gray-500" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ChatSessionList;
