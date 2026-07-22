/**
 * US AI cross-market signal status card (observability T2).
 *
 * Read-only: displays the overnight US AI value-chain (SMH/MU/NVDA)
 * performance signal + the curated KR AI value-chain ticker list that the
 * signal nudges. Never fabricates a number -- DASH when a field is null.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Globe } from 'lucide-react';
import { getUsSignal } from '@/api/client';
import type { UsSignalResponse } from '@/types';
import { fmtPct, DASH } from './shared';

const POLL_MS = 45_000;

function useUsSignal() {
  const [data, setData] = useState<UsSignalResponse | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const alive = useRef(true);
  const refetch = useCallback(async () => {
    try {
      const res = await getUsSignal();
      if (!alive.current) return;
      setData(res);
      setState('ready');
    } catch {
      if (!alive.current) return;
      setState('error');
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    refetch();
    const id = setInterval(refetch, POLL_MS);
    return () => { alive.current = false; clearInterval(id); };
  }, [refetch]);
  return { data, state };
}

function fmtSignal(v: number | null): string {
  if (v == null) return DASH;
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}`;
}

function Dot({ tone }: { tone: 'on' | 'warn' | 'off' }) {
  const c = tone === 'on' ? 'bg-up' : tone === 'warn' ? 'bg-warn' : 'bg-dim';
  return <span className={`inline-block w-2 h-2 rounded-full ${c}`} />;
}

export default function UsSignalCard() {
  const { data, state } = useUsSignal();

  const enabled = data?.enabled ?? false;
  const fresh = enabled && !!data?.as_of;
  const tone: 'on' | 'warn' | 'off' = !enabled ? 'off' : fresh ? 'on' : 'warn';

  return (
    <div className="bg-card border border-hairline rounded p-4">
      <div className="flex items-center gap-2 mb-3">
        <Globe size={15} className="text-muted" />
        <span className="text-sm font-medium text-ink">US AI 크로스마켓 신호</span>
        <Dot tone={tone} />
      </div>

      {state === 'loading' && <div className="text-sm text-muted">상태 확인 중…</div>}

      {state === 'error' && !data && (
        <div className="text-sm text-muted mb-3">신호 상태 조회 실패 — 재시도 중…</div>
      )}

      {state === 'ready' && !enabled && (
        <div className="text-sm text-muted mb-3">US 신호 비활성 (US_SIGNAL_ENABLED off)</div>
      )}

      {state === 'ready' && enabled && !fresh && (
        <div className="text-sm text-muted mb-3">당일 신호 대기 중 (개장 전 갱신 예정)</div>
      )}

      {enabled && fresh && (
        <>
          <div className="text-sm text-ink mb-2">
            간밤 미 AI 반도체{' '}
            <span className={data!.signal_pct! >= 0 ? 'text-up' : 'text-down'}>
              {fmtPct(data!.signal_pct)}
            </span>
            <span className="text-dim"> → 신호강도 {fmtSignal(data!.signal)}</span>
          </div>
          <div className="text-[12px] text-muted mb-2">
            {data!.components.map((c, i) => (
              <span key={c.ticker}>
                {i > 0 && ' · '}
                {c.ticker} {Math.round(c.weight * 100)}%{' '}
                <span className={c.change_pct == null ? 'text-dim' : c.change_pct >= 0 ? 'text-up' : 'text-down'}>
                  {fmtPct(c.change_pct)}
                </span>
              </span>
            ))}
          </div>
        </>
      )}

      {/* 큐레이션은 상태 무관 항상 */}
      {data?.curation?.length ? (
        <div className="text-[11px] text-dim leading-relaxed">
          적용 대상 ({data.curation.length}): {data.curation.map((x) => x.name).join(' · ')}
        </div>
      ) : null}

      {enabled && fresh && (
        <p className="mt-2 text-[11px] text-dim leading-relaxed">
          간밤 미 반도체 성과를 밸류체인 종목 토론·발굴에 반영(넛지) · as_of {data!.as_of}
        </p>
      )}
    </div>
  );
}
