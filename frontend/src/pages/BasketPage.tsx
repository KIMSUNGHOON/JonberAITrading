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
import { useStore } from '@/store';
import { BasketWidget } from '@/components/basket/BasketWidget';

interface BasketPageProps {
  onBack?: () => void;
}

export function BasketPage({ onBack }: BasketPageProps) {
  const setCurrentView = useStore((state) => state.setCurrentView);

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      setCurrentView('dashboard');
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface-dark">
        <button
          onClick={handleBack}
          className="p-2 rounded-lg hover:bg-surface transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-5 h-5 text-gray-400" />
        </button>
        <div>
          <h1 className="text-xl font-semibold">My Basket</h1>
          <p className="text-sm text-gray-500">Search and manage your watchlist</p>
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
