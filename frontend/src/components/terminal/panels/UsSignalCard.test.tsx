import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import UsSignalCard from './UsSignalCard';
import * as client from '@/api/client';

const base = {
  components: [
    { ticker: 'SMH', weight: 0.5, change_pct: 4.52 },
    { ticker: 'MU', weight: 0.25, change_pct: 12.17 },
    { ticker: 'NVDA', weight: 0.25, change_pct: 1.97 },
  ],
  curation: [
    { ticker: '005930', name: '삼성전자' },
    { ticker: '402340', name: 'SK스퀘어' },
  ],
};

describe('UsSignalCard', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fresh: 헤드라인 %와 큐레이션 표시', async () => {
    vi.spyOn(client, 'getUsSignal').mockResolvedValue({
      enabled: true, as_of: '2026-07-22', signal_pct: 5.8, signal: 1.0,
      computed_at: '2026-07-22T03:09:12Z', ...base,
    } as any);
    render(<UsSignalCard />);
    await waitFor(() => expect(screen.getByText(/간밤 미 AI 반도체/)).toBeInTheDocument());
    expect(screen.getByText(/삼성전자/)).toBeInTheDocument();
    expect(screen.getByText(/SK스퀘어/)).toBeInTheDocument();
  });

  it('disabled: 비활성 메시지 + 큐레이션은 표시', async () => {
    vi.spyOn(client, 'getUsSignal').mockResolvedValue({
      enabled: false, as_of: null, signal_pct: null, signal: null,
      computed_at: null, components: base.components.map(c => ({ ...c, change_pct: null })),
      curation: base.curation,
    } as any);
    render(<UsSignalCard />);
    await waitFor(() => expect(screen.getByText(/US 신호 비활성/)).toBeInTheDocument());
    expect(screen.getByText(/삼성전자/)).toBeInTheDocument();
  });

  it('awaiting: enabled이나 as_of null → 대기 메시지', async () => {
    vi.spyOn(client, 'getUsSignal').mockResolvedValue({
      enabled: true, as_of: null, signal_pct: null, signal: null,
      computed_at: null, components: base.components.map(c => ({ ...c, change_pct: null })),
      curation: base.curation,
    } as any);
    render(<UsSignalCard />);
    await waitFor(() => expect(screen.getByText(/당일 신호 대기 중/)).toBeInTheDocument());
  });
});
