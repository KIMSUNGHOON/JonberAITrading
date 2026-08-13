/**
 * FI-4: client.ts fetch functions for the dedicated discovery ledger page.
 * Pins query-parameter assembly + response passthrough against FI-2's
 * GET /trading/discovery/candidates · /performance routes. Mirrors
 * operations.test.ts's axios-mock pattern (getOperations).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';

vi.mock('axios');

describe('getDiscoveryCandidates', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('전달된 필터를 params로 그대로 조립한다', async () => {
    const get = vi.fn().mockResolvedValue({ data: { candidates: [], count: 0 } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryCandidates } = await import('./client');
    await getDiscoveryCandidates({
      trade_date: '2026-07-18',
      promoted: true,
      limit: 10,
      offset: 5,
    });
    expect(get).toHaveBeenCalledWith('/trading/discovery/candidates', {
      params: { trade_date: '2026-07-18', promoted: true, limit: 10, offset: 5 },
    });
  });

  it('인자 없이 호출하면 params가 undefined다(백엔드 기본값에 위임)', async () => {
    const get = vi.fn().mockResolvedValue({ data: { candidates: [], count: 0 } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryCandidates } = await import('./client');
    await getDiscoveryCandidates();
    expect(get).toHaveBeenCalledWith('/trading/discovery/candidates', { params: undefined });
  });

  it('promoted=false도(undefined와 구분해) 그대로 전달한다', async () => {
    const get = vi.fn().mockResolvedValue({ data: { candidates: [], count: 0 } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryCandidates } = await import('./client');
    await getDiscoveryCandidates({ promoted: false });
    expect(get).toHaveBeenCalledWith('/trading/discovery/candidates', {
      params: { promoted: false },
    });
  });

  it('응답 데이터를 그대로 반환한다(가공 없음)', async () => {
    const payload = {
      candidates: [
        {
          id: 'x1', trade_date: '2026-07-18', ticker: '005930', name: '삼성전자',
          composite_score: 0.72, top_strategy_tag: 'momentum', regime_label: 'neutral',
          rank: 1, promoted: true, skip_reason: null, close_price: 70000,
          fwd_1d: 0.012, fwd_5d: 0.03, fwd_20d: null,
        },
      ],
      count: 1,
    };
    const get = vi.fn().mockResolvedValue({ data: payload });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryCandidates } = await import('./client');
    const result = await getDiscoveryCandidates({ trade_date: '2026-07-18' });
    expect(result).toEqual(payload);
  });
});

describe('getDiscoveryPerformance', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('days를 params로 전달한다', async () => {
    const get = vi.fn().mockResolvedValue({ data: { days: 30, by_strategy_tag: {} } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryPerformance } = await import('./client');
    await getDiscoveryPerformance(30);
    expect(get).toHaveBeenCalledWith('/trading/discovery/performance', {
      params: { days: 30 },
    });
  });

  it('인자 없이 호출하면 params가 undefined다(백엔드 기본값 14에 위임)', async () => {
    const get = vi.fn().mockResolvedValue({ data: { days: 14, by_strategy_tag: {} } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryPerformance } = await import('./client');
    await getDiscoveryPerformance();
    expect(get).toHaveBeenCalledWith('/trading/discovery/performance', { params: undefined });
  });

  it('by_strategy_tag 응답을 그대로 반환한다', async () => {
    const payload = {
      days: 14,
      by_strategy_tag: {
        momentum: { candidates: 2, promoted: 1, avg_fwd_1d: -0.005, avg_fwd_5d: 0.01, hit_rate_5d: 0.5 },
      },
    };
    const get = vi.fn().mockResolvedValue({ data: payload });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getDiscoveryPerformance } = await import('./client');
    const result = await getDiscoveryPerformance();
    expect(result).toEqual(payload);
  });
});
