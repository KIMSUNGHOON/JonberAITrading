/**
 * Main Content Component
 *
 * Dashboard area with chart and analysis panels.
 */

import { useShallow } from 'zustand/shallow';
import {
  useStore,
  selectSession,
  selectAnalysis,
  selectProposal,
  selectActivePosition,
} from '@/store';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { AnalysisPanel } from '@/components/analysis/AnalysisPanel';
import { ReasoningLog } from '@/components/analysis/ReasoningLog';
import { WorkflowProgress } from '@/components/analysis/WorkflowProgress';
import { ProposalCard } from '@/components/approval/ProposalCard';
import { PositionCard } from '@/components/position/PositionCard';
import { WelcomePanel } from '@/components/analysis/WelcomePanel';
import { CoinInfo } from '@/components/coin/CoinInfo';
import { CoinMarketDashboard } from '@/components/dashboard/CoinMarketDashboard';

export function MainContent() {
  const { sessionId, ticker, status } = useStore(useShallow(selectSession));
  const currentStage = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.currentStage : state.coin.currentStage
  );
  const { analyses, reasoningLog } = useStore(useShallow(selectAnalysis));
  const { proposal, awaitingApproval } = useStore(useShallow(selectProposal));
  const activePosition = useStore(selectActivePosition);
  const showChartPanel = useStore((state) => state.showChartPanel);
  const activeMarket = useStore((state) => state.activeMarket);

  // Show welcome panel when idle
  if (status === 'idle' && !sessionId) {
    // For coin market, show market dashboard alongside welcome
    if (activeMarket === 'coin') {
      return (
        <div className="p-3 md:p-4 space-y-4">
          <WelcomePanel />
          <CoinMarketDashboard />
        </div>
      );
    }
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

          {/* Coin Info - Show for coin markets */}
          {ticker && ticker.includes('-') && (
            <section className="flex-shrink-0">
              <CoinInfo market={ticker} />
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

          {/* Coin Market Overview - Show during analysis for coin markets */}
          {activeMarket === 'coin' && status === 'running' && (
            <section className="flex-shrink-0">
              <CoinMarketDashboard compact />
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
