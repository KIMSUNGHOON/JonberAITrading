/**
 * PnlSummaryStrip — Positions 탭 상단 손익 요약.
 *
 * 미실현손익은 부모(PositionsPanel)가 이미 폴링 중인 /operations 데이터에서
 * prop으로 받는다 — 같은 브로커 조회를 30초마다 한 번 더 하지 않기 위해서다
 * (Kiwoom 초당 약 1.4요청 제한). 기간 버킷만 이 컴포넌트가 스스로 폴링한다.
 *
 * 강등은 칸 단위다: 실현손익 섹션이 죽어도 평가금 수익률은 계속 보여주고,
 * 그 반대도 같다. 0이나 가짜 값으로 위장하지 않는다(/operations·/performance와
 * 동일한 규약).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getPnlSummary } from '@/api/client';
import type { PnlSummaryResponse } from '@/types';
import { pnlColor } from '@/utils/pnl';
import { DASH } from './shared';

const POLL_MS = 30_000;

const BUCKETS: { key: string; label: string }[] = [
  { key: 'day', label: '일' },
  { key: 'week', label: '주' },
  { key: 'month', label: '월' },
  { key: 'total', label: '누적' },
];

const FAIL = '조회 실패';

function fmtSigned(n: number): string {
  return `${n > 0 ? '+' : ''}${n.toLocaleString('ko-KR')}`;
}

function fmtSignedPct(n: number): string {
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      {children}
    </div>
  );
}

export function PnlSummaryStrip({
  unrealized,
  holdings,
}: {
  unrealized: number | null;
  holdings: number;
}) {
  const [data, setData] = useState<PnlSummaryResponse | null>(null);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading');
  const aliveRef = useRef(true);

  const refetch = useCallback(async () => {
    try {
      const res = await getPnlSummary();
      if (!aliveRef.current) return;
      setData(res);
      setPhase('ready');
    } catch {
      if (!aliveRef.current) return;
      setData(null);
      setPhase('failed');
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void refetch();
    const id = setInterval(() => void refetch(), POLL_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
  }, [refetch]);

  // 세 상태를 구분한다. 첫 응답 전(loading)에는 '조회 실패'가 아니라 '—'를
  // 보여준다 — 로딩을 실패로 위장하지 않기 위해서다. 섹션 자체가 null이면
  // '조회 실패', 섹션은 살아 있는데 그 버킷만 없으면 '—'다.
  const settled = phase !== 'loading';
  const ret = data?.equity_return ?? null;
  const realized = data?.realized ?? null;

  return (
    <div className="mb-2 flex flex-wrap items-stretch divide-x divide-border border border-border text-[12px] tabular-nums">
      <Cell label="미실현손익">
        {unrealized === null ? (
          <span className="text-muted">{FAIL}</span>
        ) : (
          <>
            <span className={pnlColor(unrealized)}>{fmtSigned(unrealized)}</span>
            <span className="text-[10px] text-muted">{holdings}종목</span>
          </>
        )}
      </Cell>

      {BUCKETS.map(({ key, label }) => {
        const r = ret?.[key];
        const amount = realized?.[key];
        return (
          <Cell key={key} label={label}>
            {r ? (
              <span className={pnlColor(r.pct)}>{fmtSignedPct(r.pct)}</span>
            ) : (
              <span className="text-muted">{ret === null && settled ? FAIL : DASH}</span>
            )}
            {amount === undefined ? (
              <span className="text-[10px] text-muted">
                {realized === null && settled ? FAIL : DASH}
              </span>
            ) : (
              <span className={`text-[10px] ${pnlColor(amount)}`}>{fmtSigned(amount)}</span>
            )}
            {r?.basis === 'base_asset' && (
              <span className="text-[10px] text-muted">기준자산</span>
            )}
          </Cell>
        );
      })}
    </div>
  );
}
