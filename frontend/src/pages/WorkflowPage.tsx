/**
 * WorkflowPage Component
 *
 * Shows detailed workflow progress for a running analysis.
 * - Real-time stage updates
 * - Chart panel
 * - Reasoning log
 * - Position panel
 */

import { useState } from 'react';
import { ArrowLeft, Activity } from 'lucide-react';
import { useShallow } from 'zustand/shallow';
import {
  useStore,
  selectSession,
  selectAnalysis,
  selectActivePosition,
} from '@/store';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { AnalysisPanel } from '@/components/analysis/AnalysisPanel';
import { AnalysisQueueWidget } from '@/components/analysis/AnalysisQueueWidget';
import { ReasoningSlidePanel } from '@/components/analysis/ReasoningSlidePanel';
import { WorkflowProgress } from '@/components/analysis/WorkflowProgress';
import { PositionCard } from '@/components/position/PositionCard';
import { CoinInfo } from '@/components/coin/CoinInfo';
import { CoinMarketDashboard } from '@/components/dashboard';
import { CoinPositionPanel } from '@/components/coin/CoinPositionPanel';
import { CoinOpenOrders } from '@/components/coin/CoinOpenOrders';
import {
  KiwoomPositionPanel,
  KiwoomOpenOrders,
} from '@/components/kiwoom';

interface WorkflowPageProps {
  onBack?: () => void;
}

export function WorkflowPage({ onBack }: WorkflowPageProps) {
  const [showReasoningPanel, setShowReasoningPanel] = useState(false);

  const { ticker, status } = useStore(useShallow(selectSession));
  const currentStage = useStore((state) => {
    switch (state.activeMarket) {
      case 'stock': return state.stock.currentStage;
      case 'coin': return state.coin.currentStage;
      case 'kiwoom': return state.kiwoom.currentStage;
    }
  });
  const { analyses } = useStore(useShallow(selectAnalysis));
  const activePosition = useStore(selectActivePosition);
  const showChartPanel = useStore((state) => state.showChartPanel);
  const activeMarket = useStore((state) => state.activeMarket);
  const setCurrentView = useStore((state) => state.setCurrentView);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('dashboard');
    }
  };

  const handleViewReasoningDetails = () => {
    setShowReasoningPanel(true);
  };

  // If no active session, show empty state
  if (!ticker || status === 'idle') {
    return (
      <div className="h-full flex flex-col bg-surface">
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
          <button
            onClick={handleBack}
            className="p-2 rounded-lg hover:bg-surface transition-colors"
            title="Back to Analysis"
          >
            <ArrowLeft className="w-5 h-5 text-gray-400" />
          </button>
          <div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <Activity className="w-6 h-6 text-blue-400" />
              Workflow
            </h1>
            <p className="text-sm text-gray-500">Analysis workflow progress</p>
          </div>
        </div>

        {/* Empty State */}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-gray-500">
            <Activity className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p className="text-lg">No active analysis</p>
            <p className="text-sm mt-2">
              Select a running analysis from the Analysis page
            </p>
            <button
              onClick={handleBack}
              className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm transition-colors"
            >
              Back to Analysis
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
        <button
          onClick={handleBack}
          className="p-2 rounded-lg hover:bg-surface transition-colors"
          title="Back to Analysis"
        >
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-400" />
            {ticker}
          </h1>
          <p className="text-sm text-gray-500">
            {status === 'running' && (currentStage || 'Analyzing...')}
            {status === 'awaiting_approval' && 'Awaiting Approval'}
            {status === 'completed' && 'Analysis Complete'}
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        {/* Workflow Progress */}
        <section className="mb-3">
          <WorkflowProgress
            currentStage={currentStage}
            status={status}
            ticker={ticker}
          />
        </section>

        {/* Main Grid Layout */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Left Column - Main Content (2/3 width on xl) */}
          <div className="xl:col-span-2 space-y-3">
            {/* Chart Section */}
            {showChartPanel && ticker && (
              <section>
                <ChartPanel ticker={ticker} />
              </section>
            )}

            {/* Coin Info - Show for coin markets */}
            {ticker && ticker.includes('-') && (
              <section>
                <CoinInfo market={ticker} />
              </section>
            )}

            {/* Active Position */}
            {activePosition && (
              <section>
                <PositionCard position={activePosition} marketType={activeMarket} />
              </section>
            )}

            {/* Trading Panels */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {/* Coin Trading Panels */}
              {activeMarket === 'coin' && (
                <>
                  <section>
                    <CoinPositionPanel />
                  </section>
                  <section>
                    <CoinOpenOrders />
                  </section>
                </>
              )}

              {/* Kiwoom Trading Panels */}
              {activeMarket === 'kiwoom' && (
                <>
                  <section>
                    <KiwoomPositionPanel />
                  </section>
                  <section>
                    <KiwoomOpenOrders />
                  </section>
                </>
              )}
            </div>

            {/* Coin Market Overview */}
            {activeMarket === 'coin' && status === 'running' && (
              <section>
                <CoinMarketDashboard compact />
              </section>
            )}

            {/* Analysis Grid */}
            {analyses.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold mb-2">Analysis Results</h2>
                <AnalysisPanel analyses={analyses} />
              </section>
            )}
          </div>

          {/* Right Column - Queue (1/3 width on xl) */}
          <div className="space-y-4">
            <AnalysisQueueWidget onViewDetails={handleViewReasoningDetails} />
          </div>
        </div>
      </div>

      {/* Reasoning Slide Panel */}
      <ReasoningSlidePanel
        isOpen={showReasoningPanel}
        onClose={() => setShowReasoningPanel(false)}
      />
    </div>
  );
}
