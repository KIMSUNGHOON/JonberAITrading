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
import { pnlColor } from '@/utils/pnl';

interface ChatSessionListProps {
  sessions: AgentChatSessionSummary[];
  onSelectSession: (sessionId: string) => void;
  /** B3 (cosmetic, optional): highlights the row for the session currently
   *  open in the detail pane, so the list ("master") visibly reflects what's
   *  selected instead of leaving that only implicit. */
  selectedSessionId?: string | null;
}

// Session-lifecycle STATUS map (not directional) -> direct tokens: muted
// (idle/neutral), accent (active/working/info), warn (waiting/pending),
// up (done/success), down (error/failed). Matches AgentNode's StatusBadge
// (idle/working/waiting/error -> muted/accent/warn/down) convention.
const statusConfig: Record<
  string,
  { icon: React.ReactNode; color: string; bgColor: string }
> = {
  initializing: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-muted',
    bgColor: 'bg-muted/20',
  },
  analyzing: {
    icon: <Clock className="w-4 h-4 animate-spin" />,
    color: 'text-accent',
    bgColor: 'bg-accent/20',
  },
  discussing: {
    icon: <MessageSquare className="w-4 h-4" />,
    color: 'text-accent',
    bgColor: 'bg-accent/20',
  },
  voting: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-warn',
    bgColor: 'bg-warn/20',
  },
  decided: {
    icon: <CheckCircle className="w-4 h-4" />,
    color: 'text-up',
    bgColor: 'bg-up/20',
  },
  cancelled: {
    icon: <XCircle className="w-4 h-4" />,
    color: 'text-muted',
    bgColor: 'bg-muted/20',
  },
  error: {
    icon: <AlertTriangle className="w-4 h-4" />,
    color: 'text-down',
    bgColor: 'bg-down/20',
  },
};

// Trade-action DIRECTIONAL map -> routed via @/utils/pnl. App-wide ACTION map
// (ScannerResultsPage/AnalysisDetailPage/AgentStatusWidget): BUY/ADD bullish
// -> pnlColor(1) (up/green), SELL/REDUCE bearish -> pnlColor(-1) (down/red),
// WATCH -> warn, HOLD/NO_ACTION -> muted.
const decisionConfig: Record<
  AgentChatDecisionAction,
  { icon: React.ReactNode; color: string; label: string }
> = {
  BUY: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: pnlColor(1),
    label: 'BUY',
  },
  SELL: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: pnlColor(-1),
    label: 'SELL',
  },
  HOLD: {
    icon: <Minus className="w-4 h-4" />,
    color: 'text-muted',
    label: 'HOLD',
  },
  ADD: {
    icon: <TrendingUp className="w-4 h-4" />,
    color: pnlColor(1),
    label: 'ADD',
  },
  REDUCE: {
    icon: <TrendingDown className="w-4 h-4" />,
    color: pnlColor(-1),
    label: 'REDUCE',
  },
  WATCH: {
    icon: <Clock className="w-4 h-4" />,
    color: 'text-warn',
    label: 'WATCH',
  },
  NO_ACTION: {
    icon: <Minus className="w-4 h-4" />,
    color: 'text-muted',
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

export function ChatSessionList({ sessions, onSelectSession, selectedSessionId = null }: ChatSessionListProps) {
  if (sessions.length === 0) {
    return (
      <div className="bg-card rounded border border-hairline p-6">
        <h3 className="text-lg font-medium text-ink mb-4">Recent Sessions</h3>
        <div className="text-center py-8 text-dim">
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
    <div className="bg-card rounded border border-hairline p-6">
      <h3 className="text-lg font-medium text-ink mb-4">Recent Sessions</h3>
      <div className="space-y-2">
        {sessions.map((session) => {
          const statusCfg = statusConfig[session.status] || statusConfig.error;
          const decisionCfg = session.decision_action
            ? decisionConfig[session.decision_action]
            : null;

          const isSelected = session.id === selectedSessionId;

          return (
            <div
              key={session.id}
              className={`flex items-center justify-between p-4 rounded-lg cursor-pointer transition-colors ${
                isSelected ? 'bg-hairline ring-1 ring-accent' : 'bg-elevated hover:bg-hairline'
              }`}
              onClick={() => onSelectSession(session.id)}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="text-ink font-medium truncate">
                    {session.stock_name}
                  </span>
                  <span className="text-dim text-sm">({session.ticker})</span>
                </div>
                <div className="flex items-center gap-4 mt-1 text-sm">
                  <span className="text-muted">
                    {formatDate(session.started_at)}
                  </span>
                  <span className="text-dim tabular-nums">
                    {session.total_messages} messages, {session.total_rounds} rounds
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {/* Consensus Level */}
                {session.consensus_level !== null && (
                  <div className="text-center">
                    <div className="text-sm font-medium text-ink tabular-nums">
                      {formatConsensus(session.consensus_level)}
                    </div>
                    <div className="text-xs text-dim">Consensus</div>
                  </div>
                )}

                {/* Decision Badge */}
                {decisionCfg && (
                  <div
                    className={`flex items-center gap-1 px-2 py-1 rounded ${decisionCfg.color} bg-card`}
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

                <ChevronRight className="w-5 h-5 text-dim" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ChatSessionList;
