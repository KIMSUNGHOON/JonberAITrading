/**
 * Agent-debate tile — 4 analyst votes + consensus for the current discussion.
 *
 * Votes/consensus are NOT in the store; they live in the agent-chat coordinator
 * (REST). This tile resolves a session (active discussion → else most-recent),
 * fetches its detail, and polls every 5s. When the coordinator is dormant (its
 * default per project notes) there is no session and the tile keeps its honest
 * empty structure — the 4 rows and consensus stay '—', nothing is fabricated.
 * The 75% gate marker is a display constant, not an authoritative threshold.
 */
import { useEffect, useState } from 'react';
import {
  getAgentChatActiveDiscussions,
  getAgentChatSessions,
  getAgentChatSessionDetail,
} from '@/api/client';
import type { AgentChatSessionDetail, AgentChatVote, AgentChatVoteType } from '@/types';
import { DASH } from './shared';

const ANALYSTS: { key: string; label: string }[] = [
  { key: 'technical', label: 'TECHNICAL' },
  { key: 'fundamental', label: 'FUNDAMENTAL' },
  { key: 'sentiment', label: 'SENTIMENT' },
  { key: 'risk', label: 'RISK' },
];

const VOTE_LABEL: Record<AgentChatVoteType, string> = {
  STRONG_BUY: 'S.BUY',
  BUY: 'BUY',
  HOLD: 'HOLD',
  SELL: 'SELL',
  STRONG_SELL: 'S.SELL',
  ABSTAIN: 'ABS',
};

function voteColor(v: AgentChatVoteType): string {
  if (v === 'STRONG_BUY' || v === 'BUY') return 'text-up';
  if (v === 'SELL' || v === 'STRONG_SELL') return 'text-down';
  if (v === 'HOLD') return 'text-muted';
  return 'text-dim';
}

/** Literal bg classes (Tailwind JIT can't see runtime-built class strings). */
function voteDot(v: AgentChatVoteType | undefined): string {
  if (!v) return 'bg-dim';
  if (v === 'STRONG_BUY' || v === 'BUY') return 'bg-up';
  if (v === 'SELL' || v === 'STRONG_SELL') return 'bg-down';
  if (v === 'HOLD') return 'bg-muted';
  return 'bg-dim';
}

function useDebateSession() {
  const [detail, setDetail] = useState<AgentChatSessionDetail | null>(null);

  useEffect(() => {
    let alive = true;

    async function resolveSessionId(): Promise<string | null> {
      const active = await getAgentChatActiveDiscussions().catch(() => null);
      if (active && active.discussions.length > 0) return active.discussions[0].session_id;
      const recent = await getAgentChatSessions({ limit: 1 }).catch(() => null);
      if (recent && recent.sessions.length > 0) return recent.sessions[0].id;
      return null;
    }

    async function run() {
      const sessionId = await resolveSessionId();
      if (!alive) return;
      if (!sessionId) {
        setDetail(null);
        return;
      }
      const d = await getAgentChatSessionDetail(sessionId).catch(() => null);
      if (!alive) return;
      setDetail(d);
    }

    run();
    const id = setInterval(run, 5_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return detail;
}

export function DebatePanel() {
  const detail = useDebateSession();

  const votesByType = new Map<string, AgentChatVote>();
  detail?.votes
    .filter((v) => v.agent_type !== 'moderator')
    .forEach((v) => votesByType.set(v.agent_type, v));

  const consensusPct = detail ? Math.round(detail.consensus_level * 100) : null;

  return (
    <div className="flex flex-col h-full">
      {detail && (
        <div className="flex items-center gap-2 px-2.5 py-1 border-b border-hairline text-[10px]">
          <span className="font-semibold text-ink">{detail.stock_name || detail.ticker}</span>
          <span className="text-dim uppercase">{detail.status}</span>
          {detail.decision && (
            <span className="ml-auto text-muted">
              결정: <span className="text-ink font-semibold">{detail.decision.action}</span>
            </span>
          )}
        </div>
      )}

      <table className="w-full text-[12px] tabular-nums">
        <tbody className="text-muted">
          {ANALYSTS.map((a) => {
            const vote = votesByType.get(a.key);
            return (
              <tr key={a.key} className="border-b border-hairline/60">
                <td className="text-left px-2.5 h-6">
                  <span className="inline-flex items-center gap-2 font-semibold">
                    <span className={`w-2 h-2 rounded-sm ${voteDot(vote?.vote)}`} />
                    {a.label}
                  </span>
                </td>
                <td className={`text-right px-2.5 ${vote ? voteColor(vote.vote) : 'text-dim'}`}>
                  {vote ? VOTE_LABEL[vote.vote] : DASH}
                </td>
                <td className="text-right px-2.5 text-dim">
                  {vote ? `${Math.round(vote.confidence * 100)}%` : DASH}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="flex items-center gap-2.5 px-2.5 py-2 border-t border-hairline mt-auto">
        <span className="text-[10px] text-muted">CONSENSUS</span>
        <span className={`text-[16px] font-bold tabular-nums ${consensusPct != null ? 'text-ink' : 'text-dim'}`}>
          {consensusPct != null ? `${consensusPct}%` : DASH}
        </span>
        <div className="flex-1 h-1.5 rounded bg-elevated relative">
          {consensusPct != null && (
            <span
              className="absolute inset-y-0 left-0 rounded bg-accent transition-[width] duration-500"
              style={{ width: `${Math.min(100, Math.max(0, consensusPct))}%` }}
            />
          )}
          {/* 75% gate is a display constant, not an enforced backend threshold. */}
          <span className="absolute top-[-3px] bottom-[-3px] left-[75%] w-0.5 bg-warn" />
        </div>
        <span className="text-[11px] text-muted">gate 75%</span>
      </div>
    </div>
  );
}
