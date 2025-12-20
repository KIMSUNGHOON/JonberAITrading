/**
 * Workflow Progress Component
 *
 * Visual step indicator showing all workflow stages with real-time updates.
 */

import { useMemo } from 'react';
import {
  GitBranch,
  LineChart,
  Building2,
  MessageSquare,
  Shield,
  Brain,
  UserCheck,
  Rocket,
  CheckCircle2,
  Circle,
  Loader2,
} from 'lucide-react';
import type { SessionStatus } from '@/types';

// Workflow stages for Stock analysis (matching backend AnalysisStage enum)
const STOCK_WORKFLOW_STAGES = [
  { id: 'decomposition', label: 'Task Decomposition', icon: GitBranch, description: 'Breaking down analysis tasks' },
  { id: 'technical', label: 'Technical Analysis', icon: LineChart, description: 'Price patterns & indicators' },
  { id: 'fundamental', label: 'Fundamental Analysis', icon: Building2, description: 'Company financials & metrics' },
  { id: 'sentiment', label: 'Sentiment Analysis', icon: MessageSquare, description: 'Market sentiment & news' },
  { id: 'risk', label: 'Risk Assessment', icon: Shield, description: 'Risk evaluation & position sizing' },
  { id: 'synthesis', label: 'Synthesis', icon: Brain, description: 'Combining all analyses' },
  { id: 'approval', label: 'Human Approval', icon: UserCheck, description: 'Awaiting your decision' },
  { id: 'execution', label: 'Execution', icon: Rocket, description: 'Trade execution' },
] as const;

// Workflow stages for Coin analysis (matching backend CoinAnalysisStage enum)
const COIN_WORKFLOW_STAGES = [
  { id: 'data_collection', label: 'Data Collection', icon: GitBranch, description: 'Collecting market data' },
  { id: 'technical', label: 'Technical Analysis', icon: LineChart, description: 'Price patterns & indicators' },
  { id: 'market_analysis', label: 'Market Analysis', icon: Building2, description: 'Market trends & orderbook' },
  { id: 'sentiment', label: 'Sentiment Analysis', icon: MessageSquare, description: 'Market sentiment & news' },
  { id: 'risk', label: 'Risk Assessment', icon: Shield, description: 'Risk evaluation & position sizing' },
  { id: 'synthesis', label: 'Synthesis', icon: Brain, description: 'Combining all analyses' },
  { id: 'approval', label: 'Human Approval', icon: UserCheck, description: 'Awaiting your decision' },
  { id: 'execution', label: 'Execution', icon: Rocket, description: 'Trade execution' },
] as const;

// Helper to detect if ticker is coin market (contains '-')
function isCoinMarket(ticker: string): boolean {
  return ticker.includes('-');
}

// Get appropriate workflow stages based on ticker
function getWorkflowStages(ticker: string) {
  return isCoinMarket(ticker) ? COIN_WORKFLOW_STAGES : STOCK_WORKFLOW_STAGES;
}

type StageStatus = 'pending' | 'in_progress' | 'completed';

interface WorkflowProgressProps {
  currentStage: string | null;
  status: SessionStatus | 'idle';
  ticker: string;
}

