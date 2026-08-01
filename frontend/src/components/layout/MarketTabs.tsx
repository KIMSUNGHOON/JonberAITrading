/**
 * MarketTabs Component
 *
 * 유일한 마켓: Stock (KR · Kiwoom). The US stock stack is FROZEN (no broker,
 * sim-only) — the Stock tab routes straight to the Korean market.
 *
 * Crypto 탭은 코인 동결 fix round 1에서 제거됐고(사이드바/모바일 내비를 통해
 * `setActiveMarket('coin')`을 호출할 수 있는 배선이었다), 코인 스택 자체도
 * 이후 완전히 제거됐다(2026-08-01, `MarketType`은 `'kiwoom'` 단일 유니온).
 */

import { TrendingUp, Lock } from 'lucide-react';
import { useStore } from '@/store';

export function MarketTabs() {
  const activeMarket = useStore((state) => state.activeMarket);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);

  // Determine effective market for display
  const isStock = activeMarket === 'kiwoom';

  const handleStockClick = () => {
    if (!kiwoomApiConfigured) {
      setShowSettingsModal(true);
      return;
    }
    setActiveMarket('kiwoom');
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
      </div>

    </div>
  );
}