/**
 * AgentDetailModal Component
 *
 * Modal dialog showing detailed agent information.
 * Includes trade details, analysis summary, and execution results.
 */

import {
  X,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  FileText,
  BarChart3,
  Shield,
} from 'lucide-react';
import { AGENT_CONFIG } from './AgentNode';
import type { AgentKey, AgentState, TradeDetails, AnalysisSummary, LastResult } from './types';

// -------------------------------------------
// Props
// -------------------------------------------

interface AgentDetailModalProps {
  agentKey: AgentKey;
  agent: AgentState;
  onClose: () => void;
}

// -------------------------------------------
// Sub-components
// -------------------------------------------

/** Header with agent name and close button */
function ModalHeader({
  agentKey,
  agent,
  onClose,
}: {
  agentKey: AgentKey;
  agent: AgentState;
  onClose: () => void;
}) {
  const config = AGENT_CONFIG[agentKey];
  const Icon = config.icon;

  const statusColors = {
    idle: 'bg-gray-500',
    working: 'bg-blue-500',
    waiting: 'bg-yellow-500',
    error: 'bg-red-500',
  };

  const statusLabels = {
    idle: '대기',
    working: '작업중',
    waiting: '대기중',
    error: '오류',
  };

  return (
    <div className="flex items-center justify-between pb-4 border-b border-gray-700">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-gray-800">
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-white">{config.name}</h3>
          <p className="text-sm text-gray-500">{config.description}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium text-white ${statusColors[agent.status]}`}
        >
          <span className={`w-2 h-2 rounded-full bg-white ${agent.status === 'working' ? 'animate-pulse' : ''}`} />
          {statusLabels[agent.status]}
        </span>
        <button
          onClick={onClose}
          className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}

/** Statistics row */
function StatsRow({ agent }: { agent: AgentState }) {
  return (
    <div className="grid grid-cols-2 gap-4 p-4 bg-gray-800/50 rounded-lg">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="w-4 h-4 text-green-400" />
        <span className="text-sm text-gray-400">완료</span>
        <span className="text-sm font-semibold text-green-400">{agent.tasks_completed}</span>
      </div>
      <div className="flex items-center gap-2">
        <XCircle className="w-4 h-4 text-red-400" />
        <span className="text-sm text-gray-400">실패</span>
        <span className="text-sm font-semibold text-red-400">{agent.tasks_failed}</span>
      </div>
    </div>
  );
}

/** Processing stock display */
function ProcessingStock({ agent }: { agent: AgentState }) {
  if (!agent.processing_stock) return null;

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-white">처리 중인 종목</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold text-white">
          {agent.processing_stock_name || agent.processing_stock}
        </span>
        {agent.processing_stock_name && (
          <span className="text-sm text-gray-500">({agent.processing_stock})</span>
        )}
      </div>
    </div>
  );
}

/** Trade details grid */
function TradeDetailsGrid({ details }: { details: TradeDetails }) {
  // Format Korean Won
  const formatKRW = (value: number | undefined) => {
    if (value === undefined || value === null) return '-';
    return `₩${value.toLocaleString('ko-KR')}`;
  };

  // Get action color and icon
  const getActionStyle = (action: string | undefined) => {
    switch (action?.toUpperCase()) {
      case 'BUY':
        return { color: 'text-green-400', Icon: TrendingUp, label: '매수' };
      case 'SELL':
        return { color: 'text-red-400', Icon: TrendingDown, label: '매도' };
      case 'HOLD':
        return { color: 'text-yellow-400', Icon: Minus, label: '홀드' };
      default:
        return { color: 'text-gray-400', Icon: Minus, label: action || '-' };
    }
  };

  const actionStyle = getActionStyle(details.action);
  const ActionIcon = actionStyle.Icon;

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-white">거래 상세</span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        {/* Action */}
        <div className="col-span-2">
          <div className="text-gray-500 mb-1">액션</div>
          <div className={`flex items-center gap-2 ${actionStyle.color}`}>
            <ActionIcon className="w-4 h-4" />
            <span className="font-semibold">{actionStyle.label}</span>
          </div>
        </div>

        {/* Quantity */}
        <div>
          <div className="text-gray-500">수량</div>
          <div className="text-white font-medium">
            {details.quantity !== undefined ? `${details.quantity.toLocaleString()}주` : '-'}
          </div>
        </div>

        {/* Position % */}
        <div>
          <div className="text-gray-500">비중</div>
          <div className="text-white font-medium">
            {details.position_pct !== undefined ? `${details.position_pct.toFixed(1)}%` : '-'}
          </div>
        </div>

        {/* Entry Price */}
        <div>
          <div className="text-gray-500">진입가</div>
          <div className="text-white">{formatKRW(details.entry_price)}</div>
        </div>

        {/* Estimated Amount */}
        <div>
          <div className="text-gray-500">예상 금액</div>
          <div className="text-white">{formatKRW(details.estimated_amount || details.total_amount)}</div>
        </div>

        {/* Stop Loss */}
        <div>
          <div className="text-gray-500">손절가</div>
          <div className="text-red-400">{formatKRW(details.stop_loss)}</div>
        </div>

        {/* Take Profit */}
        <div>
          <div className="text-gray-500">익절가</div>
          <div className="text-green-400">{formatKRW(details.take_profit)}</div>
        </div>

        {/* Risk Score */}
        {details.risk_score !== undefined && (
          <div className="col-span-2">
            <div className="text-gray-500 mb-1">위험도</div>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    details.risk_score <= 3 ? 'bg-green-500' :
                    details.risk_score <= 6 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${details.risk_score * 10}%` }}
                />
              </div>
              <span className="text-white font-medium">{details.risk_score}/10</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Analysis summary view */
