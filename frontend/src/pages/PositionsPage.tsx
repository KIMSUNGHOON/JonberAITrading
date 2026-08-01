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
import { PnlSummaryStrip } from '@/components/terminal/panels/PnlSummaryStrip';

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
              {/* 기간 손익 요약 — 계좌·보유 카드 위에 전폭으로 얹는다. 미실현손익은
                  아래 KiwoomPositionPanel의 "총 손익"이 이미 보여주므로 여기선 빼고
                  일/주/월/누적만 그린다(같은 숫자를 한 화면에 두 번 띄우지 않는다). */}
              <PnlSummaryStrip />
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <KiwoomAccountBalance />
                <KiwoomPositionPanel />
              </div>
              <div className="mt-3">
                <KiwoomOpenOrders />
              </div>
            </section>
          )}

          {/* Empty state */}
          {!upbitApiConfigured && !kiwoomApiConfigured && (
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
