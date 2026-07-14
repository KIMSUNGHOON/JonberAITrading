/**
 * Agent-debate tile — 4 analyst votes + consensus for the current discussion,
 * now a LIVE control card (P2 T6) rather than a decorative REST-poll tile:
 *
 * - Live updates: once an ACTIVE session is resolved, `useAgentChatWebSocket`
 *   streams vote/status_change/decision frames straight into local state
 *   (the same hook + the same active-session gating ChatSessionViewer already
 *   uses — a decided/historical session gets no WS and no "LIVE" badge). The
 *   5s REST poll is the ONLY way to discover a session id, and it keeps
 *   running as a true fallback/resync while the WS is disconnected — but it
 *   STOPS once the WS reports connected (mirroring ChatSessionViewer), so a
 *   stale REST snapshot can never race a fresher WS-pushed vote/decision and
 *   clobber it via the panel's replace-all `setDetail`.
 * - Start affordance: when the coordinator is dormant (its default per
 *   project notes) there is no session to show votes for. Instead of a dead
 *   '—' tile, a "토론 시작" button calls the coordinator launch path
 *   (`startAgentChat`) so the tile can go from decorative to actionable.
 * - Deep link: the session header is a real link to the /agent-chat session
 *   viewer (full message history, decision detail) — this tile only ever
 *   shows the compact vote/consensus summary.
 *
 * Honesty is preserved throughout: no session → no fabricated votes, and a
 * cold coordinator status shows "확인 중" rather than guessing. The 75% gate
 * marker is a display constant, not an authoritative threshold.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getAgentChatActiveDiscussions,
  getAgentChatSessions,
  getAgentChatSessionDetail,
  getAgentChatStatus,
  startAgentChat,
} from '@/api/client';
import { useAgentChatWebSocket } from '@/hooks/useAgentChatWebSocket';
import type {
  AgentChatSessionDetail,
  AgentChatVote,
  AgentChatVoteType,
  AgentChatDecision,
  AgentChatSessionStatus,
} from '@/types';
import { Awaiting, DASH } from './shared';

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

const POLL_MS = 5_000;

/** Statuses for which the coordinator is still actively working the session
 *  (mirrors ChatSessionViewer's `isActiveSession`). A decided/cancelled/error
 *  session is historical — it gets no WS connection and no "LIVE" badge. */
const ACTIVE_STATUSES: AgentChatSessionStatus[] = [
  'initializing',
  'analyzing',
  'discussing',
  'voting',
];

function useDebateSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentChatSessionDetail | null>(null);
  const [coordinatorRunning, setCoordinatorRunning] = useState<boolean | null>(null);
  const [ready, setReady] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const resolveSessionId = useCallback(async (): Promise<string | null> => {
    const active = await getAgentChatActiveDiscussions().catch(() => null);
    if (active && active.discussions.length > 0) return active.discussions[0].session_id;
    const recent = await getAgentChatSessions({ limit: 1 }).catch(() => null);
    if (recent && recent.sessions.length > 0) return recent.sessions[0].id;
    return null;
  }, []);

  const refreshAll = useCallback(async () => {
    const [status, sid] = await Promise.all([
      getAgentChatStatus().catch(() => null),
      resolveSessionId(),
    ]);
    if (!aliveRef.current) return;
    setCoordinatorRunning(status ? status.is_running : null);
    setSessionId(sid);
    if (!sid) {
      setDetail(null);
    } else {
      const d = await getAgentChatSessionDetail(sid).catch(() => null);
      if (!aliveRef.current) return;
      if (d) setDetail(d);
    }
    setReady(true);
  }, [resolveSessionId]);

  useEffect(() => {
    aliveRef.current = true;
    refreshAll();
    return () => {
      aliveRef.current = false;
    };
  }, [refreshAll]);

  // Live WS wiring (P2 T6) — reuses the already-built agent-chat hook so this
  // tile's votes/consensus update as frames arrive, without waiting for the
  // next 5s REST poll. Only connects once a session id is resolved AND the
  // session is still active (mirrors ChatSessionViewer): a decided/idle
  // session is historical, so it gets no persistent WS and no "LIVE" badge.
  const onVote = useCallback((vote: AgentChatVote) => {
    setDetail((prev) => {
      if (!prev) return prev;
      const others = prev.votes.filter((v) => v.agent_type !== vote.agent_type);
      return { ...prev, votes: [...others, vote] };
    });
  }, []);

  const onStatusChange = useCallback(
    (_status: AgentChatSessionStatus, session: AgentChatSessionDetail) => {
      setDetail(session);
    },
    [],
  );

  const onDecision = useCallback((decision: AgentChatDecision) => {
    setDetail((prev) =>
      prev ? { ...prev, decision, consensus_level: decision.consensus_level } : prev,
    );
  }, []);

  const isActiveSession = detail !== null && ACTIVE_STATUSES.includes(detail.status);

  const { isConnected } = useAgentChatWebSocket({
    sessionId: isActiveSession ? sessionId : null,
    autoConnect: true,
    onVote,
    onStatusChange,
    onDecision,
  });

  // Fallback REST poll — mirrors ChatSessionViewer: runs only while the WS is
  // NOT connected, so REST snapshots never race the socket and clobber
  // fresher WS-pushed vote/decision state with a stale `setDetail` replace.
  useEffect(() => {
    if (isConnected) return;
    const id = setInterval(refreshAll, POLL_MS);
    return () => clearInterval(id);
  }, [isConnected, refreshAll]);

  const startDiscussion = useCallback(async () => {
    setStarting(true);
    setStartError(null);
    try {
      await startAgentChat();
      await refreshAll();
    } catch (e) {
      setStartError(e instanceof Error ? e.message : '토론 시작 실패');
    } finally {
      setStarting(false);
    }
  }, [refreshAll]);

  return { ready, detail, coordinatorRunning, isConnected, starting, startError, startDiscussion };
}

