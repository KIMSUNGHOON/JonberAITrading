/**
 * AgentStatusWidget Component
 *
 * Shows real-time status of each trading agent:
 * - Portfolio Agent: Position sizing and allocation
 * - Order Agent: Order execution
 * - Risk Monitor: Stop-loss/take-profit monitoring
 * - Strategy Engine: Strategy evaluation
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  Briefcase,
  ShoppingCart,
  Shield,
  Sliders,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Clock,
  Loader2,
} from 'lucide-react';
import { getAgentStates } from '@/api/client';
import { pnlColor } from '@/utils/pnl';

// -------------------------------------------
// Types
// -------------------------------------------

interface TradeDetails {
  action?: string;
  quantity?: number;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  risk_score?: number;
  estimated_amount?: number;
  total_amount?: number;
  position_pct?: number;
}

interface AnalysisSummary {
  technical?: { signal: string; confidence: number; key_factors?: string[] };
  fundamental?: { signal: string; confidence: number; key_factors?: string[] };
  sentiment?: { signal: string; confidence: number; key_factors?: string[] };
  risk?: { level: string; score: number; factors?: string[] };
}

interface LastResult {
  success: boolean;
  message: string;
  order_id?: string;
  filled_quantity?: number;
  avg_price?: number;
  quantity?: number;
  estimated_amount?: number;
}

interface AgentState {
  name: string;
  status: 'idle' | 'working' | 'waiting' | 'error';
  current_task: string | null;
  last_action: string | null;
  last_action_time: string | null;
  error_message: string | null;
  tasks_completed: number;
  tasks_failed: number;
  // 세부 정보 (Sub Agent Status 개선)
  processing_stock?: string | null;
  processing_stock_name?: string | null;
  trade_details?: TradeDetails | null;
  analysis_summary?: AnalysisSummary | null;
  last_result?: LastResult | null;
}

// -------------------------------------------
// Constants
// -------------------------------------------

const AGENT_ICONS: Record<string, React.ReactNode> = {
  portfolio: <Briefcase className="w-4 h-4" />,
  order: <ShoppingCart className="w-4 h-4" />,
  risk: <Shield className="w-4 h-4" />,
  strategy: <Sliders className="w-4 h-4" />,
};

const STATUS_CONFIG: Record<AgentState['status'], { label: string; color: string; icon: React.ReactNode }> = {
  idle: { label: '대기', color: 'text-muted', icon: <CheckCircle className="w-3 h-3" /> },
  working: { label: '작업중', color: 'text-accent', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
  waiting: { label: '대기중', color: 'text-warn', icon: <Clock className="w-3 h-3" /> },
  error: { label: '오류', color: 'text-down', icon: <AlertCircle className="w-3 h-3" /> },
};

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface AgentCardProps {
  agentKey: string;
  agent: AgentState;
}

function AgentCard({ agentKey, agent }: AgentCardProps) {
  const statusConfig = STATUS_CONFIG[agent.status];
  const icon = AGENT_ICONS[agentKey] || <Activity className="w-4 h-4" />;

  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return '-';
    const date = new Date(timeStr);
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  };

  const formatPrice = (price: number | undefined) => {
    if (!price) return '-';
    return `₩${price.toLocaleString()}`;
  };

  const formatAmount = (amount: number | undefined) => {
    if (!amount) return '-';
    if (amount >= 100000000) {
      return `₩${(amount / 100000000).toFixed(1)}억`;
    } else if (amount >= 10000) {
      return `₩${(amount / 10000).toFixed(0)}만`;
    }
    return `₩${amount.toLocaleString()}`;
  };

  // Merged app-wide ACTION_COLOR convention (matches ScannerResultsPage /
  // AnalysisDetailPage): BUY/ADD is bullish -> pnlColor(1) (up/green),
  // SELL/REDUCE is bearish -> pnlColor(-1) (down/red). This FLIPS the old
  // Korean red-up convention that used to color BUY red here while
  // TradeQueueWidget colored BUY green — the safety-relevant unification.
  const getActionColor = (action: string | undefined) => {
    if (!action) return 'text-muted';
    switch (action.toUpperCase()) {
      case 'BUY':
      case 'ADD':
        return pnlColor(1);
      case 'SELL':
      case 'REDUCE':
        return pnlColor(-1);
      case 'WATCH':
        return 'text-warn';
      case 'AVOID':
        return 'text-accent';
      case 'HOLD':
      default:
        return 'text-muted';
    }
  };

  return (
    <div className={`p-3 rounded-lg border ${
      agent.status === 'error' ? 'border-down/30 bg-down/5' :
      agent.status === 'working' ? 'border-accent/30 bg-accent/5' :
      'border-hairline bg-elevated/50'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`p-1.5 rounded ${
            agent.status === 'working' ? 'bg-accent/20 text-accent' :
            agent.status === 'error' ? 'bg-down/20 text-down' :
            'bg-elevated text-muted'
          }`}>
            {icon}
          </div>
          <div>
            <div className="font-medium text-sm text-ink">{agent.name}</div>
            <div className={`flex items-center gap-1 text-xs ${statusConfig.color}`}>
              {statusConfig.icon}
              <span>{statusConfig.label}</span>
            </div>
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="text-dim tabular-nums">완료: {agent.tasks_completed}</div>
          {agent.tasks_failed > 0 && (
            <div className="text-down tabular-nums">실패: {agent.tasks_failed}</div>
          )}
        </div>
      </div>

      {/* Processing Stock */}
      {agent.processing_stock && (
        <div className="mt-2 px-2 py-1 bg-warn/10 border border-warn/20 rounded text-xs">
          <span className="text-warn">처리중: </span>
          <span className="text-ink font-medium">
            {agent.processing_stock_name || agent.processing_stock} ({agent.processing_stock})
          </span>
        </div>
      )}

      {/* Current Task */}
      {agent.current_task && (
        <div className="mt-2 p-2 bg-elevated/50 rounded text-xs">
          <div className="text-muted">현재 작업:</div>
          <div className="text-ink truncate">{agent.current_task}</div>
        </div>
      )}

      {/* Trade Details */}
      {agent.trade_details && (
        <div className="mt-2 p-2 bg-elevated/50 rounded text-xs space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-muted">거래 정보</span>
            <span className={`font-medium ${getActionColor(agent.trade_details.action)}`}>
              {agent.trade_details.action}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px]">
            {agent.trade_details.quantity && (
              <>
                <span className="text-dim">수량:</span>
                <span className="text-ink text-right tabular-nums">{agent.trade_details.quantity.toLocaleString()}주</span>
              </>
            )}
            {agent.trade_details.entry_price && (
              <>
                <span className="text-dim">진입가:</span>
                <span className="text-ink text-right tabular-nums">{formatPrice(agent.trade_details.entry_price)}</span>
              </>
            )}
            {agent.trade_details.stop_loss && (
              <>
                <span className="text-dim">손절가:</span>
                <span className="text-down text-right tabular-nums">{formatPrice(agent.trade_details.stop_loss)}</span>
              </>
            )}
            {agent.trade_details.take_profit && (
              <>
                <span className="text-dim">익절가:</span>
                <span className="text-up text-right tabular-nums">{formatPrice(agent.trade_details.take_profit)}</span>
              </>
            )}
            {(agent.trade_details.estimated_amount || agent.trade_details.total_amount) && (
              <>
                <span className="text-dim">금액:</span>
                <span className="text-ink text-right tabular-nums">
                  {formatAmount(agent.trade_details.total_amount || agent.trade_details.estimated_amount)}
                </span>
              </>
            )}
            {agent.trade_details.position_pct !== undefined && (
              <>
                <span className="text-dim">비중:</span>
                <span className="text-ink text-right tabular-nums">{agent.trade_details.position_pct.toFixed(1)}%</span>
              </>
            )}
            {agent.trade_details.risk_score !== undefined && (
              <>
                <span className="text-dim">위험도:</span>
                <span className={`text-right tabular-nums ${
                  agent.trade_details.risk_score >= 7 ? 'text-down' :
                  agent.trade_details.risk_score >= 4 ? 'text-warn' :
                  'text-up'
                }`}>{agent.trade_details.risk_score}/10</span>
              </>
            )}
          </div>
        </div>
      )}

      {/* Last Result */}
      {agent.last_result && (
        <div className={`mt-2 p-2 rounded text-xs ${
          agent.last_result.success
            ? 'bg-up/10 border border-up/20'
            : 'bg-down/10 border border-down/20'
        }`}>
          <div className="flex items-center gap-1">
            {agent.last_result.success ? (
              <CheckCircle className="w-3 h-3 text-up" />
            ) : (
              <AlertCircle className="w-3 h-3 text-down" />
            )}
            <span className={agent.last_result.success ? 'text-up' : 'text-down'}>
              {agent.last_result.success ? '성공' : '실패'}
            </span>
          </div>
          <div className="text-muted mt-1 truncate">{agent.last_result.message}</div>
          {agent.last_result.order_id && (
            <div className="text-dim mt-0.5">주문번호: {agent.last_result.order_id}</div>
          )}
          {agent.last_result.filled_quantity && agent.last_result.avg_price && (
            <div className="text-muted mt-0.5 tabular-nums">
              체결: {agent.last_result.filled_quantity.toLocaleString()}주 @ {formatPrice(agent.last_result.avg_price)}
            </div>
          )}
        </div>
      )}

      {/* Last Action (when no detailed info) */}
      {agent.last_action && !agent.trade_details && !agent.last_result && (
        <div className="mt-2 text-xs text-dim">
          마지막: {agent.last_action} ({formatTime(agent.last_action_time)})
        </div>
      )}

      {/* Error Message */}
      {agent.error_message && (
        <div className="mt-2 p-2 bg-down/10 border border-down/20 rounded text-xs text-down">
          {agent.error_message}
        </div>
      )}
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export default function AgentStatusWidget() {
  const [loading, setLoading] = useState(true);
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [error, setError] = useState<string | null>(null);

  const fetchAgentStates = useCallback(async () => {
    try {
      setError(null);
      const data = await getAgentStates();
      setAgents(data.agents);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agent states');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAgentStates();
    // Poll every 3 seconds
    const interval = setInterval(fetchAgentStates, 3000);
    return () => clearInterval(interval);
  }, [fetchAgentStates]);

  const hasActiveAgents = Object.values(agents).some(a => a.status === 'working');

  return (
    <div className="bg-card rounded border border-hairline">
      {/* Header */}
      <div className="p-4 border-b border-hairline">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className={`w-5 h-5 ${hasActiveAgents ? 'text-accent' : 'text-muted'}`} />
            <h2 className="text-lg font-semibold text-ink">Agent Status</h2>
            {hasActiveAgents && (
              <span className="px-2 py-0.5 text-xs bg-accent/20 text-accent rounded-full">
                Active
              </span>
            )}
          </div>
          <button
            onClick={fetchAgentStates}
            disabled={loading}
            className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {error ? (
          <div className="text-center text-down py-4">
            <AlertCircle className="w-6 h-6 mx-auto mb-2" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && Object.keys(agents).length === 0 ? (
          <div className="text-center text-muted py-4">
            <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" />
            <p className="text-sm">Loading...</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {Object.entries(agents).map(([key, agent]) => (
              <AgentCard key={key} agentKey={key} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
