/**
 * DashboardSummary Component
 *
 * Combines MarketSummaryWidget and RecentAnalysisWidget
 * to provide a comprehensive dashboard overview.
 *
 * Replaces WelcomePanel after first visit.
 */

import { MarketSummaryWidget } from './MarketSummaryWidget';
import { RecentAnalysisWidget } from './RecentAnalysisWidget';

export function DashboardSummary() {
  return (
    <div className="space-y-4">
      {/* Market Summary - Account overview */}
      <MarketSummaryWidget />

      {/* Recent Analysis Results */}
      <RecentAnalysisWidget />
    </div>
  );
}
