/**
 * AgentWorkflowGraph Component
 *
 * Displays trading agents in a vertical workflow graph.
 * Each agent node is clickable to show detailed information.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { RefreshCw, AlertCircle } from 'lucide-react';
import { getAgentStates } from '@/api/client';
import { AgentNode } from './AgentNode';
import { AgentDetailModal } from './AgentDetailModal';
import { AGENT_ORDER } from './types';
import type { AgentKey, AgentState } from './types';

// -------------------------------------------
// Constants
// -------------------------------------------

const POLL_INTERVAL_MS = 3000;

// -------------------------------------------
// Main Component
// -------------------------------------------

interface AgentWorkflowGraphProps {
  /** Optional class name for custom styling */
  className?: string;
}

export function AgentWorkflowGraph({ className = '' }: AgentWorkflowGraphProps) {
  // State
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [selectedAgent, setSelectedAgent] = useState<AgentKey | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Refs for node positions (used by edges)
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Record<AgentKey, HTMLDivElement | null>>({
    strategy: null,
    portfolio: null,
    order: null,
    risk: null,
  });

  // Fetch agent states
  const fetchAgentStates = useCallback(async () => {
    try {
      const response = await getAgentStates();
      setAgents(response.agents as Record<string, AgentState>);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      console.error('[AgentWorkflowGraph] Failed to fetch agent states:', err);
      setError('에이전트 상태를 가져올 수 없습니다');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial fetch and polling
  useEffect(() => {
    fetchAgentStates();
    const interval = setInterval(fetchAgentStates, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchAgentStates]);

  // Handle node click
  const handleNodeClick = useCallback((agentKey: AgentKey) => {
    setSelectedAgent(agentKey);
  }, []);

  // Handle modal close
  const handleModalClose = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  // Render loading state
  if (isLoading && Object.keys(agents).length === 0) {
    return (
      <div className={`bg-gray-900 rounded-lg p-6 ${className}`}>
        <div className="flex items-center justify-center gap-2 text-gray-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>에이전트 상태 로딩중...</span>
        </div>
      </div>
    );
  }

  // Render error state
  if (error && Object.keys(agents).length === 0) {
    return (
      <div className={`bg-gray-900 rounded-lg p-6 ${className}`}>
        <div className="flex items-center justify-center gap-2 text-red-400">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-gray-900 rounded-lg ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h3 className="text-lg font-semibold text-white">Agent Workflow</h3>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-500">
              {lastUpdated.toLocaleTimeString('ko-KR')}
            </span>
          )}
          <button
            onClick={fetchAgentStates}
            className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white transition-colors"
            title="새로고침"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Workflow Graph Container */}
      <div ref={containerRef} className="relative p-4">
        {/* Agent Nodes with Connectors */}
        <div className="relative flex flex-col">
          {AGENT_ORDER.map((agentKey, index) => {
            const isLastNode = index === AGENT_ORDER.length - 1;
            const currentAgent = agents[agentKey];
            const nextAgent = !isLastNode ? agents[AGENT_ORDER[index + 1]] : null;
            const isConnectorActive = currentAgent?.status === 'working' || nextAgent?.status === 'working';

            return (
              <div key={agentKey} className="relative">
                {/* Agent Node */}
                <AgentNode
                  ref={(el) => { nodeRefs.current[agentKey] = el; }}
                  agentKey={agentKey}
                  agent={currentAgent}
                  onClick={() => handleNodeClick(agentKey)}
                />

                {/* Connector to next node */}
                {!isLastNode && (
                  <div className="relative flex justify-center py-2">
                    {/* Vertical Line */}
                    <div
                      className={`w-0.5 h-6 ${
                        isConnectorActive
                          ? 'bg-gradient-to-b from-blue-500 to-blue-400 animate-pulse'
                          : 'bg-gray-700'
                      }`}
                    />
                    {/* Arrow */}
                    <div
                      className={`absolute bottom-1 left-1/2 -translate-x-1/2 w-0 h-0
                        border-l-[6px] border-l-transparent
                        border-r-[6px] border-r-transparent
                        border-t-[8px] ${
                          isConnectorActive
                            ? 'border-t-blue-400'
                            : 'border-t-gray-700'
                        }`}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Agent Detail Modal */}
      {selectedAgent && agents[selectedAgent] && (
        <AgentDetailModal
          agentKey={selectedAgent}
          agent={agents[selectedAgent]}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
}

export default AgentWorkflowGraph;