export function WorkflowProgress({ currentStage, status, ticker }: WorkflowProgressProps) {
  // Get appropriate stages based on ticker type
  const WORKFLOW_STAGES = useMemo(() => getWorkflowStages(ticker), [ticker]);

  // Calculate stage statuses
  const stageStatuses = useMemo(() => {
    const statuses = new Map<string, StageStatus>();
    const currentIndex = WORKFLOW_STAGES.findIndex(s => s.id === currentStage);

    WORKFLOW_STAGES.forEach((stage, index) => {
      if (status === 'completed' || status === 'cancelled') {
        statuses.set(stage.id, 'completed');
      } else if (index < currentIndex) {
        statuses.set(stage.id, 'completed');
      } else if (index === currentIndex) {
        statuses.set(stage.id, 'in_progress');
      } else {
        statuses.set(stage.id, 'pending');
      }
    });

    return statuses;
  }, [currentStage, status, WORKFLOW_STAGES]);

  // Calculate progress percentage
  const progressPercent = useMemo(() => {
    if (status === 'completed' || status === 'cancelled') return 100;
    const currentIndex = WORKFLOW_STAGES.findIndex(s => s.id === currentStage);
    if (currentIndex === -1) return 0;
    return Math.round(((currentIndex + 0.5) / WORKFLOW_STAGES.length) * 100);
  }, [currentStage, status, WORKFLOW_STAGES]);

  if (status === 'idle') return null;

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-lg">Workflow Progress</h3>
          <p className="text-sm text-gray-400">
            Analyzing <span className="text-blue-400 font-medium">{ticker}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-right">
            <span className="text-2xl font-bold text-blue-400">{progressPercent}%</span>
            <p className="text-xs text-gray-400">Complete</p>
          </div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-2 bg-surface rounded-full mb-6 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-500 ease-out"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Stages - Horizontal Scroll on Mobile */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {WORKFLOW_STAGES.map((stage, index) => {
          const stageStatus = stageStatuses.get(stage.id) || 'pending';
          const Icon = stage.icon;

          return (
            <StageItem
              key={stage.id}
              stage={stage}
              status={stageStatus}
              icon={Icon}
              isLast={index === WORKFLOW_STAGES.length - 1}
            />
          );
        })}
      </div>

      {/* Current Stage Detail */}
      {currentStage && status === 'running' && (
        <CurrentStageDetail
          stage={WORKFLOW_STAGES.find(s => s.id === currentStage)}
        />
      )}
    </div>
  );
}

interface StageItemProps {
  stage: { id: string; label: string; description: string };
  status: StageStatus;
  icon: React.ComponentType<{ className?: string }>;
  isLast: boolean;
}

function StageItem({ stage, status, icon: Icon }: StageItemProps) {
  const statusColors = {
    pending: 'bg-surface-light text-gray-500 border-gray-700',
    in_progress: 'bg-blue-500/20 text-blue-400 border-blue-500 ring-2 ring-blue-500/30',
    completed: 'bg-green-500/20 text-green-400 border-green-500',
  };

  const StatusIcon = status === 'completed'
    ? CheckCircle2
    : status === 'in_progress'
      ? Loader2
      : Circle;

  return (
    <div className="flex flex-col items-center min-w-[80px] flex-shrink-0">
      {/* Icon Circle */}
      <div
        className={`
          w-12 h-12 rounded-full flex items-center justify-center border-2
          transition-all duration-300
          ${statusColors[status]}
        `}
      >
        {status === 'in_progress' ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : (
          <Icon className="w-5 h-5" />
        )}
      </div>

      {/* Label */}
      <span className={`
        mt-2 text-xs text-center font-medium leading-tight
        ${status === 'in_progress' ? 'text-blue-400' :
          status === 'completed' ? 'text-green-400' : 'text-gray-500'}
      `}>
        {stage.label}
      </span>

      {/* Status Indicator */}
      <StatusIcon className={`
        w-3 h-3 mt-1
        ${status === 'completed' ? 'text-green-400' :
          status === 'in_progress' ? 'text-blue-400 animate-spin' : 'text-gray-600'}
      `} />
    </div>
  );
}

interface CurrentStageDetailProps {
  stage?: { id: string; label: string; description: string };
}

function CurrentStageDetail({ stage }: CurrentStageDetailProps) {
  if (!stage) return null;

  return (
    <div className="mt-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-blue-500/20 rounded-lg flex items-center justify-center">
          <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
        </div>
        <div>
          <p className="font-medium text-blue-400">{stage.label}</p>
          <p className="text-sm text-gray-400">{stage.description}</p>
        </div>
      </div>
    </div>
  );
}

// Compact version for sidebar/header
export function WorkflowProgressCompact({ currentStage, status, ticker = '' }: { currentStage: string | null; status: SessionStatus | 'idle'; ticker?: string }) {
  if (status === 'idle') return null;

  const stages = getWorkflowStages(ticker);
  const currentIndex = stages.findIndex(s => s.id === currentStage);
  const stage = stages[currentIndex];
  const progressPercent = status === 'completed' ? 100 :
    currentIndex === -1 ? 0 :
    Math.round(((currentIndex + 0.5) / stages.length) * 100);

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-surface-light rounded-lg">
      {status === 'running' && (
        <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-400 truncate">
            {stage?.label || 'Starting...'}
          </span>
          <span className="text-blue-400 font-medium">{progressPercent}%</span>
        </div>
        <div className="h-1 bg-surface rounded-full mt-1">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>
    </div>
  );
}
