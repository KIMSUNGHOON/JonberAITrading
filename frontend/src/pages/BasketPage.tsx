/**
 * BasketPage Component
 *
 * Full-page view of the basket/watchlist with expanded functionality.
 * - Full search capability
 * - Expanded item list
 * - Bulk actions
 * - Analysis queue status
 */

import { ArrowLeft } from 'lucide-react';
import { useGoTo } from '@/hooks/useNav';
import { BasketWidget } from '@/components/basket/BasketWidget';

interface BasketPageProps {
  onBack?: () => void;
}

export function BasketPage({ onBack }: BasketPageProps) {
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
          <h1 className="text-xl font-semibold">My Basket</h1>
          <p className="text-sm text-dim">Search and manage your watchlist</p>
        </div>
      </div>

      {/* Content - Expanded BasketWidget */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto">
          <BasketWidget expanded={true} />
        </div>
      </div>
    </div>
  );
}
