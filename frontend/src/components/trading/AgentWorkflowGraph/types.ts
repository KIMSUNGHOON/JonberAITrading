/**
 * Type definitions for Agent Workflow Graph
 */

// -------------------------------------------
// Agent Status Types
// -------------------------------------------

export type AgentStatusType = 'idle' | 'working' | 'waiting' | 'error';

export interface TradeDetails {
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

export interface AnalysisSummary {
  technical?: { signal: string; confidence: number; key_factors?: string[] };
  fundamental?: { signal: string; confidence: number; key_factors?: string[] };
  sentiment?: { signal: string; confidence: number; key_factors?: string[] };
  risk?: { level: string; score: number; factors?: string[] };
}

export interface LastResult {
  success: boolean;
  message: string;
  order_id?: string;
  filled_quantity?: number;
  avg_price?: number;
  quantity?: number;
  estimated_amount?: number;
}

export interface AgentState {
  name: string;
  status: AgentStatusType;
  current_task: string | null;
  last_action: string | null;
  last_action_time: string | null;
  error_message: string | null;
  tasks_completed: number;
  tasks_failed: number;
  processing_stock?: string | null;
  processing_stock_name?: string | null;
  trade_details?: TradeDetails | null;
  analysis_summary?: AnalysisSummary | null;
  last_result?: LastResult | null;
}

// -------------------------------------------
// Agent Config Types
// -------------------------------------------

export type AgentKey = 'strategy' | 'portfolio' | 'order' | 'risk';

export interface AgentConfig {
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}

// -------------------------------------------
// Workflow Connection Types
// -------------------------------------------

export interface WorkflowConnection {
  from: AgentKey;
  to: AgentKey;
}

// -------------------------------------------
// Component Props Types
// -------------------------------------------

export interface AgentNodeProps {
  agentKey: AgentKey;
  agent: AgentState | undefined;
  onClick: () => void;
  nodeRef?: React.RefObject<HTMLDivElement>;
}

export interface AgentDetailModalProps {
  agentKey: AgentKey;
  agent: AgentState;
  onClose: () => void;
}

export interface AgentEdgeContainerProps {
  connections: WorkflowConnection[];
  agents: Record<string, AgentState>;
  containerRef: React.RefObject<HTMLDivElement>;
}

// -------------------------------------------
// Constants
// -------------------------------------------

export const AGENT_ORDER: AgentKey[] = ['strategy', 'portfolio', 'order', 'risk'];

export const WORKFLOW_CONNECTIONS: WorkflowConnection[] = [
  { from: 'strategy', to: 'portfolio' },
  { from: 'portfolio', to: 'order' },
  { from: 'order', to: 'risk' },
];
