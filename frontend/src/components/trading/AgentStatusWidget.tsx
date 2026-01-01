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
  idle: { label: '대기', color: 'text-gray-400', icon: <CheckCircle className="w-3 h-3" /> },
  working: { label: '작업중', color: 'text-blue-400', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
  waiting: { label: '대기중', color: 'text-yellow-400', icon: <Clock className="w-3 h-3" /> },
  error: { label: '오류', color: 'text-red-400', icon: <AlertCircle className="w-3 h-3" /> },
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

  const getActionColor = (action: string | undefined) => {
    if (!action) return 'text-gray-400';
    switch (action.toUpperCase()) {
      case 'BUY': return 'text-red-400';
      case 'SELL': return 'text-blue-400';
      case 'HOLD': return 'text-gray-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className={`p-3 rounded-lg border ${
      agent.status === 'error' ? 'border-red-500/30 bg-red-500/5' :
      agent.status === 'working' ? 'border-blue-500/30 bg-blue-500/5' :
      'border-gray-700 bg-gray-800/50'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`p-1.5 rounded ${
            agent.status === 'working' ? 'bg-blue-500/20 text-blue-400' :
            agent.status === 'error' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-700 text-gray-400'
          }`}>
            {icon}
          </div>
          <div>
            <div className="font-medium text-sm text-white">{agent.name}</div>
            <div className={`flex items-center gap-1 text-xs ${statusConfig.color}`}>
              {statusConfig.icon}
              <span>{statusConfig.label}</span>
            </div>
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="text-gray-500">완료: {agent.tasks_completed}</div>
          {agent.tasks_failed > 0 && (
            <div className="text-red-400">실패: {agent.tasks_failed}</div>
          )}
        </div>
      </div>

      {/* Processing Stock */}
      {agent.processing_stock && (
        <div className="mt-2 px-2 py-1 bg-yellow-500/10 border border-yellow-500/20 rounded text-xs">
          <span className="text-yellow-400">처리중: </span>
          <span className="text-white font-medium">
            {agent.processing_stock_name || agent.processing_stock} ({agent.processing_stock})
          </span>
        </div>
      )}

      {/* Current Task */}
      {agent.current_task && (
        <div className="mt-2 p-2 bg-gray-900/50 rounded text-xs">
          <div className="text-gray-400">현재 작업:</div>
          <div className="text-white truncate">{agent.current_task}</div>
        </div>
      )}

      {/* Trade Details */}
      {agent.trade_details && (
        <div className="mt-2 p-2 bg-gray-900/50 rounded text-xs space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">거래 정보</span>
            <span className={`font-medium ${getActionColor(agent.trade_details.action)}`}>
              {agent.trade_details.action}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px]">
            {agent.trade_details.quantity && (
              <>
                <span className="text-gray-500">수량:</span>
                <span className="text-white text-right">{agent.trade_details.quantity.toLocaleString()}주</span>
              </>
            )}
            {agent.trade_details.entry_price && (
              <>
                <span className="text-gray-500">진입가:</span>
                <span className="text-white text-right">{formatPrice(agent.trade_details.entry_price)}</span>
              </>
            )}
            {agent.trade_details.stop_loss && (
              <>
                <span className="text-gray-500">손절가:</span>
                <span className="text-red-400 text-right">{formatPrice(agent.trade_details.stop_loss)}</span>
              </>
            )}
            {agent.trade_details.take_profit && (
              <>
                <span className="text-gray-500">익절가:</span>
                <span className="text-green-400 text-right">{formatPrice(agent.trade_details.take_profit)}</span>
              </>
            )}
            {(agent.trade_details.estimated_amount || agent.trade_details.total_amount) && (
              <>
                <span className="text-gray-500">금액:</span>
                <span className="text-white text-right">
                  {formatAmount(agent.trade_details.total_amount || agent.trade_details.estimated_amount)}
                </span>
              </>
            )}
            {agent.trade_details.position_pct !== undefined && (
              <>
                <span className="text-gray-500">비중:</span>
                <span className="text-white text-right">{agent.trade_details.position_pct.toFixed(1)}%</span>
              </>
            )}
            {agent.trade_details.risk_score !== undefined && (
              <>
                <span className="text-gray-500">위험도:</span>
                <span className={`text-right ${
                  agent.trade_details.risk_score >= 7 ? 'text-red-400' :
                  agent.trade_details.risk_score >= 4 ? 'text-yellow-400' :
                  'text-green-400'
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
            ? 'bg-green-500/10 border border-green-500/20'
            : 'bg-red-500/10 border border-red-500/20'
        }`}>
          <div className="flex items-center gap-1">
            {agent.last_result.success ? (
              <CheckCircle className="w-3 h-3 text-green-400" />
            ) : (
              <AlertCircle className="w-3 h-3 text-red-400" />
            )}
            <span className={agent.last_result.success ? 'text-green-400' : 'text-red-400'}>
              {agent.last_result.success ? '성공' : '실패'}
            </span>
          </div>
          <div className="text-gray-300 mt-1 truncate">{agent.last_result.message}</div>
          {agent.last_result.order_id && (
            <div className="text-gray-500 mt-0.5">주문번호: {agent.last_result.order_id}</div>
          )}
          {agent.last_result.filled_quantity && agent.last_result.avg_price && (
            <div className="text-gray-400 mt-0.5">
              체결: {agent.last_result.filled_quantity.toLocaleString()}주 @ {formatPrice(agent.last_result.avg_price)}
            </div>
          )}
        </div>
      )}

      {/* Last Action (when no detailed info) */}
      {agent.last_action && !agent.trade_details && !agent.last_result && (
        <div className="mt-2 text-xs text-gray-500">
          마지막: {agent.last_action} ({formatTime(agent.last_action_time)})
        </div>
      )}

      {/* Error Message */}
      {agent.error_message && (
        <div className="mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">
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
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className={`w-5 h-5 ${hasActiveAgents ? 'text-blue-400' : 'text-gray-400'}`} />
            <h2 className="text-lg font-semibold text-white">Agent Status</h2>
            {hasActiveAgents && (
              <span className="px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded-full">
                Active
              </span>
            )}
          </div>
          <button
            onClick={fetchAgentStates}
            disabled={loading}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {error ? (
          <div className="text-center text-red-400 py-4">
            <AlertCircle className="w-6 h-6 mx-auto mb-2" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && Object.keys(agents).length === 0 ? (
          <div className="text-center text-gray-400 py-4">
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
