/**
 * P1-3 scanner loop-liveness classification (pure function only — the hook
 * itself is exercised indirectly via ScannerLivenessChip.test.tsx).
 *
 * Closes the Task 6 Step 2 gap: only the agent-chat coordinator got a
 * liveness chip (useLoopLiveness); the background scanner had none.
 */
import { describe, it, expect } from 'vitest';
import { computeScannerLiveness, SCANNER_STALE_AFTER_MS } from './useScannerLiveness';
import type { ScanProgressResponse } from '@/types';

function status(overrides: Partial<ScanProgressResponse> = {}): ScanProgressResponse {
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

describe('computeScannerLiveness', () => {
  it('is unknown when the status could not be fetched (null)', () => {
    expect(computeScannerLiveness(null)).toBe('unknown');
  });

  it('is idle when the scanner has never been started', () => {
    expect(computeScannerLiveness(status({ status: 'idle' }))).toBe('idle');
  });

  it('is idle when paused', () => {
    expect(computeScannerLiveness(status({ status: 'paused' }))).toBe('idle');
  });

  it('is idle when a scan completed cleanly — a finished scan is NOT dead', () => {
    const now = Date.now();
    const longAgo = new Date(now - 5 * 60 * 60_000).toISOString(); // 5h ago
    expect(
      computeScannerLiveness(
        status({ status: 'completed', started_at: longAgo, completed_at: longAgo }),
        now,
      ),
    ).toBe('idle');
  });

  it('is idle (not dead) when the last run ended in error', () => {
    const now = Date.now();
    const longAgo = new Date(now - 5 * 60 * 60_000).toISOString();
    expect(
      computeScannerLiveness(status({ status: 'error', started_at: longAgo, last_error: 'boom' }), now),
    ).toBe('idle');
  });

  it('is active while a scan is running with a fresh started_at', () => {
    const now = Date.now();
    const recent = new Date(now - 60_000).toISOString();
    expect(computeScannerLiveness(status({ status: 'running', started_at: recent }), now)).toBe('active');
  });

  it('is active when running but started_at not yet reported (just kicked off)', () => {
    expect(computeScannerLiveness(status({ status: 'running', started_at: null }))).toBe('active');
  });

  it('is stale when running but started_at is far older than any real scan should take', () => {
    const now = Date.now();
    const dead = new Date(now - SCANNER_STALE_AFTER_MS - 60_000).toISOString();
    expect(computeScannerLiveness(status({ status: 'running', started_at: dead }), now)).toBe('stale');
  });

  it('a DEAD scanner reporting status=running does not display as active', () => {
    const now = Date.now();
    const dead = new Date(now - 3 * 60 * 60_000).toISOString(); // 3h silence
    const level = computeScannerLiveness(status({ status: 'running', started_at: dead }), now);
    expect(level).not.toBe('active');
    expect(level).toBe('stale');
  });
});
