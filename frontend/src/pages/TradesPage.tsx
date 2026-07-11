/**
 * TradesPage Component
 *
 * Full-page view of executed trade history across all markets.
 * - Coin trade history
 * - Kiwoom trade history
 * - Filtering by market type
 */

import { ArrowLeft } from 'lucide-react';
import { useStore } from '@/store';
import { useGoTo } from '@/hooks/useNav';
import { CoinTradeHistory } from '@/components/coin/CoinTradeHistory';
import { KRStockTradeHistory } from '@/components/kiwoom';

interface TradesPageProps {
  onBack?: () => void;
}

export function TradesPage({ onBack }: TradesPageProps) {
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
      <div className="flex items-center gap-3 px-6 py-4 border-b border-hairline bg-card">
        <button
          onClick={handleBack}
          className="p-2 rounded hover:bg-elevated transition-colors"
          title="Back to Dashboard"
        >
          <ArrowLeft className="w-5 h-5 text-muted" />
        </button>
        <div>
          <h1 className="text-xl font-semibold">Trade History</h1>
          <p className="text-sm text-dim">View your executed trades across all markets</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Coin Trades */}
          {(activeMarket === 'coin' || upbitApiConfigured) && (
            <section>
              <h2 className="text-lg font-semibold mb-3">Crypto Trades</h2>
              <CoinTradeHistory pageSize={15} />
            </section>
          )}

          {/* Kiwoom Trades */}
          {(activeMarket === 'kiwoom' || kiwoomApiConfigured) && (
            <section>
              <h2 className="text-lg font-semibold mb-3">Korean Stock Trades</h2>
              <KRStockTradeHistory pageSize={15} />
            </section>
          )}

          {/* Empty state */}
          {!upbitApiConfigured && !kiwoomApiConfigured && (
            <div className="card p-8 text-center">
              <p className="text-dim">
                Configure your API keys in Settings to view trade history
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
