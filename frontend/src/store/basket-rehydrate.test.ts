/**
 * R2 persist-safety: the US 'stock' market was removed, but the basket is
 * persisted wholesale in localStorage — items added BEFORE the removal can
 * carry marketType 'stock'. Rehydration must drop them: a surviving stale
 * item misroutes its Analyze button to the coin endpoint and poisons
 * activeMarket with an out-of-union value (review finding, 86f19bd..570f5e1).
 */

import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

const STORAGE_KEY = 'agentic-trading-storage';

/** test/setup.ts replaces localStorage with vi.fn() mocks — feed getItem. */
function seedStorage(payload: unknown) {
  (window.localStorage.getItem as Mock).mockImplementation((key: string) =>
    key === STORAGE_KEY ? JSON.stringify(payload) : null
  );
}

function baskItem(marketType: string, ticker: string) {
  return {
    id: `item-${ticker}`,
    marketType,
    ticker,
    displayName: ticker,
    price: 0,
    prevPrice: 0,
    changeRate: 0,
    change: 'EVEN',
    addedAt: new Date().toISOString(),
    lastUpdated: null,
  };
}

describe('basket rehydration after the US market removal', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('drops persisted basket items whose marketType no longer exists', async () => {
    seedStorage({
      version: 1,
      state: {
        basket: {
          items: [
            baskItem('stock', 'AAPL'), // pre-removal US item
            baskItem('kiwoom', '005930'),
            baskItem('coin', 'KRW-BTC'),
          ],
          maxItems: 10,
          isUpdating: false,
        },
      },
    });

    const { useStore } = await import('@/store');
    const items = useStore.getState().basket.items;

    expect(items.map((i) => i.ticker)).toEqual(['005930', 'KRW-BTC']);
    expect(items.every((i) => i.marketType === 'kiwoom' || i.marketType === 'coin')).toBe(true);
  });

  it('keeps a fully valid persisted basket intact', async () => {
    seedStorage({
      version: 1,
      state: {
        basket: {
          items: [baskItem('kiwoom', '005930')],
          maxItems: 10,
          isUpdating: false,
        },
      },
    });

    const { useStore } = await import('@/store');
    expect(useStore.getState().basket.items.map((i) => i.ticker)).toEqual(['005930']);
  });
});
