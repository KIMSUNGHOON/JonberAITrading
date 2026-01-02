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
      color: 'bg-gray-500/20 text-gray-400',
      Icon: Circle,
      animate: false,
    },
    working: {
      label: '작업중',
      color: 'bg-blue-500/20 text-blue-400',
      Icon: Loader2,
      animate: true,
    },
    waiting: {
      label: '대기중',
      color: 'bg-yellow-500/20 text-yellow-400',
      Icon: Clock,
      animate: false,
    },
    error: {
      label: '오류',
      color: 'bg-red-500/20 text-red-400',
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
          className="w-full p-4 rounded-lg border border-gray-700 bg-gray-800/30"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-gray-700">
              <Icon className="w-5 h-5 text-gray-400" />
            </div>
            <div>
              <div className="font-medium text-gray-400">{config.name}</div>
              <div className="text-xs text-gray-500">Loading...</div>
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
          hover:border-blue-500/50 hover:bg-gray-800/50
          ${isWorking ? 'border-blue-500/50 bg-blue-500/5 ring-1 ring-blue-500/20' :
            isError ? 'border-red-500/30 bg-red-500/5' :
            'border-gray-700 bg-gray-800/30'}
        `}
      >
        {/* Header: Icon + Name + Status Badge */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg transition-colors ${
              isWorking ? 'bg-blue-500/20' :
              isError ? 'bg-red-500/20' :
              'bg-gray-700'
            }`}>
              <Icon className={`w-5 h-5 ${
                isWorking ? 'text-blue-400' :
                isError ? 'text-red-400' :
                'text-gray-400'
              }`} />
            </div>
            <div>
              <div className="font-medium text-white">{config.name}</div>
              <div className="text-xs text-gray-500">{config.description}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={agent.status} />
          </div>
        </div>

        {/* Current Task - Only when working */}
        {isWorking && agent.current_task && (
          <div className="mt-3 p-2 bg-blue-500/10 border border-blue-500/20 rounded text-sm text-blue-300">
            {agent.current_task}
          </div>
        )}

        {/* Processing Stock */}
        {agent.processing_stock && (
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className="text-gray-500">처리중:</span>
            <span className="text-white font-medium">
              {agent.processing_stock_name || agent.processing_stock}
            </span>
            <span className="text-gray-500">({agent.processing_stock})</span>
          </div>
        )}

        {/* Quick Stats */}
        <div className="mt-2 flex items-center gap-4 text-xs">
          <span className="text-gray-500">
            완료: <span className="text-green-400">{agent.tasks_completed}</span>
          </span>
          {agent.tasks_failed > 0 && (
            <span className="text-gray-500">
              실패: <span className="text-red-400">{agent.tasks_failed}</span>
            </span>
          )}
        </div>

        {/* Error Message Preview */}
        {agent.error_message && (
          <div className="mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400 truncate">
            {agent.error_message}
          </div>
        )}

        {/* Expand Indicator */}
        <ChevronRight className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
      </div>
    );
  }
);

AgentNode.displayName = 'AgentNode';

export default AgentNode;
