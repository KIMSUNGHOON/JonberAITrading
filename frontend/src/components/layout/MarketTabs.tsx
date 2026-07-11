/**
 * MarketTabs Component
 *
 * Two markets: Stock (KR · Kiwoom) and Crypto (Upbit).
 * The US stock stack is FROZEN (no broker, sim-only) — the Stock tab routes
 * straight to the Korean market.
 */

import { TrendingUp, Bitcoin, Lock } from 'lucide-react';
import { useStore } from '@/store';

export function MarketTabs() {
  const activeMarket = useStore((state) => state.activeMarket);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);

  // Determine effective market for display
  const isStock = activeMarket === 'kiwoom';
  const isCoin = activeMarket === 'coin';

  const handleStockClick = () => {
    if (!kiwoomApiConfigured) {
      setShowSettingsModal(true);
      return;
    }
    setActiveMarket('kiwoom');
  };

  const handleCoinClick = () => {
    if (!upbitApiConfigured) {
      setShowSettingsModal(true);
      return;
    }
    setActiveMarket('coin');
  };

  return (
    <div className="space-y-2 w-full">
      {/* Main Market Tabs */}
      <div className="flex gap-1 p-1 bg-surface rounded-lg w-full">
        {/* Stock Tab */}
        <button
          onClick={handleStockClick}
          className={`
            flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-md
            text-sm font-medium transition-all duration-200 min-w-0
            ${isStock
              ? 'bg-blue-600 text-white shadow-md'
              : 'text-gray-400 hover:text-white hover:bg-surface-light'
            }
          `}
        >
          <TrendingUp size={16} className="flex-shrink-0" />
          <span className="truncate">Stock</span>
          {!kiwoomApiConfigured && (
            <Lock size={12} className="text-amber-300 opacity-70 flex-shrink-0" />
          )}
        </button>

        {/* Crypto Tab */}
        <button
          onClick={handleCoinClick}
          className={`
            flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-md
            text-sm font-medium transition-all duration-200 min-w-0
            ${isCoin
              ? 'bg-amber-600 text-white shadow-md'
              : 'text-gray-400 hover:text-white hover:bg-surface-light'
            }
          `}
        >
          <Bitcoin size={16} className="flex-shrink-0" />
          <span className="truncate">Crypto</span>
          {!upbitApiConfigured && (
            <Lock size={12} className="text-amber-300 opacity-70 flex-shrink-0" />
          )}
        </button>
      </div>

    </div>
  );
}