/**
 * Watchlist tile — the client-side basket, filtered to the active market.
 *
 * Rows come from the persisted store basket (store.basket.items), so they show
 * on mount with no session. SYM/LAST/CHG% are store-backed; VOL/RSI/SIGNAL have
 * NO backing field and render an honest em-dash (—) rather than fabricated data.
 * For coin, prices are refreshed via getCoinTickers (batched, 30s) written back
 * into the store — the same path BasketWidget uses — so the two stay in sync.
 * US ('stock') has no live feed, so its rows show stored/entered values only.
 */
import { useEffect } from 'react';
import { useShallow } from 'zustand/shallow';
import { useStore, selectBasketItems, selectChartSymbol } from '@/store';
import { getCoinTickers } from '@/api/client';
import { changeColor } from '@/utils/pnl';
import { Awaiting, TH, DASH, fmtPct, fmtPrice, marketLabelOf } from './shared';

export function WatchlistPanel() {
  const activeMarket = useStore((s) => s.activeMarket);
  const allItems = useStore(useShallow(selectBasketItems));
  const upbitApiConfigured = useStore((s) => s.upbitApiConfigured);
  const updateBasketItemPrice = useStore((s) => s.updateBasketItemPrice);
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const chartSymbol = useStore(selectChartSymbol);

  const items = allItems.filter((i) => i.marketType === activeMarket);

  // Refresh coin prices into the store (batched, gated on Upbit config).
  useEffect(() => {
    if (activeMarket !== 'coin' || !upbitApiConfigured) return;
    const coinTickers = items.map((i) => i.ticker);
    if (coinTickers.length === 0) return;

    let alive = true;
    async function run() {
      try {
        const res = await getCoinTickers(coinTickers);
        if (!alive) return;
        res.tickers.forEach((t) => {
          updateBasketItemPrice(
            t.market,
            t.trade_price,
            t.change_rate * 100,
            t.change as 'RISE' | 'FALL' | 'EVEN',
          );
        });
      } catch {
        /* keep last known prices; do not fabricate */
      }
    }
    run();
    const id = setInterval(run, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // items identity changes each render; key on the ticker set + gates instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, upbitApiConfigured, items.map((i) => i.ticker).join(','), updateBasketItemPrice]);

  if (items.length === 0) {
    return <Awaiting label={`관심종목 없음 · ${marketLabelOf(activeMarket)} 종목을 바스켓에 추가`} />;
  }

  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>SYM · {marketLabelOf(activeMarket)}</th>
          <th className={TH}>LAST</th>
          <th className={TH}>CHG%</th>
          <th className={TH}>VOL</th>
          <th className={TH}>RSI</th>
          <th className={TH}>SIGNAL</th>
        </tr>
      </thead>
      <tbody>
        {items.map((it) => (
          <tr
            key={it.id}
            onClick={() => setChartSymbol(it.ticker)}
            title="차트에 표시"
            className={`border-b border-hairline/60 cursor-pointer hover:bg-elevated/40 ${
              chartSymbol === it.ticker ? 'bg-elevated/60' : ''
            }`}
          >
            <td className="text-left px-2.5 py-1">
              <span className="font-semibold">{it.displayName || it.ticker}</span>
              {it.displayName && it.displayName !== it.ticker && (
                <span className="text-dim text-[10px] ml-1">{it.ticker}</span>
              )}
            </td>
            <td className="text-right px-2.5 py-1">{fmtPrice(it.price, activeMarket)}</td>
            <td className={`text-right px-2.5 py-1 ${changeColor(it.change)}`}>
              {it.price > 0 ? fmtPct(it.changeRate) : DASH}
            </td>
            {/* VOL / RSI / SIGNAL have no backing store field — honest em-dash. */}
            <td className="text-right px-2.5 py-1 text-dim">{DASH}</td>
            <td className="text-right px-2.5 py-1 text-dim">{DASH}</td>
            <td className="text-right px-2.5 py-1 text-dim">{DASH}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
