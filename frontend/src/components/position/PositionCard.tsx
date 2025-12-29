/**
 * Position Card Component
 *
 * Displays active trading position.
 */

import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Activity,
} from 'lucide-react';
import type { Position } from '@/types';
import type { MarketType } from '@/store';

// Helper to format currency based on market type
function formatCurrency(value: number, marketType: MarketType): string {
  if (marketType === 'kiwoom' || marketType === 'coin') {
    return `₩${value.toLocaleString('ko-KR')}`;
  }
  return `$${value.toFixed(2)}`;
}

interface PositionCardProps {
  position: Position;
  marketType?: MarketType;
}

export function PositionCard({ position, marketType = 'stock' }: PositionCardProps) {
  const {
    ticker,
    quantity,
    entry_price,
    current_price,
    pnl,
    pnl_percent,
  } = position;

  const isProfit = pnl >= 0;

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-600/20 flex items-center justify-center">
            <Activity className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h3 className="font-semibold flex items-center gap-2">
              Active Position
              <span className="live-indicator text-sm font-normal text-bull">
                Live
              </span>
            </h3>
            <p className="text-sm text-gray-400">{ticker}</p>
          </div>
        </div>

        {/* P&L Badge */}
        <div
          className={`flex items-center gap-1 px-3 py-1.5 rounded-lg ${
            isProfit ? 'bg-bull/20 text-bull' : 'bg-bear/20 text-bear'
          }`}
        >
          {isProfit ? (
            <TrendingUp className="w-4 h-4" />
          ) : (
            <TrendingDown className="w-4 h-4" />
          )}
          <span className="font-semibold">
            {isProfit ? '+' : ''}
            {pnl_percent.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Details Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <DetailBox
          label="Quantity"
          value={quantity.toString()}
          icon={<DollarSign className="w-4 h-4" />}
        />
        <DetailBox
          label="Entry Price"
          value={formatCurrency(entry_price, marketType)}
          icon={<TrendingUp className="w-4 h-4" />}
        />
        <DetailBox
          label="Current Price"
          value={formatCurrency(current_price, marketType)}
          icon={<Activity className="w-4 h-4" />}
          valueColor={current_price >= entry_price ? 'text-bull' : 'text-bear'}
        />
        <DetailBox
          label="P&L"
          value={`${isProfit ? '+' : ''}${formatCurrency(Math.abs(pnl), marketType)}`}
          icon={isProfit ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          valueColor={isProfit ? 'text-bull' : 'text-bear'}
        />
      </div>
    </div>
  );
}

interface DetailBoxProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  valueColor?: string;
}

function DetailBox({ label, value, icon, valueColor = 'text-white' }: DetailBoxProps) {
  return (
    <div className="bg-surface rounded-lg p-3">
      <div className="flex items-center gap-1 text-gray-400 text-xs mb-1">
        {icon}
        {label}
      </div>
      <div className={`font-semibold ${valueColor}`}>{value}</div>
    </div>
  );
}
