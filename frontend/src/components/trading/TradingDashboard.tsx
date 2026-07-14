/**
 * 자율 운용 관제 (Autonomous Operations Control) — /trading
 *
 * R5-P2 재편: 이전 버전은 초기 모델의 잔재였다 — 장식용 Agent Workflow 그래프
 * (갱신 경로가 데드 코드), 어떤 매매 경로도 읽지 않는 전략 프리셋 위젯,
 * 코디네이터 인메모리 포트폴리오(브로커 계좌와 다른 진실), R3 자율 시스템과의
 * 완전한 단절. 이 화면은 실제 자율 운용의 세 스위치와 안전장치를 한곳에 모은다:
 *
 *   1. 트레이딩 모드 (HITL | AUTONOMOUS, 마켓별) — R3 게이트가 매 결정마다 읽음
 *   2. 결정 계층 (Agent Coordinator) — 워치리스트 감시 → 토론 → 합의 → 결정
 *   3. 실행 계층 (Execution Coordinator) — 큐 → 게이트 재확인 → 브로커 주문
 *
 * 전략 위젯은 실제 배선(R5-P3) 전까지 UI에서 내렸다 — 통제감 착각 제거.
 *
 * R5-P2-UX B1: "결정 계층" 카드는 더 이상 Start/Stop을 직접 호출하지 않는다.
 * 이 코디네이터 on/off는 /agent-chat Status Card, /trading(여기), 대시보드
 * DebatePanel 세 곳에서 각각 다른 라벨로 켤 수 있었다 — 사용자가 "같은
 * 스위치"라는 걸 알 수 없는 3중 컨트롤이었다. SSOT는 /agent-chat으로 고정하고,
 * 여기서는 읽기전용 상태칩 + 딥링크만 제공한다("실행 계층"은 별개 스위치라
 * 그대로 유지).
 *
 * P2 funnel-consolidation Task 8b: the "3행: 운용 데이터" row (WatchListWidget/
 * TradeQueueWidget) has been removed — every action those two widgets
 * offered (convert-to-queue, remove-from-watch, re-analyze, cancel-queued,
 * manual queue-process) now lives in the dashboard funnel's WATCHLIST/
 * PIPELINE sections (see OperationsPanel.tsx's WatchingColumn/
 * PendingBuyColumn + FunnelPanel.tsx), which poll the SAME `/operations`
 * source instead of running two more independent polls. This screen is now
 * purely the three control switches + safety gate summary.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bot,
  CircleDollarSign,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
} from 'lucide-react';

import {
  getAgentChatStatus,
  getTradingStatus,
  startTrading,
  stopTrading,
  pauseTrading,
  resumeTrading,
  apiClient,
} from '@/api/client';
import { useStore } from '@/store';
import { TradingModeSection } from '@/components/settings/TradingModeSection';
import type { AgentChatCoordinatorStatus } from '@/types';

/** HH:mm for the last coordinator watch-list tick; DASH when unknown. */
const DASH = '—';
function formatLastCheck(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

interface ExecutionStatus {
  mode: string;
  is_active: boolean;
  started_at: string | null;
  daily_trades: number;
  max_daily_trades: number;
}

interface RiskLimits {
  max_daily_loss_pct?: number;
  max_open_positions?: number;
  max_trade_notional_krw?: number;
}

function StatusDot({ on }: { on: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${on ? 'bg-up' : 'bg-dim'}`}
      aria-hidden
    />
  );
}

function CardHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-muted">{icon}</span>
      <h3 className="text-sm font-medium text-ink">{title}</h3>
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  disabled,
  tone = 'default',
  icon,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: 'default' | 'accent' | 'danger';
  icon?: React.ReactNode;
}) {
  const toneCls =
    tone === 'accent'
      ? 'bg-accent text-canvas hover:bg-accent/90'
      : tone === 'danger'
        ? 'border border-down/50 text-down hover:bg-down/10'
        : 'border border-hairline text-muted hover:text-ink hover:bg-elevated';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${toneCls}`}
    >
      {icon}
      {label}
    </button>
  );
}

