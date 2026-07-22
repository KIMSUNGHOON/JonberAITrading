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

const subSignals = {
  memory: { signal: 0.6, signal_pct: 8.4, components: { MU: 12.17, SMH: 4.52 } },
  accel: { signal: 0.3, signal_pct: 3.1, components: { NVDA: 1.97, AVGO: 4.3 } },
  demand: { signal: 0.2, signal_pct: 1.5, components: { MSFT: 1.1, GOOGL: 0.9, AMZN: 2.2, META: 1.8 } },
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

  it('fresh + sub_signals: 메모리/가속기/수요 라벨·%·큐레이션 signal_type 배지·틸트 노트', async () => {
    vi.spyOn(client, 'getUsSignal').mockResolvedValue({
      enabled: true, as_of: '2026-07-22', signal_pct: 5.8, signal: 1.0,
      computed_at: '2026-07-22T03:09:12Z',
      components: base.components,
      curation: [
        { ticker: '005930', name: '삼성전자', signal_type: 'memory' },
        { ticker: '007660', name: '이수페타시스', signal_type: 'accel' },
      ],
      sub_signals: subSignals,
    } as any);
    render(<UsSignalCard />);
    await waitFor(() => expect(screen.getByText(/간밤 미 AI 반도체/)).toBeInTheDocument());

    expect(screen.getByText('메모리')).toBeInTheDocument();
    expect(screen.getByText('가속기')).toBeInTheDocument();
    expect(screen.getByText('수요')).toBeInTheDocument();
    expect(screen.getByText('+8.40%')).toBeInTheDocument(); // memory.signal_pct
    expect(screen.getByText('+3.10%')).toBeInTheDocument(); // accel.signal_pct
    expect(screen.getByText('+1.50%')).toBeInTheDocument(); // demand.signal_pct

    expect(screen.getByText('[memory]')).toBeInTheDocument();
    expect(screen.getByText('[accel]')).toBeInTheDocument();

    // demand.signal(0.2) > 0 → 틸트 노트 표시
    expect(screen.getByText(/발굴 momentum 틸트 활성/)).toBeInTheDocument();
  });

  it('fresh: sub_signals 없음(null-safe) → 서브신호 라인 없이 overall+큐레이션만', async () => {
    vi.spyOn(client, 'getUsSignal').mockResolvedValue({
      enabled: true, as_of: '2026-07-22', signal_pct: 5.8, signal: 1.0,
      computed_at: '2026-07-22T03:09:12Z', sub_signals: null, ...base,
    } as any);
    render(<UsSignalCard />);
    await waitFor(() => expect(screen.getByText(/간밤 미 AI 반도체/)).toBeInTheDocument());
    expect(screen.queryByText('메모리')).not.toBeInTheDocument();
    expect(screen.queryByText(/발굴 momentum 틸트 활성/)).not.toBeInTheDocument();
    expect(screen.getByText(/삼성전자/)).toBeInTheDocument();
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