export function DebatePanel() {
  const navigate = useNavigate();
  const { ready, detail, coordinatorRunning, isConnected, starting, startError, startDiscussion } =
    useDebateSession();

  const openViewer = useCallback(() => navigate('/agent-chat'), [navigate]);

  if (!ready) {
    return <Awaiting label="토론 상태 확인 중…" />;
  }

  if (!detail) {
    const running = coordinatorRunning === true;
    return (
      <div className="flex flex-col h-full items-center justify-center gap-2 py-6 px-4 text-center">
        <span className="text-[11px] text-dim">
          {running ? '코디네이터 실행 중 · 활성 토론 대기' : '코디네이터 미기동 · 활성 토론 없음'}
        </span>
        {!running && (
          <button
            type="button"
            onClick={startDiscussion}
            disabled={starting}
            className="text-[11px] font-semibold text-accent hover:underline disabled:opacity-50"
          >
            {starting ? '시작 중…' : '토론 시작'}
          </button>
        )}
        {startError && <span className="text-[10px] text-down">{startError}</span>}
        <button
          type="button"
          onClick={openViewer}
          className="text-[10px] text-dim hover:text-accent"
        >
          에이전트 토론 뷰어 열기 →
        </button>
      </div>
    );
  }

  const votesByType = new Map<string, AgentChatVote>();
  detail.votes
    .filter((v) => v.agent_type !== 'moderator')
    .forEach((v) => votesByType.set(v.agent_type, v));

  const consensusPct = Math.round(detail.consensus_level * 100);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2.5 py-1 border-b border-hairline text-[10px]">
        <span className="font-semibold text-ink">{detail.stock_name || detail.ticker}</span>
        <span className="text-dim uppercase">{detail.status}</span>
        {isConnected && (
          <span className="text-accent font-semibold" title="실시간 연결됨">
            LIVE
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {detail.decision && (
            <span className="text-muted">
              결정: <span className="text-ink font-semibold">{detail.decision.action}</span>
            </span>
          )}
          <button
            type="button"
            onClick={openViewer}
            className="text-dim hover:text-accent font-semibold"
            title="에이전트 토론 세션 뷰어 열기"
          >
            세션 보기 →
          </button>
        </div>
      </div>

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
        <span className="text-[16px] font-bold tabular-nums text-ink">{consensusPct}%</span>
        <div className="flex-1 h-1.5 rounded bg-elevated relative">
          <span
            className="absolute inset-y-0 left-0 rounded bg-accent transition-[width] duration-500"
            style={{ width: `${Math.min(100, Math.max(0, consensusPct))}%` }}
          />
          {/* 75% gate is a display constant, not an enforced backend threshold. */}
          <span className="absolute top-[-3px] bottom-[-3px] left-[75%] w-0.5 bg-warn" />
        </div>
        <span className="text-[11px] text-muted">gate 75%</span>
      </div>
    </div>
  );
}
