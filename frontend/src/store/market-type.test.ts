import { describe, expect, it } from 'vitest';
import { useStore } from '@/store';

/**
 * Recursively collects every own-enumerable key matching `pattern` anywhere
 * in `value` — not just at the top level. A shallow `Object.keys()` scan
 * would pass even with a nested coin slice intact (e.g. a future
 * `tradingModes: { kiwoom, coin }` regression), since nothing under a
 * top-level key would ever be inspected. Arrays are walked by element
 * (their own numeric-index keys are not pattern-tested); a `seen` set
 * guards against cycles.
 */
function collectMatchingKeys(
  value: unknown,
  pattern: RegExp,
  path: string[] = [],
  seen: Set<object> = new Set(),
): string[] {
  if (value === null || typeof value !== 'object') return [];
  if (seen.has(value as object)) return [];
  seen.add(value as object);

  const isArray = Array.isArray(value);
  const entries: [string, unknown][] = isArray
    ? (value as unknown[]).map((v, i) => [String(i), v])
    : Object.entries(value as Record<string, unknown>);

  const hits: string[] = [];
  for (const [key, child] of entries) {
    if (!isArray && pattern.test(key)) {
      hits.push([...path, key].join('.'));
    }
    hits.push(...collectMatchingKeys(child, pattern, [...path, key], seen));
  }
  return hits;
}

describe('MarketType 단일화', () => {
  it('activeMarket 기본값은 kiwoom이다', () => {
    expect(useStore.getState().activeMarket).toBe('kiwoom');
  });

  it('스토어에 코인 전용 상태·액션이 (중첩 포함) 남아 있지 않다', () => {
    const coinKeys = collectMatchingKeys(useStore.getState(), /coin/i);
    expect(coinKeys).toEqual([]);
  });
});
