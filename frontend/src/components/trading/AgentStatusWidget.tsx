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

interface AgentState {
  name: string;
  status: 'idle' | 'working' | 'waiting' | 'error';
  current_task: string | null;
  last_action: string | null;
  last_action_time: string | null;
  error_message: string | null;
  tasks_completed: number;
  tasks_failed: number;
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

      {/* Current Task */}
      {agent.current_task && (
        <div className="mt-2 p-2 bg-gray-900/50 rounded text-xs">
          <div className="text-gray-400">현재 작업:</div>
          <div className="text-white truncate">{agent.current_task}</div>
        </div>
      )}

      {/* Last Action */}
      {agent.last_action && (
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
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(agents).map(([key, agent]) => (
              <AgentCard key={key} agentKey={key} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
