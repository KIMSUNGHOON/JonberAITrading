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
import { useGoTo } from '@/hooks/useNav';
import { CoinPositionPanel } from '@/components/coin/CoinPositionPanel';
import { CoinAccountBalance } from '@/components/coin/CoinAccountBalance';
import { CoinOpenOrders } from '@/components/coin/CoinOpenOrders';
import { KiwoomPositionPanel, KiwoomAccountBalance, KiwoomOpenOrders } from '@/components/kiwoom';

interface PositionsPageProps {
  onBack?: () => void;
}

export function PositionsPage({ onBack }: PositionsPageProps) {
  const goTo = useGoTo();
  const activeMarket = useStore((state) => state.activeMarket);
  const kiwoomApiConfigured = useStore((state) => state.kiwoomApiConfigured);
  const upbitApiConfigured = useStore((state) => state.upbitApiConfigured);

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
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-hairline bg-card">
        <button
          onClick={handleBack}
          className="p-1.5 rounded hover:bg-elevated transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-4 h-4 text-muted" />
        </button>
        <div>
          <h1 className="text-sm font-semibold">Positions</h1>
          <p className="text-[11px] text-dim">View your holdings across all markets</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="max-w-6xl mx-auto space-y-4">
          {/* Coin Positions */}
          {(activeMarket === 'coin' || upbitApiConfigured) && (
            <section>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2">Crypto Positions</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <CoinAccountBalance />
                <CoinPositionPanel />
              </div>
              <div className="mt-3">
                <CoinOpenOrders />
              </div>
            </section>
          )}

          {/* Kiwoom Positions */}
          {(activeMarket === 'kiwoom' || kiwoomApiConfigured) && (
            <section>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2">Korean Stock Positions</h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <KiwoomAccountBalance />
                <KiwoomPositionPanel />
              </div>
              <div className="mt-3">
                <KiwoomOpenOrders />
              </div>
            </section>
          )}

          {/* Placeholder for US Stock positions */}
          {activeMarket === 'stock' && (
            <section>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2">US Stock Positions</h2>
              <div className="card p-5 text-center">
                <p className="text-dim text-sm">US Stock position tracking coming soon</p>
              </div>
            </section>
          )}

          {/* Empty state */}
          {!upbitApiConfigured && !kiwoomApiConfigured && activeMarket !== 'stock' && (
            <div className="card p-5 text-center">
              <p className="text-dim text-sm">
                Configure your API keys in Settings to view positions
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