function AnalysisSummaryView({ summary }: { summary: AnalysisSummary }) {
  const getSignalStyle = (signal: string) => {
    const upperSignal = signal.toUpperCase();
    if (upperSignal.includes('BUY') || upperSignal.includes('BULL')) {
      return 'text-green-400 bg-green-500/10';
    }
    if (upperSignal.includes('SELL') || upperSignal.includes('BEAR')) {
      return 'text-red-400 bg-red-500/10';
    }
    return 'text-yellow-400 bg-yellow-500/10';
  };

  const analyses = [
    { key: 'technical', label: '기술적 분석', icon: BarChart3, data: summary.technical },
    { key: 'fundamental', label: '펀더멘털', icon: FileText, data: summary.fundamental },
    { key: 'sentiment', label: '센티멘트', icon: Activity, data: summary.sentiment },
  ];

  return (
    <div className="p-4 bg-gray-800/50 rounded-lg">
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-white">분석 요약</span>
      </div>

      <div className="space-y-3">
        {analyses.map(({ key, label, icon: Icon, data }) => {
          if (!data) return null;
          return (
            <div key={key} className="flex items-start gap-3">
              <Icon className="w-4 h-4 text-gray-400 mt-0.5" />
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-gray-400">{label}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${getSignalStyle(data.signal)}`}
                  >
                    {data.signal}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full"
                      style={{ width: `${data.confidence}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500">{data.confidence}%</span>
                </div>
                {data.key_factors && data.key_factors.length > 0 && (
                  <div className="mt-1 text-xs text-gray-500">
                    {data.key_factors.slice(0, 2).join(', ')}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Risk Assessment */}
        {summary.risk && (
          <div className="flex items-start gap-3 pt-2 border-t border-gray-700">
            <Shield className="w-4 h-4 text-gray-400 mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-gray-400">리스크</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    summary.risk.level === 'LOW' ? 'text-green-400 bg-green-500/10' :
                    summary.risk.level === 'MEDIUM' ? 'text-yellow-400 bg-yellow-500/10' :
                    'text-red-400 bg-red-500/10'
                  }`}
                >
                  {summary.risk.level}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      summary.risk.score <= 3 ? 'bg-green-500' :
                      summary.risk.score <= 6 ? 'bg-yellow-500' : 'bg-red-500'
                    }`}
                    style={{ width: `${summary.risk.score * 10}%` }}
                  />
                </div>
                <span className="text-xs text-gray-500">{summary.risk.score}/10</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Last result display */
function LastResultView({ result }: { result: LastResult }) {
  const formatKRW = (value: number | undefined) => {
    if (value === undefined || value === null) return '-';
    return `₩${value.toLocaleString('ko-KR')}`;
  };

  return (
    <div
      className={`p-4 rounded-lg ${
        result.success ? 'bg-green-500/10 border border-green-500/20' : 'bg-red-500/10 border border-red-500/20'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        {result.success ? (
          <CheckCircle2 className="w-4 h-4 text-green-400" />
        ) : (
          <XCircle className="w-4 h-4 text-red-400" />
        )}
        <span className={`text-sm font-medium ${result.success ? 'text-green-400' : 'text-red-400'}`}>
          최근 결과: {result.success ? '성공' : '실패'}
        </span>
      </div>
      <p className={`text-sm ${result.success ? 'text-green-300' : 'text-red-300'}`}>
        {result.message}
      </p>
      {result.success && result.filled_quantity && (
        <div className="mt-2 text-sm text-gray-400">
          {result.filled_quantity.toLocaleString()}주 @ {formatKRW(result.avg_price)} 체결
          {result.order_id && (
            <span className="ml-2 text-xs text-gray-500">#{result.order_id}</span>
          )}
        </div>
      )}
    </div>
  );
}

/** Current task display */
function CurrentTask({ task }: { task: string }) {
  return (
    <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <Clock className="w-4 h-4 text-blue-400 animate-pulse" />
        <span className="text-sm font-medium text-blue-400">현재 작업</span>
      </div>
      <p className="text-sm text-blue-300">{task}</p>
    </div>
  );
}

/** Error message display */
function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-red-400" />
        <span className="text-sm font-medium text-red-400">오류</span>
      </div>
      <p className="text-sm text-red-300">{message}</p>
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

export function AgentDetailModal({ agentKey, agent, onClose }: AgentDetailModalProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6 space-y-4">
          {/* Header */}
          <ModalHeader agentKey={agentKey} agent={agent} onClose={onClose} />

          {/* Statistics */}
          <StatsRow agent={agent} />

          {/* Processing Stock */}
          <ProcessingStock agent={agent} />

          {/* Current Task */}
          {agent.current_task && <CurrentTask task={agent.current_task} />}

          {/* Trade Details */}
          {agent.trade_details && <TradeDetailsGrid details={agent.trade_details} />}

          {/* Analysis Summary */}
          {agent.analysis_summary && <AnalysisSummaryView summary={agent.analysis_summary} />}

          {/* Last Result */}
          {agent.last_result && <LastResultView result={agent.last_result} />}

          {/* Error Message */}
          {agent.error_message && <ErrorMessage message={agent.error_message} />}

          {/* Last Action Time */}
          {agent.last_action_time && (
            <div className="text-xs text-gray-500 text-center pt-2 border-t border-gray-700">
              마지막 작업: {new Date(agent.last_action_time).toLocaleString('ko-KR')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentDetailModal;
