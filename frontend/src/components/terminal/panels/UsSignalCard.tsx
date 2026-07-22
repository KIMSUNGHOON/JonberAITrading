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
import type { UsSignalResponse, UsSubSignal } from '@/types';
import { fmtPct, DASH } from './shared';

const POLL_MS = 45_000;

// v2: memory/accel/demand 서브신호 라벨. demand는 종목 매칭 없이 발굴 틸트 관측용.
const SUB_SIGNAL_LABELS: Record<'memory' | 'accel' | 'demand', string> = {
  memory: '메모리',
  accel: '가속기',
  demand: '수요',
};

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

/** memory/accel/demand 서브신호 한 줄: 라벨 + fmtPct(signal_pct) + 구성종목. null-safe --
 * sub이 없으면 호출부에서 아예 렌더하지 않음(허구 수치 금지). */
function SubSignalLine({ label, sub }: { label: string; sub: UsSubSignal }) {
  const pct = sub.signal_pct;
  const comps = sub.components ? Object.entries(sub.components) : [];
  return (
    <div className="text-[12px] text-muted mb-1">
      <span className="text-dim">{label}</span>{' '}
      <span className={pct == null ? 'text-dim' : pct >= 0 ? 'text-up' : 'text-down'}>
        {fmtPct(pct)}
      </span>
      {comps.length > 0 && (
        <span className="text-dim">
          {' ('}
          {comps.map(([ticker, v], i) => (
            <span key={ticker}>
              {i > 0 && ' · '}
              {ticker} {fmtPct(v)}
            </span>
          ))}
          {')'}
        </span>
      )}
    </div>
  );
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

          {/* v2: memory/accel/demand 서브신호 -- 없는 키는 조용히 생략(허구 수치 금지) */}
          {(Object.keys(SUB_SIGNAL_LABELS) as Array<keyof typeof SUB_SIGNAL_LABELS>).map((key) => {
            const sub = data?.sub_signals?.[key];
            if (!sub) return null;
            return <SubSignalLine key={key} label={SUB_SIGNAL_LABELS[key]} sub={sub} />;
          })}

          {data?.sub_signals?.demand?.signal != null && data.sub_signals.demand.signal > 0 && (
            <div className="text-[11px] text-up mb-2">→ 발굴 momentum 틸트 활성</div>
          )}
        </>
      )}

      {/* 큐레이션은 상태 무관 항상 */}
      {data?.curation?.length ? (
        <div className="text-[11px] text-dim leading-relaxed">
          적용 대상 ({data.curation.length}):{' '}
          {data.curation.map((x, i) => (
            <span key={x.ticker}>
              {i > 0 && ' · '}
              {x.name}
              {x.signal_type ? <span className="text-muted"> [{x.signal_type}]</span> : null}
            </span>
          ))}
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
