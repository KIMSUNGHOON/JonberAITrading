/**
 * Main Content Component
 *
 * Handles routing between different views:
 * - Dashboard: Comprehensive overview with all widgets
 * - Analysis: Detailed workflow view for analyzing stocks
 * - Basket, History, Positions, Charts pages
 */

import { useState, useEffect } from 'react';
import { useStore, selectActivePosition } from '@/store';
import { AnalysisQueueWidget } from '@/components/analysis/AnalysisQueueWidget';
import { ReasoningSlidePanel } from '@/components/analysis/ReasoningSlidePanel';
import { PositionCard } from '@/components/position/PositionCard';
import { WelcomePanel } from '@/components/analysis/WelcomePanel';
import { CoinMarketDashboard, DashboardSummary } from '@/components/dashboard';
import { CoinAccountBalance } from '@/components/coin/CoinAccountBalance';
import { CoinPositionPanel } from '@/components/coin/CoinPositionPanel';
import { CoinOpenOrders } from '@/components/coin/CoinOpenOrders';
import { CoinTradeHistory } from '@/components/coin/CoinTradeHistory';
import {
  KiwoomTickerInput,
  KiwoomPositionPanel,
  KiwoomAccountBalance,
  KiwoomOpenOrders,
} from '@/components/kiwoom';
import { BasketWidget } from '@/components/basket';
import { BasketPage } from '@/pages/BasketPage';
import { PositionsPage } from '@/pages/PositionsPage';
import { ChartsPage } from '@/pages/ChartsPage';
import { TradesPage } from '@/pages/TradesPage';
import { AnalysisPage } from '@/pages/AnalysisPage';
import { WorkflowPage } from '@/pages/WorkflowPage';
import { AnalysisDetailPage } from '@/pages/AnalysisDetailPage';
import { ScannerResultsPage } from '@/pages/ScannerResultsPage';
import { TradingDashboard } from '@/components/trading';

export function MainContent() {
  const [showReasoningPanel, setShowReasoningPanel] = useState(false);

  const activePosition = useStore(selectActivePosition);
  const activeMarket = useStore((state) => state.activeMarket);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const currentView = useStore((state) => state.currentView);

  // First visit tracking - show WelcomePanel on first visit, DashboardSummary on subsequent visits
  const hasVisited = useStore((state) => state.hasVisited);
  const setHasVisited = useStore((state) => state.setHasVisited);

  // Set hasVisited to true after first render (immediate transition)
  useEffect(() => {
    if (!hasVisited) {
      setHasVisited(true);
    }
  }, [hasVisited, setHasVisited]);

  const handleViewReasoningDetails = () => {
    setShowReasoningPanel(true);
  };

  // ============================================
  // Page Views (basket, history, positions, charts)
  // ============================================
  if (currentView === 'basket') {
    return <BasketPage />;
  }

  // History is now merged into Analysis page
  if (currentView === 'history') {
    return <AnalysisPage />;
  }

  if (currentView === 'positions') {
    return <PositionsPage />;
  }

  if (currentView === 'charts') {
    return <ChartsPage />;
  }

  if (currentView === 'trades') {
    return <TradesPage />;
  }

  if (currentView === 'trading') {
    return <TradingDashboard />;
  }

  if (currentView === 'scanner') {
    return <ScannerResultsPage />;
  }

  // ============================================
  // Analysis Pages - New unified analysis views
  // ============================================

  // Analysis List Page - Shows running and completed analyses
  if (currentView === 'analysis') {
    return <AnalysisPage />;
  }

  // Workflow Page - Shows detailed progress for a running analysis
  if (currentView === 'workflow') {
    return <WorkflowPage />;
  }

  // Analysis Detail Page - Shows report for completed analysis
  if (currentView === 'analysis-detail') {
    return <AnalysisDetailPage />;
  }

  // ============================================
  // Dashboard View - Comprehensive overview
  // ============================================

  // Coin market dashboard
  if (activeMarket === 'coin') {
    return (
      <div className="p-3 md:p-4 space-y-4">
        {/* Show WelcomePanel on first visit, DashboardSummary on subsequent visits */}
        {hasVisited ? <DashboardSummary /> : <WelcomePanel />}

        {/* Main Grid - Trading Dashboard + Basket/Queue */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Left Column - Account & Positions (2/3 width on xl) */}
          <div className="xl:col-span-2 space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <CoinAccountBalance />
              <CoinPositionPanel />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <CoinOpenOrders />
              <CoinTradeHistory pageSize={5} />
            </div>
          </div>

          {/* Right Column - Basket & Queue (1/3 width on xl) */}
          <div className="space-y-4">
            <BasketWidget />
            <AnalysisQueueWidget onViewDetails={handleViewReasoningDetails} />
          </div>
        </div>

        <CoinMarketDashboard />

        {/* Reasoning Slide Panel */}
        <ReasoningSlidePanel
          isOpen={showReasoningPanel}
          onClose={() => setShowReasoningPanel(false)}
        />
      </div>
    );
  }

  // Kiwoom market dashboard
  if (activeMarket === 'kiwoom') {
    return (
      <div className="p-3 md:p-4 space-y-4">
        {/* Show WelcomePanel on first visit, DashboardSummary on subsequent visits */}
        {hasVisited ? <DashboardSummary /> : <WelcomePanel />}

        {/* Main Grid - Trading Dashboard + Basket/Queue */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Left Column - Account & Positions (2/3 width on xl) */}
          <div className="xl:col-span-2 space-y-4">
            {kiwoomApiConfigured && (
              <>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <KiwoomAccountBalance />
                  <KiwoomPositionPanel />
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="bg-surface-light rounded-xl p-4 border border-border">
                    <h3 className="text-sm font-medium text-gray-300 mb-3">종목 분석 시작</h3>
                    <KiwoomTickerInput />
                  </div>
                  <KiwoomOpenOrders />
                </div>
              </>
            )}
          </div>

          {/* Right Column - Basket & Queue (1/3 width on xl) */}
          <div className="space-y-4">
            <BasketWidget />
            <AnalysisQueueWidget onViewDetails={handleViewReasoningDetails} />
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

  // Default - stock market dashboard
  return (
    <div className="p-3 md:p-4 space-y-4">
      {/* Show WelcomePanel on first visit, DashboardSummary on subsequent visits */}
      {hasVisited ? <DashboardSummary /> : <WelcomePanel />}

      {/* Main Grid - Trading Dashboard + Basket/Queue */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Left Column - Main Content (2/3 width on xl) */}
        <div className="xl:col-span-2 space-y-4">
          {/* Active Position */}
          {activePosition && (
            <section>
              <PositionCard position={activePosition} />
            </section>
          )}
        </div>

        {/* Right Column - Basket & Queue (1/3 width on xl) */}
        <div className="space-y-4">
          <BasketWidget />
          <AnalysisQueueWidget onViewDetails={handleViewReasoningDetails} />
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
