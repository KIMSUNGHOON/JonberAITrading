/**
 * AgentChatDashboard Component
 *
 * Main dashboard for Agent Group Chat system.
 * Controls coordinator start/stop and shows active discussions.
 *
 * R5-P2-UX B2: this page used to full-page-swap to `ChatSessionViewer` the
 * moment a session was selected (the app's only screen that does that — see
 * the page-ux audit §B). It's now master-detail: the session list stays
 * visible (narrowed) whenever the detail pane shows a viewer, so selecting a
 * session never wipes the page. Selection is also driven by the URL
 * (`?session=<id>`) rather than local-only state, so DebatePanel's
 * "세션 보기 →" deep link (B1) actually opens the session it links to, and
 * the address bar always reflects what's on screen.
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  MessageSquare,
  Play,
  Square,
  RefreshCw,
  Users,
  Clock,
  TrendingUp,
  AlertCircle,
  Settings,
} from 'lucide-react';
import {
  getAgentChatStatus,
  startAgentChat,
  stopAgentChat,
  getAgentChatActiveDiscussions,
  getAgentChatSessions,
  startAgentChatDiscussion,
} from '@/api/client';
import type {
  AgentChatCoordinatorStatus,
  AgentChatActiveDiscussion,
  AgentChatSessionSummary,
} from '@/types';
import { computeLoopLiveness } from '@/hooks/useLoopLiveness';
import { ChatSessionList } from './ChatSessionList';
import { ChatSessionViewer } from './ChatSessionViewer';
import { PositionMonitor } from './PositionMonitor';

const DASH = '—';

/** "HH:MM:SS" for the coordinator's last watch-list tick; DASH when unknown
 *  — an absent/never-ticked heartbeat must read as honestly missing, not as
 *  a fabricated "just checked". */
function formatLastCheckTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** "mm:ss" countdown, floored at 0 — never a negative or fractional display. */
function formatCountdownMMSS(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const mm = Math.floor(totalSeconds / 60);
  const ss = totalSeconds % 60;
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
}

interface CoordinatorConfig {
  check_interval_minutes: number;
  max_concurrent_discussions: number;
}

