/**
 * ChartsPage Component
 *
 * Full-page view for chart analysis.
 * - TradingView-style charts
 * - Technical indicators
 * - Multi-timeframe analysis
 */

import { ArrowLeft, LineChart } from 'lucide-react';
import { useGoTo } from '@/hooks/useNav';

interface ChartsPageProps {
  onBack?: () => void;
}

export function ChartsPage({ onBack }: ChartsPageProps) {
  const goTo = useGoTo();

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      goTo('dashboard');
    }
  };

  return (
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-hairline bg-card">
        <button
          onClick={handleBack}
          className="p-2 rounded hover:bg-elevated transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-5 h-5 text-muted" />
        </button>
        <div>
          <h1 className="text-xl font-semibold">Charts</h1>
          <p className="text-sm text-dim">Technical analysis and charting tools</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto">
          {/* Placeholder for chart tools */}
          <div className="card p-12 text-center">
            <LineChart className="w-16 h-16 mx-auto mb-4 text-dim" />
            <h2 className="text-xl font-semibold mb-2">Advanced Charts</h2>
            <p className="text-dim max-w-md mx-auto">
              Full-featured charting with technical indicators, drawing tools, and
              multi-timeframe analysis coming soon.
            </p>
            <p className="text-sm text-dim mt-4">
              For now, charts are available within each analysis session.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