export default function TradingDashboard() {
  const navigate = useNavigate();
  const masterEnabled = useStore((s) => s.autonomyMasterEnabled);
  const tradingModes = useStore((s) => s.tradingModes);

  const [error, setError] = useState<string | null>(null);
  const [execStatus, setExecStatus] = useState<ExecutionStatus | null>(null);
  const [brainStatus, setBrainStatus] = useState<AgentChatCoordinatorStatus | null>(null);
  const [riskLimits, setRiskLimits] = useState<RiskLimits | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const [exec, brain, risk] = await Promise.allSettled([
      getTradingStatus(),
      getAgentChatStatus(),
      apiClient.getTradingRiskParams(),
    ]);
    if (exec.status === 'fulfilled') setExecStatus(exec.value as ExecutionStatus);
    if (brain.status === 'fulfilled') setBrainStatus(brain.value);
    if (risk.status === 'fulfilled') setRiskLimits(risk.value as RiskLimits);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await fetchAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : '요청에 실패했습니다');
    } finally {
      setBusy(null);
    }
  };

  const autonomousMarkets = tradingModes
    ? (['kiwoom', 'coin'] as const).filter((m) => tradingModes[m] === 'autonomous')
    : [];
  const fullyArmed =
    masterEnabled && autonomousMarkets.length > 0 && brainStatus?.is_running && execStatus?.is_active;

  return (
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex-none flex items-center justify-between px-4 py-2.5 border-b border-hairline bg-card">
        <div>
          <h1 className="text-sm font-semibold text-ink">자율 운용 관제</h1>
          <p className="text-[11px] text-dim">
            모드 · 결정 계층 · 실행 계층 · 안전장치를 한곳에서 제어합니다
          </p>
        </div>
        <div className="flex items-center gap-3">
          {fullyArmed ? (
            <span className="px-2 py-0.5 rounded border border-accent/50 text-accent text-[11px] font-medium uppercase tracking-wide">
              Autonomous · Armed
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded border border-hairline text-dim text-[11px] uppercase tracking-wide">
              Standby
            </span>
          )}
          <button
            onClick={fetchAll}
            className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
            title="새로고침"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-3 px-3 py-2 rounded border border-down/40 bg-down/10 text-down text-sm">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-6xl mx-auto space-y-4">
          {/* 1행: 스위치 3개 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {/* 트레이딩 모드 (공용 섹션 재사용) */}
            <TradingModeSection onError={setError} />

            {/* 결정 계층 — 읽기전용 상태칩 + 딥링크 (B1: on/off SSOT=/agent-chat) */}
            <div className="bg-card border border-hairline rounded p-4">
              <CardHeader icon={<Bot size={15} />} title="결정 계층 · Agent Coordinator" />
              <div className="flex items-center gap-2 text-sm text-muted mb-1">
                <StatusDot on={!!brainStatus?.is_running} />
                {brainStatus == null
                  ? '상태 확인 중…'
                  : brainStatus.is_running
                    ? `가동 중 — 토론 ${brainStatus.active_discussions}건 · ${brainStatus.check_interval_minutes}분 주기`
                    : '정지 — 워치리스트 감시 없음'}
              </div>
              {brainStatus?.is_running && (
                <div className="text-[11px] text-dim mb-2">
                  마지막 점검 {formatLastCheck(brainStatus.last_check_at)}
                </div>
              )}
              <button
                type="button"
                onClick={() => navigate('/agent-chat')}
                className="mt-2 text-xs font-medium text-accent hover:underline"
              >
                /agent-chat에서 제어 →
              </button>
              <p className="mt-3 text-[11px] text-dim leading-relaxed">
                워치리스트 감시 → 에이전트 토론 → 합의(75%) → 결정. 손절/익절 감시
                (Position Monitor)도 함께 기동됩니다. 시작/정지는 /agent-chat에서
                제어합니다.
              </p>
            </div>

            {/* 실행 계층 */}
            <div className="bg-card border border-hairline rounded p-4">
              <CardHeader
                icon={<CircleDollarSign size={15} />}
                title="실행 계층 · Execution"
              />
              <div className="flex items-center gap-2 text-sm text-muted mb-3">
                <StatusDot on={!!execStatus?.is_active} />
                {execStatus == null
                  ? '상태 확인 중…'
                  : execStatus.is_active
                    ? `가동 중 (${execStatus.mode}) — 오늘 ${execStatus.daily_trades}/${execStatus.max_daily_trades}건`
                    : '정지 — 큐 처리 없음'}
              </div>
              <div className="flex gap-2 flex-wrap">
                {execStatus?.is_active ? (
                  <>
                    <ActionButton
                      label="Pause"
                      icon={<Pause size={12} />}
                      disabled={busy !== null}
                      onClick={() => act('exec', () => pauseTrading('Manual pause'))}
                    />
                    <ActionButton
                      label="Stop"
                      icon={<Square size={12} />}
                      tone="danger"
                      disabled={busy !== null}
                      onClick={() => act('exec', () => stopTrading())}
                    />
                  </>
                ) : (
                  <>
                    <ActionButton
                      label="Start"
                      icon={<Play size={12} />}
                      tone="accent"
                      disabled={busy !== null}
                      onClick={() => act('exec', () => startTrading())}
                    />
                    <ActionButton
                      label="Resume"
                      disabled={busy !== null}
                      onClick={() => act('exec', () => resumeTrading())}
                    />
                  </>
                )}
              </div>
              <p className="mt-3 text-[11px] text-dim leading-relaxed">
                승인된 거래의 큐 처리와 브로커 주문. 자율 거래는 실행 직전 게이트를
                다시 통과해야 합니다.
              </p>
            </div>
          </div>

          {/* 2행: 안전장치 */}
          <div className="bg-card border border-hairline rounded p-4">
            <CardHeader icon={<ShieldCheck size={15} />} title="안전장치 · Autonomy Gate" />
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
              <div>
                <div className="text-[11px] text-dim uppercase tracking-wide">마스터 게이트</div>
                <div className={masterEnabled ? 'text-up' : 'text-muted'}>
                  {masterEnabled ? 'ENABLED' : 'DISABLED (env)'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-dim uppercase tracking-wide">일일 손실 한도</div>
                <div className="text-ink tabular-nums">
                  {riskLimits?.max_daily_loss_pct != null
                    ? `${riskLimits.max_daily_loss_pct}% (브레이커)`
                    : '—'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-dim uppercase tracking-wide">최대 포지션</div>
                <div className="text-ink tabular-nums">
                  {riskLimits?.max_open_positions ?? '—'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-dim uppercase tracking-wide">거래당 상한</div>
                <div className="text-ink tabular-nums">
                  {riskLimits?.max_trade_notional_krw != null
                    ? `₩${riskLimits.max_trade_notional_krw.toLocaleString()}`
                    : '—'}
                </div>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-dim leading-relaxed">
              모든 자율 승인·실행은 게이트 체인(마스터 → 마켓 모드 → 페이퍼 →
              브레이커 → 포지션/금액 캡)을 통과해야 하며, 페이퍼 모드는 코드에
              고정되어 있습니다. 자율 승인 전 60초 유예 동안 홈 ORDER 레일에서
              거부할 수 있습니다.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
