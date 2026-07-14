/**
 * Loop-liveness (P1-3)
 *
 * `is_running` alone can't distinguish a healthy autonomous loop from a
 * dead one — a scheduler whose job crashed out of its try/except (or whose
 * process hung) can leave `_running=True` forever. The agent-chat
 * coordinator status route additionally reports `last_check_at`, a
 * heartbeat set at the top of every executed tick (see
 * services/agent_chat/coordinator.py `_check_watch_list`). Comparing that
 * against `check_interval_minutes` lets the shell tell "still ticking" apart
 * from "reports running but hasn't ticked in N cycles" — i.e. a dead
 * scheduler cannot silently display as active.
 */
import { useEffect, useState } from 'react';
import { getAgentChatStatus } from '@/api/client';
import type { AgentChatCoordinatorStatus } from '@/types';

export type LoopLivenessLevel = 'active' | 'stale' | 'off' | 'unknown';

const POLL_MS = 15_000;
// Floor at 2 minutes so a fast check_interval doesn't false-positive on its
// own cadence; otherwise allow one full missed cycle before calling it stale.
const MIN_STALE_AFTER_MS = 2 * 60_000;

export function staleAfterMs(checkIntervalMinutes: number): number {
  return Math.max(MIN_STALE_AFTER_MS, checkIntervalMinutes * 60_000 * 2);
}

/** Pure classification — kept separate from the hook so it's trivially testable. */
export function computeLoopLiveness(
  status: AgentChatCoordinatorStatus | null,
  now: number = Date.now(),
): LoopLivenessLevel {
  if (!status) return 'unknown';
  if (!status.is_running) return 'off';
  if (!status.last_check_at) return 'active'; // just started, first tick still pending
  const age = now - new Date(status.last_check_at).getTime();
  return age > staleAfterMs(status.check_interval_minutes) ? 'stale' : 'active';
}

export function useLoopLiveness(pollMs: number = POLL_MS) {
  const [status, setStatus] = useState<AgentChatCoordinatorStatus | null>(null);
  const [level, setLevel] = useState<LoopLivenessLevel>('unknown');

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const data = await getAgentChatStatus();
        if (cancelled) return;
        setStatus(data);
        setLevel(computeLoopLiveness(data));
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
