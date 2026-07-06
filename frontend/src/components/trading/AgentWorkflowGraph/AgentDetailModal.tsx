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
import { pnlColor } from '@/utils/pnl';
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
    idle: 'bg-muted text-ink',
    working: 'bg-accent text-canvas',
    waiting: 'bg-warn text-canvas',
    error: 'bg-down text-ink',
  };

  const statusLabels = {
    idle: '대기',
    working: '작업중',
    waiting: '대기중',
    error: '오류',
  };

  return (
    <div className="flex items-center justify-between pb-4 border-b border-hairline">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-elevated">
          <Icon className="w-6 h-6 text-ink" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-ink">{config.name}</h3>
          <p className="text-sm text-dim">{config.description}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${statusColors[agent.status]}`}
        >
          <span className={`w-2 h-2 rounded-full bg-ink ${agent.status === 'working' ? 'animate-pulse' : ''}`} />
          {statusLabels[agent.status]}
        </span>
        <button
          onClick={onClose}
          className="p-1.5 rounded hover:bg-elevated text-muted hover:text-ink transition-colors"
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
    <div className="grid grid-cols-2 gap-4 p-4 bg-elevated/50 rounded-lg">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="w-4 h-4 text-up" />
        <span className="text-sm text-muted">완료</span>
        <span className="text-sm font-semibold text-up tabular-nums">{agent.tasks_completed}</span>
      </div>
      <div className="flex items-center gap-2">
        <XCircle className="w-4 h-4 text-down" />
        <span className="text-sm text-muted">실패</span>
        <span className="text-sm font-semibold text-down tabular-nums">{agent.tasks_failed}</span>
      </div>
    </div>
  );
}

/** Processing stock display */
function ProcessingStock({ agent }: { agent: AgentState }) {
  if (!agent.processing_stock) return null;

  return (
    <div className="p-4 bg-elevated/50 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-4 h-4 text-accent" />
        <span className="text-sm font-medium text-ink">처리 중인 종목</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold text-ink">
          {agent.processing_stock_name || agent.processing_stock}
        </span>
        {agent.processing_stock_name && (
          <span className="text-sm text-dim">({agent.processing_stock})</span>
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

  // Get action color and icon. App-wide ACTION map (matches
  // ScannerResultsPage/AnalysisDetailPage/AgentStatusWidget): BUY/ADD is
  // bullish -> pnlColor(1) (up/green), SELL/REDUCE is bearish -> pnlColor(-1)
  // (down/red), WATCH -> warn, AVOID -> accent, HOLD/default -> muted.
  const getActionStyle = (action: string | undefined) => {
    switch (action?.toUpperCase()) {
      case 'BUY':
        return { color: pnlColor(1), Icon: TrendingUp, label: '매수' };
      case 'ADD':
        return { color: pnlColor(1), Icon: TrendingUp, label: action };
      case 'SELL':
        return { color: pnlColor(-1), Icon: TrendingDown, label: '매도' };
      case 'REDUCE':
        return { color: pnlColor(-1), Icon: TrendingDown, label: action };
      case 'WATCH':
        return { color: 'text-warn', Icon: Minus, label: action };
      case 'AVOID':
        return { color: 'text-accent', Icon: Minus, label: action };
      case 'HOLD':
        return { color: 'text-muted', Icon: Minus, label: '홀드' };
      default:
        return { color: 'text-muted', Icon: Minus, label: action || '-' };
    }
  };

  const actionStyle = getActionStyle(details.action);
  const ActionIcon = actionStyle.Icon;

  return (
    <div className="p-4 bg-elevated/50 rounded-lg">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="w-4 h-4 text-accent" />
        <span className="text-sm font-medium text-ink">거래 상세</span>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        {/* Action */}
        <div className="col-span-2">
          <div className="text-dim mb-1">액션</div>
          <div className={`flex items-center gap-2 ${actionStyle.color}`}>
            <ActionIcon className="w-4 h-4" />
            <span className="font-semibold">{actionStyle.label}</span>
          </div>
        </div>

        {/* Quantity */}
        <div>
          <div className="text-dim">수량</div>
          <div className="text-ink font-medium tabular-nums">
            {details.quantity !== undefined ? `${details.quantity.toLocaleString()}주` : '-'}
          </div>
        </div>

        {/* Position % */}
        <div>
          <div className="text-dim">비중</div>
          <div className="text-ink font-medium tabular-nums">
            {details.position_pct !== undefined ? `${details.position_pct.toFixed(1)}%` : '-'}
          </div>
        </div>

        {/* Entry Price */}
        <div>
          <div className="text-dim">진입가</div>
          <div className="text-ink tabular-nums">{formatKRW(details.entry_price)}</div>
        </div>

        {/* Estimated Amount */}
        <div>
          <div className="text-dim">예상 금액</div>
          <div className="text-ink tabular-nums">{formatKRW(details.estimated_amount || details.total_amount)}</div>
        </div>

        {/* Stop Loss */}
        <div>
          <div className="text-dim">손절가</div>
          <div className="text-down tabular-nums">{formatKRW(details.stop_loss)}</div>
        </div>

        {/* Take Profit */}
        <div>
          <div className="text-dim">익절가</div>
          <div className="text-up tabular-nums">{formatKRW(details.take_profit)}</div>
        </div>

        {/* Risk Score */}
        {details.risk_score !== undefined && (
          <div className="col-span-2">
            <div className="text-dim mb-1">위험도</div>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-elevated rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    details.risk_score <= 3 ? 'bg-up' :
                    details.risk_score <= 6 ? 'bg-warn' : 'bg-down'
                  }`}
                  style={{ width: `${details.risk_score * 10}%` }}
                />
              </div>
              <span className="text-ink font-medium tabular-nums">{details.risk_score}/10</span>
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
      return `${pnlColor(1)} bg-up/10`;
    }
    if (upperSignal.includes('SELL') || upperSignal.includes('BEAR')) {
      return `${pnlColor(-1)} bg-down/10`;
    }
    return 'text-muted bg-elevated';
  };

  const analyses = [
    { key: 'technical', label: '기술적 분석', icon: BarChart3, data: summary.technical },
    { key: 'fundamental', label: '펀더멘털', icon: FileText, data: summary.fundamental },
    { key: 'sentiment', label: '센티멘트', icon: Activity, data: summary.sentiment },
  ];

  return (
    <div className="p-4 bg-elevated/50 rounded-lg">
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 className="w-4 h-4 text-accent" />
        <span className="text-sm font-medium text-ink">분석 요약</span>
      </div>

      <div className="space-y-3">
        {analyses.map(({ key, label, icon: Icon, data }) => {
          if (!data) return null;
          return (
            <div key={key} className="flex items-start gap-3">
              <Icon className="w-4 h-4 text-muted mt-0.5" />
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-muted">{label}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${getSignalStyle(data.signal)}`}
                  >
                    {data.signal}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-elevated rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent rounded-full"
                      style={{ width: `${data.confidence}%` }}
                    />
                  </div>
                  <span className="text-xs text-dim tabular-nums">{data.confidence}%</span>
                </div>
                {data.key_factors && data.key_factors.length > 0 && (
                  <div className="mt-1 text-xs text-dim">
                    {data.key_factors.slice(0, 2).join(', ')}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Risk Assessment */}
        {summary.risk && (
          <div className="flex items-start gap-3 pt-2 border-t border-hairline">
            <Shield className="w-4 h-4 text-muted mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-muted">리스크</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    summary.risk.level === 'LOW' ? 'text-up bg-up/10' :
                    summary.risk.level === 'MEDIUM' ? 'text-warn bg-warn/10' :
                    'text-down bg-down/10'
                  }`}
                >
                  {summary.risk.level}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-elevated rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      summary.risk.score <= 3 ? 'bg-up' :
                      summary.risk.score <= 6 ? 'bg-warn' : 'bg-down'
                    }`}
                    style={{ width: `${summary.risk.score * 10}%` }}
                  />
                </div>
                <span className="text-xs text-dim tabular-nums">{summary.risk.score}/10</span>
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
        result.success ? 'bg-up/10 border border-up/20' : 'bg-down/10 border border-down/20'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        {result.success ? (
          <CheckCircle2 className="w-4 h-4 text-up" />
        ) : (
          <XCircle className="w-4 h-4 text-down" />
        )}
        <span className={`text-sm font-medium ${result.success ? 'text-up' : 'text-down'}`}>
          최근 결과: {result.success ? '성공' : '실패'}
        </span>
      </div>
      <p className={`text-sm ${result.success ? 'text-up' : 'text-down'}`}>
        {result.message}
      </p>
      {result.success && result.filled_quantity && (
        <div className="mt-2 text-sm text-muted">
          {result.filled_quantity.toLocaleString()}주 @ {formatKRW(result.avg_price)} 체결
          {result.order_id && (
            <span className="ml-2 text-xs text-dim">#{result.order_id}</span>
          )}
        </div>
      )}
    </div>
  );
}

/** Current task display */
function CurrentTask({ task }: { task: string }) {
  return (
    <div className="p-4 bg-accent/10 border border-accent/20 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <Clock className="w-4 h-4 text-accent animate-pulse" />
        <span className="text-sm font-medium text-accent">현재 작업</span>
      </div>
      <p className="text-sm text-accent">{task}</p>
    </div>
  );
}

/** Error message display */
function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="p-4 bg-down/10 border border-down/20 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-down" />
        <span className="text-sm font-medium text-down">오류</span>
      </div>
      <p className="text-sm text-down">{message}</p>
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
        className="bg-card border border-hairline rounded-lg max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto shadow-2xl"
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
            <div className="text-xs text-dim text-center pt-2 border-t border-hairline">
              마지막 작업: {new Date(agent.last_action_time).toLocaleString('ko-KR')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentDetailModal;
