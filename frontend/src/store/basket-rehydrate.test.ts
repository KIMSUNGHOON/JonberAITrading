/**
 * Persist-safety for basket items whose market no longer exists.
 *
 * R2 (86f19bd..570f5e1, commit 9453e1f): the US 'stock' market was removed,
 * but the basket persists wholesale in localStorage — a pre-removal item
 * (marketType 'stock') would survive rehydration, misroute its Analyze
 * button to the coin endpoint, and poison activeMarket with an out-of-union
 * value.
 *
 * upbit-removal task 1 fix round 2 (coordinator review, 2026-08-01): the
 * SAME class of bug, now for 'coin'. The Scratchpad's COIN <select> option
 * was cut in round 1, but a basket item added BEFORE the freeze still
 * carries marketType 'coin' in localStorage. Unfiltered, it would survive
 * rehydration and its "분석▶"/price-poll would reach the now-unmounted
 * /coin/analysis/start and /coin/tickers routes (real user state, not
 * hypothetical — the dropdown only just stopped offering it).
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

describe('basket rehydration — dropped markets (US stock, then coin)', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('drops persisted basket items whose marketType no longer exists (stock, coin)', async () => {
    seedStorage({
      version: 1,
      state: {
        basket: {
          items: [
            baskItem('stock', 'AAPL'), // pre-R2 US item
            baskItem('kiwoom', '005930'),
            baskItem('coin', 'KRW-BTC'), // pre-freeze coin item
          ],
          maxItems: 10,
          isUpdating: false,
        },
      },
    });

    const { useStore } = await import('@/store');
    const items = useStore.getState().basket.items;

    expect(items.map((i) => i.ticker)).toEqual(['005930']);
    expect(items.every((i) => i.marketType === 'kiwoom')).toBe(true);
  });

  // 코인 동결(freeze) fix round 2: 위 테스트와 별개로, coin 단독 케이스를 명시적으로
  // 고정한다 — 이게 지금 살아있는 유일한 실사용 시나리오다("코인 감시는 제외"인
  // 배포 이력상 stock 잔존 항목은 사실상 이론적이지만, coin은 라운드 1까지 select에서
  // 실제로 고를 수 있었으므로 사용자 localStorage에 남아있을 개연성이 훨씬 높다).
  it('coin 항목만 있는 basket도 rehydrate 시 전부 걸러진다', async () => {
    seedStorage({
      version: 1,
      state: {
        basket: {
          items: [baskItem('coin', 'KRW-BTC'), baskItem('coin', 'KRW-ETH')],
          maxItems: 10,
          isUpdating: false,
        },
      },
    });

    const { useStore } = await import('@/store');
    expect(useStore.getState().basket.items).toEqual([]);
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
