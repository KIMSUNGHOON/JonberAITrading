import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ScannerLivenessChip } from './ScannerLivenessChip';
import type { ScanProgressResponse } from '@/types';

const getScanProgress = vi.fn();
vi.mock('@/api/client', () => ({
  getScanProgress: (...a: unknown[]) => getScanProgress(...a),
}));

function baseStatus(overrides: Partial<ScanProgressResponse> = {}): ScanProgressResponse {
  return {
    status: 'idle',
    total_stocks: 0,
    completed: 0,
    in_progress: 0,
    failed: 0,
    progress_pct: 0,
    current_stocks: [],
    buy_count: 0,
    sell_count: 0,
    hold_count: 0,
    watch_count: 0,
    avoid_count: 0,
    started_at: null,
    estimated_completion: null,
    completed_at: null,
    last_scan_date: null,
    last_error: null,
    ...overrides,
  };
}

beforeEach(() => {
  getScanProgress.mockReset();
});

describe('ScannerLivenessChip', () => {
  it('shows SCAN ACTIVE while a scan is running', async () => {
    getScanProgress.mockResolvedValue(
      baseStatus({ status: 'running', started_at: new Date().toISOString() }),
    );
    render(<ScannerLivenessChip />);
    await waitFor(() => expect(screen.getByText('SCAN ACTIVE')).toBeInTheDocument());
  });

  it('shows SCAN IDLE when the scanner has never run', async () => {
    getScanProgress.mockResolvedValue(baseStatus({ status: 'idle' }));
    render(<ScannerLivenessChip />);
    await waitFor(() => expect(screen.getByText('SCAN IDLE')).toBeInTheDocument());
  });

  it('shows SCAN IDLE (not dead) when a scan completed cleanly', async () => {
    const longAgo = new Date(Date.now() - 5 * 60 * 60_000).toISOString();
    getScanProgress.mockResolvedValue(
      baseStatus({ status: 'completed', started_at: longAgo, completed_at: longAgo }),
    );
    render(<ScannerLivenessChip />);
    await waitFor(() => expect(screen.getByText('SCAN IDLE')).toBeInTheDocument());
    expect(screen.queryByText('SCAN STALE')).not.toBeInTheDocument();
  });

  it('shows SCAN STALE when status=running but started_at is far in the past (dead scan)', async () => {
    const dead = new Date(Date.now() - 3 * 60 * 60_000).toISOString();
    getScanProgress.mockResolvedValue(baseStatus({ status: 'running', started_at: dead }));
    render(<ScannerLivenessChip />);
    await waitFor(() => expect(screen.getByText('SCAN STALE')).toBeInTheDocument());
    expect(screen.queryByText('SCAN ACTIVE')).not.toBeInTheDocument();
  });

  it('shows an unknown state when the status fetch fails', async () => {
    getScanProgress.mockRejectedValue(new Error('network down'));
    render(<ScannerLivenessChip />);
    await waitFor(() => expect(screen.getByText('SCAN —')).toBeInTheDocument());
  });
});
