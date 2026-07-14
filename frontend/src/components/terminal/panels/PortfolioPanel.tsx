/**
 * Portfolio KV tile — 총자산 / 평가손익 / 보유 / 가용 for the active market.
 *
 * No store slice backs account balances; data comes from REST per market:
 *   kiwoom → getKRStockAccount (총자산/가용/보유) + getOperations('kiwoom') (평가손익)
 *   coin   → getCoinAccounts (총자산/가용/보유) + getCoinPositions (평가손익)
 * Polls every 30s (Kiwoom is throttled through the 800ms request queue, so keep
 * the cadence gentle). The 4-cell grid keeps the exact honest empty-state.
 *
 * P2-4 M1: the KR 평가손익 figure is summed from `getOperations('kiwoom')`
 * holdings — the SAME per-holding `pnl` the Positions tile (PositionsPanel)
 * and the funnel's HoldingColumn already render, which P1 (commit 6e6bf3f)
 * wired net of round-trip KR cost (commission both legs + sell tax; see
 * `services/trading/fill_costs.py::effective_pnl`). Previously this tile
 * read `getKRStockAccount().total_profit_loss`, the broker's raw GROSS
 * evlu_pfls_amt — always off from the holdings panels by exactly the
 * round-trip cost. Sourcing both from the one `/operations` response is what
 * makes the dashboard's numbers reconcile (this codebase has fixed the same
 * "why don't these two numbers match" class of bug twice before: ddfebb6,
 * b283814). A failed/degraded ops fetch renders DASH here rather than
 * silently falling back to the gross figure, which would reintroduce the
 * divergence. Coin already sourced 평가손익 from `getCoinPositions()`
 * (`total_pnl`), which itself sums each position's `unrealized_pnl` — net of
 * projected coin fee since P1 (`calculate_position_pnl`) — so no coin-side
 * change was needed.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { useStore } from '@/store';
import { getKRStockAccount, getCoinAccounts, getCoinPositions, getOperations } from '@/api/client';
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
      try {
        if (activeMarket === 'kiwoom') {
          // ops fetch is best-effort (.catch(() => null)): a network failure
          // here must degrade 평가손익 to DASH, never fall back to
          // acct.total_profit_loss (gross) — that fallback is exactly the
          // divergence this fix closes. See file header for the full
          // rationale.
          const [acct, ops] = await Promise.all([
            getKRStockAccount(),
            getOperations('kiwoom').catch(() => null),
          ]);
          if (!alive) return;
          const opsHoldings = ops?.holding ?? null;
          let pnl: number | null = null;
          let pnlPct: number | null = null;
          if (opsHoldings) {
            pnl = opsHoldings.reduce((sum, h) => sum + h.pnl, 0);
            const costBasis = opsHoldings.reduce((sum, h) => sum + h.avg_price * h.quantity, 0);
            pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
          }
          setSummary({
            totalAssets: acct.cash.deposit + acct.total_eval_amount,
            pnl,
            pnlPct,
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
