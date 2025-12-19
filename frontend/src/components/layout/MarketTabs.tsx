/**
 * MarketTabs Component
 *
 * Tab navigation for switching between Stock and Coin markets.
 */

import { TrendingUp, Bitcoin } from 'lucide-react';
import { useStore, type MarketType } from '@/store';

interface TabProps {
  market: MarketType;
  icon: React.ReactNode;
  label: string;
  sublabel: string;
  isActive: boolean;
  onClick: () => void;
}

function Tab({ icon, label, sublabel, isActive, onClick }: TabProps) {
  return (
    <button
      onClick={onClick}
      className={`
        flex-1 flex items-center justify-center gap-2 py-3 px-2
        rounded-lg transition-all duration-200
        ${
          isActive
            ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
            : 'text-gray-400 hover:bg-surface hover:text-gray-200 border border-transparent'
        }
      `}
    >
      {icon}
      <div className="text-left">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs opacity-60">{sublabel}</div>
      </div>
    </button>
  );
}

export function MarketTabs() {
  const activeMarket = useStore((state) => state.activeMarket);
  const setActiveMarket = useStore((state) => state.setActiveMarket);

  return (
    <div className="flex gap-2 p-1 bg-surface rounded-lg">
      <Tab
        market="stock"
        icon={<TrendingUp className="w-5 h-5" />}
        label="Stock"
        sublabel="증권"
        isActive={activeMarket === 'stock'}
        onClick={() => setActiveMarket('stock')}
      />
      <Tab
        market="coin"
        icon={<Bitcoin className="w-5 h-5" />}
        label="Coin"
        sublabel="코인"
        isActive={activeMarket === 'coin'}
        onClick={() => setActiveMarket('coin')}
      />
    </div>
  );
}
