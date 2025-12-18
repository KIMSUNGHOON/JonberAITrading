/**
 * Main Content Component
 *
 * Dashboard area with chart and analysis panels.
 */

import { useShallow } from 'zustand/shallow';
import { useStore } from '@/store';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { AnalysisPanel } from '@/components/analysis/AnalysisPanel';
import { ReasoningLog } from '@/components/analysis/ReasoningLog';
import { WorkflowProgress } from '@/components/analysis/WorkflowProgress';
import { ProposalCard } from '@/components/approval/ProposalCard';
import { PositionCard } from '@/components/position/PositionCard';
import { WelcomePanel } from '@/components/analysis/WelcomePanel';

export function MainContent() {
  const { sessionId, ticker, status, currentStage } = useStore(
    useShallow((state) => ({
      sessionId: state.activeSessionId,
      ticker: state.ticker,
      status: state.status,
      currentStage: state.currentStage,
    }))
  );
  const { analyses, reasoningLog } = useStore(
    useShallow((state) => ({
      analyses: state.analyses,
      reasoningLog: state.reasoningLog,
    }))
  );
  const { proposal, awaitingApproval } = useStore(
    useShallow((state) => ({
      proposal: state.tradeProposal,
      awaitingApproval: state.awaitingApproval,
    }))
  );
  const activePosition = useStore((state) => state.activePosition);
  const showChartPanel = useStore((state) => state.showChartPanel);

  // Show welcome panel when idle
  if (status === 'idle' && !sessionId) {
    return <WelcomePanel />;
  }

  return (
    <div className="p-3 md:p-4 space-y-3 h-full flex flex-col">
      {/* Workflow Progress - Compact at top */}
      {ticker && status !== 'idle' && (
        <section className="flex-shrink-0">
          <WorkflowProgress
            currentStage={currentStage}
            status={status}
            ticker={ticker}
          />
        </section>
      )}

      {/* Main Content Grid - Flexible height */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-3 min-h-0">
        {/* Left Column */}
        <div className="flex flex-col gap-3 min-h-0 overflow-y-auto">
          {/* Chart Section */}
          {showChartPanel && ticker && (
            <section className="flex-shrink-0">
              <ChartPanel ticker={ticker} />
            </section>
          )}

          {/* Active Position */}
          {activePosition && (
            <section className="flex-shrink-0">
              <PositionCard position={activePosition} />
            </section>
          )}

          {/* Trade Proposal */}
          {proposal && awaitingApproval && (
            <section className="flex-shrink-0">
              <ProposalCard proposal={proposal} />
            </section>
          )}

          {/* Analysis Grid */}
          {analyses.length > 0 && (
            <section className="flex-shrink-0">
              <h2 className="text-sm font-semibold mb-2">Analysis Results</h2>
              <AnalysisPanel analyses={analyses} />
            </section>
          )}
        </div>

        {/* Right Column - Reasoning Log */}
        {reasoningLog.length > 0 && (
          <div className="min-h-0 overflow-hidden">
            <ReasoningLog entries={reasoningLog} maxHeight={undefined} />
          </div>
        )}
      </div>
    </div>
  );
}
