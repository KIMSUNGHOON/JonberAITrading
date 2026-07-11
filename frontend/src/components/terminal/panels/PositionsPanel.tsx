/**
 * Positions tile — live broker holdings for the active market.
 *
 * Data comes from REST (per-market), NOT the store: the store's activePosition
 * is a single analysis-derived object with no stop/take. Kiwoom + coin have
 * exact column matches. Polls every 10s, keyed on activeMarket so switching
 * the market tab re-fetches (the tile never remounts).
 */
import { useEffect, useState } from 'react';
import { useStore, selectChartSymbol } from '@/store';
import { getKRStockPositions, getCoinPositions } from '@/api/client';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, TH, DASH, fmtInt, fmtPct, fmtPrice } from './shared';

interface Row {
  sym: string;
  code: string; // chartable symbol: KR 6-digit code or coin KRW-XXX market
  qty: number;
  entry: number;
  cur: number;
  pnl: number;
  pnlPct: number;
  stop: number | null;
  take: number | null;
}

type FetchState = 'loading' | 'ready' | 'error';

function usePositions() {
  const activeMarket = useStore((s) => s.activeMarket);
  const [rows, setRows] = useState<Row[]>([]);
  const [state, setState] = useState<FetchState>('loading');
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    async function run(showLoading: boolean) {
      if (showLoading) setState('loading');
      setErr(null);
      try {
        if (activeMarket === 'kiwoom') {
          const res = await getKRStockPositions();
          if (!alive) return;
          setRows(
            res.positions.map((p) => ({
              sym: p.stk_nm || p.stk_cd,
              code: p.stk_cd,
              qty: p.quantity,
              entry: p.avg_entry_price,
              cur: p.current_price,
              pnl: p.unrealized_pnl,
              pnlPct: p.unrealized_pnl_pct,
              stop: p.stop_loss,
              take: p.take_profit,
            })),
          );
        } else {
          const res = await getCoinPositions();
          if (!alive) return;
          setRows(
            res.positions.map((p) => ({
              sym: p.currency || p.market,
              code: p.market,
              qty: p.quantity,
              entry: p.avg_entry_price,
              cur: p.current_price,
              pnl: p.unrealized_pnl,
              pnlPct: p.unrealized_pnl_pct,
              stop: p.stop_loss,
              take: p.take_profit,
            })),
          );
        }
        setState('ready');
      } catch (e) {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : '로드 실패');
        setState('error');
      }
    }

    run(true);
    const id = setInterval(() => run(false), 10_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [activeMarket]);

  return { activeMarket, rows, state, err };
}

export function PositionsPanel() {
  const { activeMarket, rows, state, err } = usePositions();
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const chartSymbol = useStore(selectChartSymbol);

  if (state === 'loading') return <Awaiting label="포지션 로드 중…" />;
  if (state === 'error') return <Awaiting label={`포지션 오류 · ${err ?? '연결 실패'}`} />;
  if (rows.length === 0) return <Awaiting label="보유 포지션 없음 · 체결 시 표시" />;

  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>SYM</th>
          <th className={TH}>QTY</th>
          <th className={TH}>ENTRY</th>
          <th className={TH}>CUR</th>
          <th className={TH}>P&amp;L</th>
          <th className={TH}>%</th>
          <th className={TH}>STOP</th>
          <th className={TH}>TAKE</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr
            key={`${r.code}-${i}`}
            onClick={() => setChartSymbol(r.code)}
            title="차트에 표시"
            className={`border-b border-hairline/60 cursor-pointer hover:bg-elevated/40 ${
              chartSymbol === r.code ? 'bg-elevated/60' : ''
            }`}
          >
            <td className="text-left px-2.5 py-1 font-semibold truncate max-w-[120px]">{r.sym}</td>
            <td className="text-right px-2.5 py-1">{fmtInt(r.qty)}</td>
            <td className="text-right px-2.5 py-1 text-muted">{fmtPrice(r.entry, activeMarket)}</td>
            <td className="text-right px-2.5 py-1">{fmtPrice(r.cur, activeMarket)}</td>
            <td className={`text-right px-2.5 py-1 ${pnlColor(r.pnl)}`}>{fmtInt(r.pnl)}</td>
            <td className={`text-right px-2.5 py-1 ${pnlColor(r.pnlPct)}`}>{fmtPct(r.pnlPct)}</td>
            <td className="text-right px-2.5 py-1 text-dim">
              {r.stop != null ? fmtPrice(r.stop, activeMarket) : DASH}
            </td>
            <td className="text-right px-2.5 py-1 text-dim">
              {r.take != null ? fmtPrice(r.take, activeMarket) : DASH}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
