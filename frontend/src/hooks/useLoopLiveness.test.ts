/**
 * P1-3 loop-liveness classification (pure function only — the hook itself is
 * exercised indirectly via LoopLivenessChip.test.tsx).
 */
import { describe, it, expect } from 'vitest';
import { computeLoopLiveness, staleAfterMs } from './useLoopLiveness';
import type { AgentChatCoordinatorStatus } from '@/types';

function status(overrides: Partial<AgentChatCoordinatorStatus> = {}): AgentChatCoordinatorStatus {
  return {
    is_running: true,
    active_discussions: 0,
    total_sessions: 0,
    check_interval_minutes: 5,
    max_concurrent_discussions: 3,
    last_check_at: null,
    ...overrides,
  };
}

describe('computeLoopLiveness', () => {
  it('is unknown when the status could not be fetched (null)', () => {
    expect(computeLoopLiveness(null)).toBe('unknown');
  });

  it('is off when the coordinator is not running', () => {
    expect(computeLoopLiveness(status({ is_running: false }))).toBe('off');
  });

  it('is active when running but no tick has fired yet (just started)', () => {
    expect(computeLoopLiveness(status({ is_running: true, last_check_at: null }))).toBe('active');
  });

  it('is active when the last tick is recent relative to check_interval_minutes', () => {
    const now = Date.now();
    const recentTick = new Date(now - 30_000).toISOString(); // 30s ago
    expect(computeLoopLiveness(status({ last_check_at: recentTick }), now)).toBe('active');
  });

  it('is stale when running but the last tick is far older than the check interval', () => {
    const now = Date.now();
    // check_interval_minutes=5 -> stale threshold = 10 min; 20 min silence.
    const deadTick = new Date(now - 20 * 60_000).toISOString();
    expect(
      computeLoopLiveness(status({ is_running: true, check_interval_minutes: 5, last_check_at: deadTick }), now)
    ).toBe('stale');
  });

  it('a DEAD scheduler reporting is_running=true does not display as active', () => {
    const now = Date.now();
    const deadTick = new Date(now - 60 * 60_000).toISOString(); // 1 hour silence
    const level = computeLoopLiveness(status({ is_running: true, last_check_at: deadTick }), now);
    expect(level).not.toBe('active');
    expect(level).toBe('stale');
  });

  it('respects a larger check_interval_minutes when computing staleness', () => {
    const now = Date.now();
    const tick15MinAgo = new Date(now - 15 * 60_000).toISOString();
    // interval=5 -> threshold 10min -> 15min silence is stale
    expect(
      computeLoopLiveness(status({ check_interval_minutes: 5, last_check_at: tick15MinAgo }), now)
    ).toBe('stale');
    // interval=20 -> threshold 40min -> 15min silence is still active
    expect(
      computeLoopLiveness(status({ check_interval_minutes: 20, last_check_at: tick15MinAgo }), now)
    ).toBe('active');
  });

  it('staleAfterMs floors at 2 minutes even for a very short check interval', () => {
    expect(staleAfterMs(1)).toBe(2 * 60_000);
  });
});