export function AgentChatDashboard() {
  const [status, setStatus] = useState<AgentChatCoordinatorStatus | null>(null);
  const [activeDiscussions, setActiveDiscussions] = useState<AgentChatActiveDiscussion[]>([]);
  const [recentSessions, setRecentSessions] = useState<AgentChatSessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [config, setConfig] = useState<CoordinatorConfig>({
    check_interval_minutes: 5,
    max_concurrent_discussions: 3,
  });

  // B3: in-page manual debate — this page previously had no way to say "debate
  // this ticker now"; the only caller of startAgentChatDiscussion was ⌘K
  // (CommandPalette.tsx). Reuses the exact same client call/request shape.
  const [debateTicker, setDebateTicker] = useState('');
  const [debateLoading, setDebateLoading] = useState(false);
  const [debateError, setDebateError] = useState<string | null>(null);

  // Selection lives in the URL (`?session=<id>`), not local-only state: this
  // is what makes DebatePanel's session-id deep link (B1) actually land on
  // the right session, and it's the single source of truth for "what's
  // selected" — no separate state to fall out of sync.
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSessionId = searchParams.get('session');
  const selectSession = useCallback(
    (sessionId: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (sessionId) {
            next.set('session', sessionId);
          } else {
            next.delete('session');
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // Tick every 1s while the coordinator is running with a known last-check
  // timestamp, so the "다음 점검까지" countdown re-renders (same pattern as
  // OrderTicketRail's auto-approve countdown: derive remaining time from
  // Date.now() vs. an ISO timestamp on each tick).
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    if (!status?.is_running || !status?.last_check_at) return;
    const id = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, [status?.is_running, status?.last_check_at]);

  // Loop-liveness (reuses the same pure classifier the shell's
  // LoopLivenessChip uses — see hooks/useLoopLiveness): `is_running` alone
  // can't tell a healthy 5-minute loop apart from one whose job crashed but
  // left the flag set. A "stale" reading here must show as a warning, not a
  // confident (and wrong) countdown.
  const liveness = computeLoopLiveness(status, nowTick);
  const lastCheckLabel = formatLastCheckTime(status?.last_check_at);
  const nextCheckLabel = (() => {
    if (!status?.is_running) return null;
    if (!status.last_check_at) return '첫 점검 대기 중';
    const intervalMs = (status.check_interval_minutes || config.check_interval_minutes) * 60_000;
    const nextAt = new Date(status.last_check_at).getTime() + intervalMs;
    const remaining = nextAt - nowTick;
    return remaining > 0 ? formatCountdownMMSS(remaining) : '점검 중…';
  })();

  // B3 — Active Discussions used to vanish entirely at 0 (no explanation of
  // why / when the next check runs). This is the honest replacement text
  // for that state, reusing the same last_check/interval math as the
  // countdown above (not a separate, possibly-inconsistent computation).
  const activeDiscussionsEmptyText = (() => {
    if (!status?.is_running) return '자동 모니터링이 꺼져 있습니다 · 조건 충족 종목 없음';
    if (liveness === 'stale') return '점검 루프 응답 없음 — 다음 점검 시각 불명 · 조건 충족 종목 없음';
    return `다음 점검까지 ${nextCheckLabel} · 조건 충족 종목 없음`;
  })();

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [statusData, activeData, sessionsData] = await Promise.all([
        getAgentChatStatus().catch(() => null),
        getAgentChatActiveDiscussions().catch(() => ({ discussions: [], count: 0 })),
        getAgentChatSessions({ limit: 10 }).catch(() => ({ sessions: [], count: 0 })),
      ]);

      if (statusData) {
        setStatus(statusData);
        setConfig({
          check_interval_minutes: statusData.check_interval_minutes,
          max_concurrent_discussions: statusData.max_concurrent_discussions,
        });
      }
      setActiveDiscussions(activeData.discussions);
      setRecentSessions(sessionsData.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleStart = async () => {
    try {
      setActionLoading(true);
      setError(null);
      await startAgentChat(config);
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start coordinator');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionLoading(true);
      setError(null);
      await stopAgentChat();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop coordinator');
    } finally {
      setActionLoading(false);
    }
  };

  // B3 — "debate this ticker right now", distinct from `handleStart` above
  // (which only arms the 5-minute watch-list scheduler). Also used as the
  // fallback action for PositionMonitor's "Discussion Required" event badge
  // when no existing/active session matches that ticker — so the badge is
  // never a dead end, it always leads somewhere real.
  const handleStartDebate = useCallback(
    async (ticker: string, stockName?: string) => {
      const trimmed = ticker.trim();
      if (!trimmed) {
        setDebateError('종목코드를 입력하세요');
        return;
      }
      try {
        setDebateLoading(true);
        setDebateError(null);
        const result = await startAgentChatDiscussion({
          ticker: trimmed,
          stock_name: stockName?.trim() || trimmed,
        });
        setDebateTicker('');
        await fetchData();
        selectSession(result.session_id);
      } catch (err) {
        setDebateError(err instanceof Error ? err.message : '토론 시작 실패');
      } finally {
        setDebateLoading(false);
      }
    },
    [fetchData, selectSession],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <MessageSquare className="w-6 h-6 text-accent" />
          <h2 className="text-xl font-semibold text-ink">Agent Group Chat</h2>
        </div>
        <button
          onClick={fetchData}
          className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
        >
          <RefreshCw className="w-5 h-5" />
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-down/10 border border-down/30 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-down" />
          <span className="text-down">{error}</span>
        </div>
      )}

      {/* Status Card */}
      <div className="bg-card rounded border border-hairline p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <div
              className={`w-3 h-3 rounded-full ${
                status?.is_running ? 'bg-accent animate-pulse' : 'bg-muted'
              }`}
            />
            <span className="text-lg font-medium text-ink">
              Coordinator {status?.is_running ? 'Running' : 'Stopped'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowConfig(!showConfig)}
              className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
            >
              <Settings className="w-5 h-5" />
            </button>
            {status?.is_running ? (
              <button
                onClick={handleStop}
                disabled={actionLoading}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-ink rounded-lg" // color-ok: destructive action
              >
                {actionLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                자동 모니터링 중지
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={actionLoading}
                className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-canvas rounded-lg"
              >
                {actionLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                자동 모니터링 시작 ({config.check_interval_minutes}분 주기)
              </button>
            )}
          </div>
        </div>

        {/* Loop liveness (P1-3 last_check_at, rendered here for the first
            time — previously only the shell's LoopLivenessChip consumed it).
            A stale/absent heartbeat must read as honest, not as a confident
            "just checked" or a fake countdown. */}
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-6 text-xs text-muted"
          data-testid="coordinator-heartbeat"
        >
          <span>
            마지막 점검 <span className="text-ink tabular-nums">{lastCheckLabel}</span>
          </span>
          {status?.is_running && liveness === 'stale' && (
            <span className="text-warn">루프 응답 지연 — 예정된 점검을 놓쳤을 수 있습니다</span>
          )}
          {status?.is_running && liveness !== 'stale' && nextCheckLabel && (
            <span>
              다음 점검까지 <span className="text-ink tabular-nums">{nextCheckLabel}</span>
            </span>
          )}
        </div>

        {/* Config Panel */}
        {showConfig && (
          <div className="mb-6 p-4 bg-elevated rounded-lg space-y-4">
            <h4 className="text-sm font-medium text-ink">Configuration</h4>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-muted mb-1">
                  Check Interval (minutes)
                </label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={config.check_interval_minutes}
                  onChange={(e) =>
                    setConfig({ ...config, check_interval_minutes: parseInt(e.target.value) || 5 })
                  }
                  className="w-full px-3 py-2 bg-card border border-hairline rounded-lg text-ink text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">
                  Max Concurrent Discussions
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={config.max_concurrent_discussions}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      max_concurrent_discussions: parseInt(e.target.value) || 3,
                    })
                  }
                  className="w-full px-3 py-2 bg-card border border-hairline rounded-lg text-ink text-sm"
                />
              </div>
            </div>
          </div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-elevated rounded-lg p-4 text-center">
            <Users className="w-6 h-6 text-accent mx-auto mb-2" />
            <div className="text-2xl font-bold text-ink tabular-nums">{status?.active_discussions || 0}</div>
            <div className="text-xs text-muted">Active Discussions</div>
          </div>
          <div className="bg-elevated rounded-lg p-4 text-center">
            <TrendingUp className="w-6 h-6 text-accent mx-auto mb-2" />
            <div className="text-2xl font-bold text-ink tabular-nums">{status?.total_sessions || 0}</div>
            <div className="text-xs text-muted">Total Sessions</div>
          </div>
          <div className="bg-elevated rounded-lg p-4 text-center">
            <Clock className="w-6 h-6 text-accent mx-auto mb-2" />
            <div className="text-2xl font-bold text-ink tabular-nums">
              {status?.check_interval_minutes || 5}m
            </div>
            <div className="text-xs text-muted">Check Interval</div>
          </div>
        </div>
      </div>

      {/* Manual debate (B3) — this page previously had no way to say "debate
          this ticker now"; that only existed in ⌘K (CommandPalette.tsx).
          Kept visible in both browsing and detail views since "start a
          debate for some other ticker" is a valid action regardless of
          what's currently on screen. */}
      <div className="bg-card rounded border border-hairline p-6">
        <h3 className="text-lg font-medium text-ink mb-3 flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-accent" />
          지금 토론 시작
        </h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleStartDebate(debateTicker);
          }}
          className="flex items-center gap-3"
        >
          <input
            type="text"
            value={debateTicker}
            onChange={(e) => setDebateTicker(e.target.value)}
            placeholder="종목코드 (예: 005930)"
            aria-label="토론할 종목코드"
            disabled={debateLoading}
            className="flex-1 px-3 py-2 bg-elevated border border-hairline rounded-lg text-ink text-sm placeholder:text-dim disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={debateLoading || !debateTicker.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-canvas rounded-lg whitespace-nowrap"
          >
            {debateLoading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <MessageSquare className="w-4 h-4" />
            )}
            토론 시작
          </button>
        </form>
        {debateError && <p className="text-sm text-down mt-2">{debateError}</p>}
        <p className="text-xs text-muted mt-2">
          특정 종목을 지금 바로 4-애널리스트 토론에 부칩니다 — 5분 주기 자동 모니터링과는 별개입니다.
        </p>
      </div>

      {/* Active Discussions — hidden while the detail pane is open (the
          session list to the left already shows this session's card; the
          detail pane is where attention belongs). At 0 this used to vanish
          with no explanation; now it stays and says why (next-check
          countdown / loop state) instead of just disappearing. */}
      {!selectedSessionId && (
        <div className="bg-card rounded border border-hairline p-6" data-testid="active-discussions">
          <h3 className="text-lg font-medium text-ink mb-4 flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                activeDiscussions.length > 0 ? 'bg-accent animate-pulse' : 'bg-muted'
              }`}
            />
            Active Discussions
          </h3>
          {activeDiscussions.length > 0 ? (
            <div className="space-y-3">
              {activeDiscussions.map((discussion) => (
                <div
                  key={discussion.session_id}
                  className="flex items-center justify-between p-4 bg-elevated rounded-lg cursor-pointer hover:bg-hairline"
                  onClick={() => selectSession(discussion.session_id)}
                >
                  <div>
                    <div className="text-ink font-medium">
                      {discussion.stock_name} ({discussion.ticker})
                    </div>
                    <div className="text-sm text-muted">
                      Status: {discussion.status}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-1 text-xs bg-accent/20 text-accent rounded">
                      In Progress
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">{activeDiscussionsEmptyText}</p>
          )}
        </div>
      )}

      {/* Master-detail (R5-P2-UX B2): the session list ("master") never gets
          replaced — it just narrows to make room for the detail pane once a
          session is selected. Browsing (no selection): list 2/3 + Position
          Monitor 1/3, same as before. Viewing a session: list 1/3 (still
          visible + clickable — switching sessions doesn't require going
          "back" first) + ChatSessionViewer 2/3. */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className={selectedSessionId ? 'xl:col-span-1' : 'xl:col-span-2'}>
          <ChatSessionList
            sessions={recentSessions}
            onSelectSession={selectSession}
            selectedSessionId={selectedSessionId}
          />
        </div>

        <div className={selectedSessionId ? 'xl:col-span-2' : ''}>
          {selectedSessionId ? (
            <ChatSessionViewer
              sessionId={selectedSessionId}
              onClose={() => selectSession(null)}
            />
          ) : (
            <PositionMonitor
              activeDiscussions={activeDiscussions}
              sessions={recentSessions}
              onOpenSession={selectSession}
              onStartDebate={handleStartDebate}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentChatDashboard;
