/**
 * PositionsPage Component
 *
 * Full-page view of positions across all markets.
 * - Coin positions
 * - Kiwoom positions
 * - Stock positions
 */

import { ArrowLeft } from 'lucide-react';
import { useStore } from '@/store';
import { CoinPositionPanel } from '@/components/coin/CoinPositionPanel';
import { CoinAccountBalance } from '@/components/coin/CoinAccountBalance';
import { CoinOpenOrders } from '@/components/coin/CoinOpenOrders';
import { KiwoomPositionPanel, KiwoomAccountBalance, KiwoomOpenOrders } from '@/components/kiwoom';

interface PositionsPageProps {
  onBack?: () => void;
}

export function PositionsPage({ onBack }: PositionsPageProps) {
  const setCurrentView = useStore((state) => state.setCurrentView);
  const activeMarket = useStore((state) => state.activeMarket);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);

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
          <h1 className="text-xl font-semibold">Positions</h1>
          <p className="text-sm text-gray-500">View your holdings across all markets</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Coin Positions */}
          {(activeMarket === 'coin' || upbitApiConfigured) && (
            <section>
              <h2 className="text-lg font-semibold mb-3">Crypto Positions</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <CoinAccountBalance />
                <CoinPositionPanel />
              </div>
              <div className="mt-4">
                <CoinOpenOrders />
              </div>
            </section>
          )}

          {/* Kiwoom Positions */}
          {(activeMarket === 'kiwoom' || kiwoomApiConfigured) && (
            <section>
              <h2 className="text-lg font-semibold mb-3">Korean Stock Positions</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <KiwoomAccountBalance />
                <KiwoomPositionPanel />
              </div>
              <div className="mt-4">
                <KiwoomOpenOrders />
              </div>
            </section>
          )}

          {/* Placeholder for US Stock positions */}
          {activeMarket === 'stock' && (
            <section>
              <h2 className="text-lg font-semibold mb-3">US Stock Positions</h2>
              <div className="card p-8 text-center">
                <p className="text-gray-500">US Stock position tracking coming soon</p>
              </div>
            </section>
          )}

          {/* Empty state */}
          {!upbitApiConfigured && !kiwoomApiConfigured && activeMarket !== 'stock' && (
            <div className="card p-8 text-center">
              <p className="text-gray-500">
                Configure your API keys in Settings to view positions
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
