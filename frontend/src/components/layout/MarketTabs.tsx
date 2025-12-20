/**
 * MarketTabs Component
 *
 * Tab navigation for switching between Stock and Coin markets.
 * Coin tab requires Upbit API key configuration.
 */

import { TrendingUp, Bitcoin, Lock } from 'lucide-react';
import { useStore, type MarketType } from '@/store';

interface TabProps {
  market: MarketType;
  icon: React.ReactNode;
  label: string;
  sublabel: string;
  isActive: boolean;
  locked?: boolean;
  onClick: () => void;
}

function Tab({ icon, label, sublabel, isActive, locked, onClick }: TabProps) {
  return (
    <button
      onClick={onClick}
      className={`
        flex-1 flex items-center justify-center gap-2 py-3 px-2
        rounded-lg transition-all duration-200
        ${
          isActive
            ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
            : locked
              ? 'text-gray-500 hover:bg-surface border border-transparent cursor-pointer'
              : 'text-gray-400 hover:bg-surface hover:text-gray-200 border border-transparent'
        }
      `}
    >
      {icon}
      <div className="text-left">
        <div className="text-sm font-medium flex items-center gap-1">
          {label}
          {locked && <Lock className="w-3 h-3 text-yellow-500" />}
        </div>
        <div className="text-xs opacity-60">
          {locked ? 'API Key 필요' : sublabel}
        </div>
      </div>
    </button>
  );
}

export function MarketTabs() {
  const activeMarket = useStore((state) => state.activeMarket);
  const setActiveMarket = useStore((state) => state.setActiveMarket);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);

  const handleCoinTabClick = () => {
    if (!upbitApiConfigured) {
      // API KEY가 없으면 설정 모달 열기
      setShowSettingsModal(true);
    } else {
      setActiveMarket('coin');
    }
  };

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
        locked={!upbitApiConfigured}
        onClick={handleCoinTabClick}
      />
    </div>
  );
}
