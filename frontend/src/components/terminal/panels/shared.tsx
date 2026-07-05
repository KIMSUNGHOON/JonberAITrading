/**
 * Shared primitives for the terminal dashboard tiles.
 *
 * Every tile is dense, tabular, and honest: when a value has no backing store
 * field or endpoint it renders an em-dash (—), never a fabricated number.
 */
import type { MarketType } from '@/store';

/** Centered "no data yet" state used by every tile. Honest, never fabricated. */
export function Awaiting({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full py-6 text-[11px] text-dim text-center px-4">
      <span className="w-1.5 h-1.5 rounded-full bg-dim mr-2 flex-none" />
      {label}
    </div>
  );
}

/** Sticky table-header cell class (right-aligned numeric columns). */
export const TH =
  'sticky top-0 bg-card text-right font-semibold text-muted text-[10px] tracking-wide px-2.5 py-1.5 border-b border-hairline whitespace-nowrap';

/** Em-dash for any value the store/endpoint genuinely lacks. */
export const DASH = '—';

/** Integer with thousands separators; DASH when missing/non-finite. */
export function fmtInt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return Math.round(n).toLocaleString();
}

/** Signed percent, 2 decimals (e.g. +1.24%); DASH when missing. */
export function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

/**
 * Market-aware price. US ('stock') is USD; coin/kiwoom are KRW.
 * KRW prices under 100 keep up to 4 decimals (small-cap coins); otherwise
 * integer KRW. A 0 or missing price renders DASH (never a misleading 0.00).
 */
export function fmtPrice(n: number | null | undefined, market: MarketType): string {
  if (n == null || !Number.isFinite(n) || n === 0) return DASH;
  if (market === 'stock') {
    return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (n < 100) return `₩${n.toLocaleString('ko-KR', { maximumFractionDigits: 4 })}`;
  return `₩${Math.round(n).toLocaleString('ko-KR')}`;
}

/**
 * Compact KRW/USD for KV tiles (총자산/가용): 1.2억 / 340만 / $12.3k.
 * Keeps the dense tile readable without dropping magnitude. DASH when missing.
 */
export function fmtMoneyCompact(n: number | null | undefined, market: MarketType): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  if (market === 'stock') {
    if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
    return `$${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  }
  if (Math.abs(n) >= 100_000_000) return `₩${(n / 100_000_000).toFixed(2)}억`;
  if (Math.abs(n) >= 10_000) return `₩${(n / 10_000).toFixed(0)}만`;
  return `₩${Math.round(n).toLocaleString('ko-KR')}`;
}

/** Label for the active market (matches the status line / command bar). */
export function marketLabelOf(market: MarketType): string {
  return market === 'kiwoom' ? 'KRX' : market === 'coin' ? 'UPBIT' : 'US';
}
