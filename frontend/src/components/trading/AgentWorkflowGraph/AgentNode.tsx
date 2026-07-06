/**
 * AgentNode Component
 *
 * Represents a single agent in the workflow graph.
 * Clickable to show detailed information.
 */

import { forwardRef } from 'react';
import {
  Sliders,
  Briefcase,
  ShoppingCart,
  Shield,
  Loader2,
  Clock,
  AlertCircle,
  Circle,
  ChevronRight,
} from 'lucide-react';
import type { AgentKey, AgentState, AgentConfig, AgentNodeProps } from './types';

// -------------------------------------------
// Agent Configuration
// -------------------------------------------

export const AGENT_CONFIG: Record<AgentKey, AgentConfig> = {
  strategy: {
    name: 'Strategy Engine',
    description: '진입/청산 전략 평가',
    icon: Sliders,
  },
  portfolio: {
    name: 'Portfolio Agent',
    description: '포지션 크기 계산',
    icon: Briefcase,
  },
  order: {
    name: 'Order Agent',
    description: '주문 실행',
    icon: ShoppingCart,
  },
  risk: {
    name: 'Risk Monitor',
    description: '리스크 모니터링',
    icon: Shield,
  },
};

// -------------------------------------------
// Status Badge Sub-component
// -------------------------------------------

interface StatusBadgeProps {
  status: AgentState['status'];
}

function StatusBadge({ status }: StatusBadgeProps) {
  const config = {
    idle: {
      label: '대기',
      color: 'bg-muted/20 text-muted',
      Icon: Circle,
      animate: false,
    },
    working: {
      label: '작업중',
      color: 'bg-accent/20 text-accent',
      Icon: Loader2,
      animate: true,
    },
    waiting: {
      label: '대기중',
      color: 'bg-warn/20 text-warn',
      Icon: Clock,
      animate: false,
    },
    error: {
      label: '오류',
      color: 'bg-down/20 text-down',
      Icon: AlertCircle,
      animate: false,
    },
  };

  const { label, color, Icon, animate } = config[status];

  return (
    <span className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${color}`}>
      <Icon className={`w-3 h-3 ${animate ? 'animate-spin' : ''}`} />
      {label}
    </span>
  );
}

// -------------------------------------------
// Main AgentNode Component
// -------------------------------------------

export const AgentNode = forwardRef<HTMLDivElement, AgentNodeProps>(
  ({ agentKey, agent, onClick }, ref) => {
    const config = AGENT_CONFIG[agentKey];
    const Icon = config.icon;

    // Handle undefined agent state
    if (!agent) {
      return (
        <div
          ref={ref}
          className="w-full p-4 rounded-lg border border-hairline bg-elevated/30"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-elevated">
              <Icon className="w-5 h-5 text-muted" />
            </div>
            <div>
              <div className="font-medium text-muted">{config.name}</div>
              <div className="text-xs text-dim">Loading...</div>
            </div>
          </div>
        </div>
      );
    }

    const isWorking = agent.status === 'working';
    const isError = agent.status === 'error';

    return (
      <div
        ref={ref}
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onClick(); }}
        className={`
          relative w-full p-4 rounded-lg border transition-all cursor-pointer text-left
          hover:border-accent/50 hover:bg-elevated/50
          ${isWorking ? 'border-accent/50 bg-accent/5 ring-1 ring-accent/20' :
            isError ? 'border-down/30 bg-down/5' :
            'border-hairline bg-elevated/30'}
        `}
      >
        {/* Header: Icon + Name + Status Badge */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg transition-colors ${
              isWorking ? 'bg-accent/20' :
              isError ? 'bg-down/20' :
              'bg-elevated'
            }`}>
              <Icon className={`w-5 h-5 ${
                isWorking ? 'text-accent' :
                isError ? 'text-down' :
                'text-muted'
              }`} />
            </div>
            <div>
              <div className="font-medium text-ink">{config.name}</div>
              <div className="text-xs text-dim">{config.description}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={agent.status} />
          </div>
        </div>

        {/* Current Task - Only when working */}
        {isWorking && agent.current_task && (
          <div className="mt-3 p-2 bg-accent/10 border border-accent/20 rounded text-sm text-accent">
            {agent.current_task}
          </div>
        )}

        {/* Processing Stock */}
        {agent.processing_stock && (
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="text-dim">처리중:</span>
            <span className="text-ink font-medium">
              {agent.processing_stock_name || agent.processing_stock}
            </span>
            <span className="text-dim">({agent.processing_stock})</span>
          </div>
        )}

        {/* Quick Stats */}
        <div className="mt-2 flex items-center gap-4 text-xs">
          <span className="text-dim">
            완료: <span className="text-up tabular-nums">{agent.tasks_completed}</span>
          </span>
          {agent.tasks_failed > 0 && (
            <span className="text-dim">
              실패: <span className="text-down tabular-nums">{agent.tasks_failed}</span>
            </span>
          )}
        </div>

        {/* Error Message Preview */}
        {agent.error_message && (
          <div className="mt-2 p-2 bg-down/10 border border-down/20 rounded text-xs text-down truncate">
            {agent.error_message}
          </div>
        )}

        {/* Expand Indicator */}
        <ChevronRight className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-dim" />
      </div>
    );
  }
);

AgentNode.displayName = 'AgentNode';

export default AgentNode;
