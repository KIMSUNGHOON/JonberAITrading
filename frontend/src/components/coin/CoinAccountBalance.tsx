/**
 * CoinAccountBalance Component
 *
 * Displays account balances including KRW and coin holdings.
 */

import { useState, useEffect } from 'react';
import { Wallet, RefreshCw, AlertCircle } from 'lucide-react';
import { getCoinAccounts } from '@/api/client';
import type { CoinAccount } from '@/types';

interface CoinAccountBalanceProps {
  onRefresh?: () => void;
}

export function CoinAccountBalance({ onRefresh }: CoinAccountBalanceProps) {
  const [accounts, setAccounts] = useState<CoinAccount[]>([]);
  const [totalKrw, setTotalKrw] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAccounts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getCoinAccounts();
      setAccounts(response.accounts);
      setTotalKrw(response.total_krw_value);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load accounts');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, []);

  const handleRefresh = () => {
    fetchAccounts();
    onRefresh?.();
  };

  const formatKRW = (value: number) => {
    return value.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  };

  const formatCrypto = (value: number) => {
    if (value >= 1) return value.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
    if (value >= 0.0001) return value.toFixed(6);
    return value.toFixed(8);
  };

  // Separate KRW from other currencies
  const krwAccount = accounts.find((a) => a.currency === 'KRW');
  const coinAccounts = accounts.filter((a) => a.currency !== 'KRW' && (a.balance > 0 || a.locked > 0));

  if (isLoading) {
    return (
      <div className="card animate-pulse">
        <div className="h-24 bg-surface rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 text-red-400">
          <AlertCircle size={16} />
          <span className="text-sm">{error}</span>
        </div>
        <button
          onClick={handleRefresh}
          className="mt-2 text-sm text-primary hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet size={18} className="text-primary" />
          <h3 className="font-semibold">Account Balance</h3>
        </div>
        <button
          onClick={handleRefresh}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="Refresh"
        >
          <RefreshCw size={16} className="text-gray-400" />
        </button>
      </div>

      {/* KRW Balance */}
      {krwAccount && (
        <div className="p-3 bg-surface rounded-lg">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">KRW</span>
            <div className="text-right">
              <div className="font-semibold">
                {formatKRW(krwAccount.balance)} <span className="text-xs text-gray-500">KRW</span>
              </div>
              {krwAccount.locked > 0 && (
                <div className="text-xs text-gray-500">
                  Locked: {formatKRW(krwAccount.locked)} KRW
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Coin Holdings */}
      {coinAccounts.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-gray-500 uppercase tracking-wide">Holdings</div>
          <div className="space-y-2 max-h-40 overflow-y-auto">
            {coinAccounts.map((account) => (
              <div
                key={account.currency}
                className="flex items-center justify-between py-2 px-3 bg-surface rounded-lg"
              >
                <div>
                  <div className="font-medium">{account.currency}</div>
                  {account.avg_buy_price > 0 && (
                    <div className="text-xs text-gray-500">
                      Avg: {formatKRW(account.avg_buy_price)} KRW
                    </div>
                  )}
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm">
                    {formatCrypto(account.balance)}
                  </div>
                  {account.locked > 0 && (
                    <div className="text-xs text-gray-500">
                      +{formatCrypto(account.locked)} locked
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Total Value */}
      {totalKrw !== null && totalKrw > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-400">Available KRW</span>
            <span className="font-semibold">{formatKRW(totalKrw)} KRW</span>
          </div>
        </div>
      )}

      {/* Empty State */}
      {accounts.length === 0 && (
        <div className="text-center py-4 text-gray-500 text-sm">
          No account data available
        </div>
      )}
    </div>
  );
}
