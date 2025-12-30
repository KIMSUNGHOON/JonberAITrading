/**
 * DashboardSummary Component
 *
 * Combines MarketSummaryWidget, TradingStatusCard, PopularStocksWidget,
 * and RecentAnalysisWidget for a comprehensive dashboard overview.
 *
 * Replaces WelcomePanel after first visit.
 */

import { MarketSummaryWidget } from './MarketSummaryWidget';
import { TradingStatusCard } from './TradingStatusCard';
import { PopularStocksWidget } from './PopularStocksWidget';
import { RecentAnalysisWidget } from './RecentAnalysisWidget';

export function DashboardSummary() {
  return (
    <div className="space-y-4">
      {/* Top Row - Market Summary + Trading Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Market Summary - Account overview */}
        <MarketSummaryWidget />

        {/* Auto Trading Status */}
        <TradingStatusCard />
      </div>

      {/* Popular Stocks - Flightboard Style */}
      <PopularStocksWidget />

      {/* Recent Analysis Results */}
      <RecentAnalysisWidget />
    </div>
  );
}
