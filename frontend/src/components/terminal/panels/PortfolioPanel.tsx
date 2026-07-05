/**
 * Portfolio KV tile — 총자산 / 평가손익 / 보유 / 가용 for the active market.
 *
 * No store slice backs account balances; data comes from REST per market:
 *   kiwoom → getKRStockAccount
 *   coin   → getCoinAccounts (+ getCoinPositions for P&L, which accounts lack)
 *   stock  → no endpoint → honest '—'
 * Polls every 30s (Kiwoom is throttled through the 800ms request queue, so keep
 * the cadence gentle). The 4-cell grid keeps the exact honest empty-state.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { useStore } from '@/store';
import { getKRStockAccount, getCoinAccounts, getCoinPositions } from '@/api/client';
import { pnlColor } from '@/utils/pnl';
import { DASH, fmtPct, fmtMoneyCompact } from './shared';

interface Summary {
  totalAssets: number | null;
  pnl: number | null;
  pnlPct: number | null;
  holdings: number | null;
  available: number | null;
}

const EMPTY: Summary = { totalAssets: null, pnl: null, pnlPct: null, holdings: null, available: null };

function usePortfolioSummary() {
  const activeMarket = useStore((s) => s.activeMarket);
  const [summary, setSummary] = useState<Summary>(EMPTY);

  useEffect(() => {
    let alive = true;

    async function run() {
      // US has no account endpoint — leave the honest '—' KVs.
      if (activeMarket === 'stock') {
        setSummary(EMPTY);
        return;
      }
      try {
        if (activeMarket === 'kiwoom') {
          const acct = await getKRStockAccount();
          if (!alive) return;
          setSummary({
            totalAssets: acct.cash.deposit + acct.total_eval_amount,
            pnl: acct.total_profit_loss,
            pnlPct: acct.total_profit_loss_rate,
            holdings: acct.holdings.length,
            available: acct.cash.orderable_amount,
          });
        } else {
          // Coin: accounts give assets/holdings/cash; positions give P&L.
          const [acct, pos] = await Promise.all([
            getCoinAccounts(),
            getCoinPositions().catch(() => null),
          ]);
          if (!alive) return;
          const krw = acct.accounts.find((a) => a.currency === 'KRW');
          const coinHoldings = acct.accounts.filter((a) => a.currency !== 'KRW' && a.balance > 0);
          setSummary({
            totalAssets: acct.total_krw_value,
            pnl: pos ? pos.total_pnl : null,
            pnlPct: pos ? pos.total_pnl_pct : null,
            holdings: coinHoldings.length,
            available: krw ? krw.balance : null,
          });
        }
      } catch {
        if (!alive) return;
        setSummary(EMPTY);
      }
    }

    run();
    const id = setInterval(run, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [activeMarket]);

  return { activeMarket, summary };
}

export function PortfolioPanel() {
  const { activeMarket, summary } = usePortfolioSummary();

  const totalAssets = fmtMoneyCompact(summary.totalAssets, activeMarket);
  const available = fmtMoneyCompact(summary.available, activeMarket);
  const holdings = summary.holdings != null ? String(summary.holdings) : '0';
  const pnlValue = fmtMoneyCompact(summary.pnl, activeMarket);
  const pnlPct = summary.pnlPct != null ? fmtPct(summary.pnlPct) : '';

  const cells: { k: string; v: ReactNode }[] = [
    { k: '총 자산', v: totalAssets },
    {
      k: '평가손익',
      v:
        summary.pnl != null ? (
          <span className={pnlColor(summary.pnl)}>
            {pnlValue}
            {pnlPct && <span className="text-[10px] ml-1">{pnlPct}</span>}
          </span>
        ) : (
          DASH
        ),
    },
    { k: '보유', v: holdings },
    { k: '가용', v: available },
  ];

  return (
    <div className="grid grid-cols-4 tabular-nums h-full">
      {cells.map((c) => (
        <div key={c.k} className="px-2.5 py-2 border-r border-hairline last:border-r-0">
          <div className="text-[10px] uppercase tracking-wide text-muted">{c.k}</div>
          <div className="text-[14px] font-bold mt-0.5 truncate">{c.v}</div>
        </div>
      ))}
    </div>
  );
}
