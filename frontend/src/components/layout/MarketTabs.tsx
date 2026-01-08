/**
 * MarketTabs Component (Redesigned)
 *
 * Two main markets: Stock and Crypto
 * Stock has sub-regions: US and Korea
 */

import { TrendingUp, Bitcoin, Lock } from 'lucide-react';
import { useStore, type StockRegion } from '@/store';

export function MarketTabs() {
  const activeMarket = useStore((state) => state.activeMarket);
  const stockRegion = useStore((state) => state.stockRegion);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const setStockRegion = useStore((state) => state.setStockRegion);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);

  // Determine effective market for display
  const isStock = activeMarket === 'stock' || activeMarket === 'kiwoom';
  const isCoin = activeMarket === 'coin';

  const handleStockClick = () => {
    // When clicking Stock tab, use the current region to determine market
    if (stockRegion === 'kr') {
      if (!kiwoomApiConfigured) {
        setShowSettingsModal(true);
        return;
      }
      setActiveMarket('kiwoom');
    } else {
      setActiveMarket('stock');
    }
  };

  const handleCoinClick = () => {
    if (!upbitApiConfigured) {
      setShowSettingsModal(true);
      return;
    }
    setActiveMarket('coin');
  };

  const handleRegionChange = (region: StockRegion) => {
    setStockRegion(region);
    if (region === 'kr') {
      if (!kiwoomApiConfigured) {
        setShowSettingsModal(true);
        return;
      }
      setActiveMarket('kiwoom');
    } else {
      setActiveMarket('stock');
    }
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

      {/* Stock Region Selector (only shown when Stock is active) */}
      {isStock && (
        <div className="flex gap-1 p-0.5 bg-surface rounded-lg w-full">
          {/* US Stock */}
          <button
            onClick={() => handleRegionChange('us')}
            className={`
              flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md
              text-xs font-medium transition-all duration-200 min-w-0
              ${stockRegion === 'us'
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-light border border-transparent'
              }
            `}
          >
            <span className="text-sm flex-shrink-0">🇺🇸</span>
            <span className="truncate">US</span>
          </button>

          {/* Korea Stock */}
          <button
            onClick={() => handleRegionChange('kr')}
            className={`
              flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md
              text-xs font-medium transition-all duration-200 min-w-0
              ${stockRegion === 'kr'
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-light border border-transparent'
              }
            `}
          >
            <span className="text-sm flex-shrink-0">🇰🇷</span>
            <span className="truncate">Korea</span>
            {!kiwoomApiConfigured && (
              <Lock size={10} className="text-amber-400 opacity-70 flex-shrink-0" />
            )}
          </button>
        </div>
      )}
    </div>
  );
}