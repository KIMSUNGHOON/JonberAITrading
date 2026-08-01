import { describe, expect, it } from 'vitest';
import { useStore } from '@/store';

describe('MarketType 단일화', () => {
  it('activeMarket 기본값은 kiwoom이다', () => {
    expect(useStore.getState().activeMarket).toBe('kiwoom');
  });

  it('스토어에 코인 전용 액션이 남아 있지 않다', () => {
    const keys = Object.keys(useStore.getState());
    const coinKeys = keys.filter((k) => /coin/i.test(k));
    expect(coinKeys).toEqual([]);
  });
});
