/**
 * Scanner loop-liveness (P1-3, Task 6 Step 2 gap close)
 *
 * The background scanner is an on-demand ONE-SHOT job, not a perpetual
 * scheduler like the agent-chat coordinator (see useLoopLiveness) — it
 * scans once and stops. That means `status === 'idle' | 'completed' |
 * 'paused' | 'error'` is a healthy RESTING state, not a dead loop, and must
 * never be shown as "dead". The only way for the scanner to look "alive but
 * actually dead" is `status === 'running'` while `started_at` goes stale far
 * longer than any real scan should take — background_scanner throttles
 * Kiwoom calls to ~1.4 req/s, so a full KOSPI/KOSDAQ sweep can legitimately
 * run tens of minutes, hence the generous threshold below.
 */
import { useEffect, useState } from 'react';
import { getScanProgress } from '@/api/client';
import type { ScanProgressResponse } from '@/types';

export type ScannerLivenessLevel = 'active' | 'idle' | 'stale' | 'unknown';

const POLL_MS = 15_000;
// A full KOSPI/KOSDAQ sweep throttled at ~1.4 req/s can legitimately run for
// tens of minutes; give it a generous margin before calling it dead.
export const SCANNER_STALE_AFTER_MS = 60 * 60_000; // 60 min

/** Pure classification — kept separate from the hook so it's trivially testable. */
export function computeScannerLiveness(
  status: ScanProgressResponse | null,
  now: number = Date.now(),
): ScannerLivenessLevel {
  if (!status) return 'unknown';
  // idle/paused/completed/error are all resting states — a finished or
  // never-started scan is NOT a dead loop.
  if (status.status !== 'running') return 'idle';
  if (!status.started_at) return 'active'; // just kicked off, no timestamp to judge staleness against yet
  const age = now - new Date(status.started_at).getTime();
  return age > SCANNER_STALE_AFTER_MS ? 'stale' : 'active';
}

export function useScannerLiveness(pollMs: number = POLL_MS) {
  const [status, setStatus] = useState<ScanProgressResponse | null>(null);
  const [level, setLevel] = useState<ScannerLivenessLevel>('unknown');

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const data = await getScanProgress();
        if (cancelled) return;
        setStatus(data);
        setLevel(computeScannerLiveness(data));
      } catch {
        if (cancelled) return;
        setStatus(null);
        setLevel('unknown');
      }
    };

    tick();
    const id = setInterval(tick, pollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollMs]);

  return { status, level };
}
