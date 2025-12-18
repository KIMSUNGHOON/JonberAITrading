/**
 * Main Content Component
 *
 * Dashboard area with chart and analysis panels.
 */

import { useStore, selectSession, selectAnalysis, selectProposal } from '@/store';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { AnalysisPanel } from '@/components/analysis/AnalysisPanel';
import { ReasoningLog } from '@/components/analysis/ReasoningLog';
import { ProposalCard } from '@/components/approval/ProposalCard';
import { PositionCard } from '@/components/position/PositionCard';
import { WelcomePanel } from '@/components/analysis/WelcomePanel';

export function MainContent() {
  const { sessionId, ticker, status } = useStore(selectSession);
  const { analyses, reasoningLog } = useStore(selectAnalysis);
  const { proposal, awaitingApproval } = useStore(selectProposal);
  const activePosition = useStore((state) => state.activePosition);
  const showChartPanel = useStore((state) => state.showChartPanel);

  // Show welcome panel when idle
  if (status === 'idle' && !sessionId) {
    return <WelcomePanel />;
  }

  return (
    <div className="p-4 md:p-6 space-y-6">
      {/* Chart Section */}
      {showChartPanel && ticker && (
        <section>
          <ChartPanel ticker={ticker} />
        </section>
      )}

      {/* Active Position */}
      {activePosition && (
        <section>
          <PositionCard position={activePosition} />
        </section>
      )}

      {/* Trade Proposal */}
      {proposal && awaitingApproval && (
        <section>
          <ProposalCard proposal={proposal} />
        </section>
      )}

      {/* Analysis Grid */}
      {analyses.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Analysis Results</h2>
          <AnalysisPanel analyses={analyses} />
        </section>
      )}

      {/* Reasoning Log */}
      {reasoningLog.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Agent Reasoning</h2>
          <ReasoningLog entries={reasoningLog} />
        </section>
      )}
    </div>
  );
}
