/**
 * Single source of truth for price-direction / P&L color.
 *
 * The app previously hardcoded two contradicting conventions (Korean red-up in
 * some panels, Western green-up in others) so the SAME profit showed opposite
 * colors — a misread hazard on a trading surface. Everything now routes through
 * here. Default is Western (green = up); pass 'korean' for the red-up convention.
 */
export type PnlConvention = 'western' | 'korean';

/** Tailwind text-color class for a signed value under the active convention. */
export function pnlColor(value: number, convention: PnlConvention = 'western'): string {
  if (value === 0) return 'text-muted';
  const isUp = value > 0;
  const green = convention === 'western' ? isUp : !isUp;
  return green ? 'text-up' : 'text-down';
}

/** Tailwind text-color class for a RISE/FALL direction string (tickers). */
export function changeColor(dir: string, convention: PnlConvention = 'western'): string {
  if (dir === 'RISE') return convention === 'western' ? 'text-up' : 'text-down';
  if (dir === 'FALL') return convention === 'western' ? 'text-down' : 'text-up';
  return 'text-muted';
}
