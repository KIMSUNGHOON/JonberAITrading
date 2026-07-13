import { describe, it, expect, vi, beforeEach } from 'vitest';
import axios from 'axios';

vi.mock('axios');

describe('getOperations', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('GET /trading/operations에 market 파라미터를 전달한다', async () => {
    const get = vi.fn().mockResolvedValue({ data: { errors: {} } });
    (axios.create as ReturnType<typeof vi.fn>).mockReturnValue({
      get,
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    });
    const { getOperations } = await import('./client');
    await getOperations('kiwoom');
    expect(get).toHaveBeenCalledWith('/trading/operations', {
      params: { market: 'kiwoom' },
    });
  });
});
