/**
 * WatchlistPanel had a KR (kiwoom) early-return that skipped price refresh
 * entirely — the poll effect only ever handled `activeMarket === 'coin'`, so
 * KR basket rows froze at whatever price they were added at. These tests
 * pin: KR items now refresh via getKRStockTicker (single-fetch per ticker,
 * since there is no batch REST endpoint yet — P1), the coin path is
 * untouched, and a single failing KR fetch doesn't blank/crash the panel.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const getCoinTickers = vi.fn();
const getKRStockTicker = vi.fn();
vi.mock('@/api/client', () => ({
  getCoinTickers: (...a: unknown[]) => getCoinTickers(...a),
  getKRStockTicker: (...a: unknown[]) => getKRStockTicker(...a),
}));

import { useStore } from '@/store';
import { WatchlistPanel } from './WatchlistPanel';

function krItem(overrides: Record<string, unknown> = {}) {
  return {
    id: `item-${overrides.ticker ?? '005930'}`,
    marketType: 'kiwoom' as const,
    ticker: '005930',
    displayName: '삼성전자',
    price: 0,
    prevPrice: 0,
    changeRate: 0,
    change: 'EVEN' as const,
    addedAt: new Date(),
    lastUpdated: null,
    isLoading: false,
    error: null,
    ...overrides,
  };
}

function coinItem(overrides: Record<string, unknown> = {}) {
  return {
    id: `item-${overrides.ticker ?? 'KRW-BTC'}`,
    marketType: 'coin' as const,
    ticker: 'KRW-BTC',
    displayName: '비트코인',
    price: 0,
    prevPrice: 0,
    changeRate: 0,
    change: 'EVEN' as const,
    addedAt: new Date(),
    lastUpdated: null,
    isLoading: false,
    error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    activeMarket: 'kiwoom',
    upbitApiConfigured: false,
    kiwoomApiConfigured: false,
    basket: { items: [], maxItems: 10, isUpdating: false },
  });
});

describe('WatchlistPanel — KR price refresh', () => {
  it('갱신 폴 이후 KR 종목의 가격/등락률이 getKRStockTicker로 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });
    getKRStockTicker.mockResolvedValue({
      stk_cd: '005930',
      stk_nm: '삼성전자',
      cur_prc: 71000,
      prdy_vrss: 500,
      prdy_ctrt: 1.23,
      opng_prc: 70500,
      high_prc: 71200,
      low_prc: 70200,
      trde_qty: 1000,
      trde_prica: 71000000,
      per: null,
      pbr: null,
      eps: null,
      bps: null,
      timestamp: '2026-07-13T00:00:00Z',
    });

    render(<WatchlistPanel />);

    await waitFor(() => expect(getKRStockTicker).toHaveBeenCalledWith('005930'));
    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    expect(screen.getByText('+1.23%')).toBeInTheDocument();
  });

  it('kiwoomApiConfigured가 false면 KR 폴을 시도하지 않는다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: false,
      basket: { items: [krItem()], maxItems: 10, isUpdating: false },
    });

    render(<WatchlistPanel />);

    await new Promise((r) => setTimeout(r, 0));
    expect(getKRStockTicker).not.toHaveBeenCalled();
  });

  it('일부 KR 종목의 조회가 실패해도 패널이 죽지 않고 나머지는 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'kiwoom',
      kiwoomApiConfigured: true,
      basket: {
        items: [krItem({ id: 'item-005930', ticker: '005930', displayName: '삼성전자' }),
                krItem({ id: 'item-000660', ticker: '000660', displayName: 'SK하이닉스' })],
        maxItems: 10,
        isUpdating: false,
      },
    });
    getKRStockTicker.mockImplementation((stk_cd: string) => {
      if (stk_cd === '000660') return Promise.reject(new Error('kiwoom rate limit'));
      return Promise.resolve({
        stk_cd: '005930',
        stk_nm: '삼성전자',
        cur_prc: 71000,
        prdy_vrss: 500,
        prdy_ctrt: 1.23,
        opng_prc: 70500,
        high_prc: 71200,
        low_prc: 70200,
        trde_qty: 1000,
        trde_prica: 71000000,
        per: null,
        pbr: null,
        eps: null,
        bps: null,
        timestamp: '2026-07-13T00:00:00Z',
      });
    });

    render(<WatchlistPanel />);

    await waitFor(() => expect(screen.getByText('₩71,000')).toBeInTheDocument());
    // Failed ticker keeps its last-known (missing) price — honest DASH, no crash.
    expect(screen.getByText('SK하이닉스')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('WatchlistPanel — coin path unchanged', () => {
  it('coin 종목은 기존처럼 getCoinTickers로 갱신된다', async () => {
    useStore.setState({
      activeMarket: 'coin',
      upbitApiConfigured: true,
      basket: { items: [coinItem()], maxItems: 10, isUpdating: false },
    });
    getCoinTickers.mockResolvedValue({
      tickers: [
        {
          market: 'KRW-BTC',
          trade_price: 50_000_000,
          change: 'RISE',
          change_rate: 0.012,
          change_price: 600_000,
          high_price: 50_500_000,
          low_price: 49_000_000,
          trade_volume: 10,
          acc_trade_price_24h: 1_000_000_000,
          timestamp: '2026-07-13T00:00:00Z',
        },
      ],
      total: 1,
    });

    render(<WatchlistPanel />);

    await waitFor(() => expect(getCoinTickers).toHaveBeenCalledWith(['KRW-BTC']));
    await waitFor(() => expect(screen.getByText('₩50,000,000')).toBeInTheDocument());
    expect(screen.getByText('+1.20%')).toBeInTheDocument();
    expect(getKRStockTicker).not.toHaveBeenCalled();
  });
});
