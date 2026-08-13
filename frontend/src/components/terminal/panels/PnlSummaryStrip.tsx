/**
 * PnlSummaryStrip — Positions 페이지(`/positions`)의 기간 손익 요약.
 *
 * **기간 버킷만 보여준다.** 미실현손익은 바로 아래 `KiwoomPositionPanel`의
 * 「보유 종목」 카드가 이미 "총 손익"으로 표시하므로 여기서 또 그리면 같은
 * 숫자가 한 화면에 두 번 나온다. 덕분에 이 컴포넌트는 브로커 보유 조회를
 * 하지 않고 `/trading/pnl-summary` 하나만 폴링한다(Kiwoom 초당 약 1.4요청 제한).
 *
 * 강등은 칸 단위다: 실현손익 섹션이 죽어도 평가금 수익률은 계속 보여주고,
 * 그 반대도 같다. 0이나 가짜 값으로 위장하지 않는다(/operations·/performance와
 * 동일한 규약).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getPnlSummary } from '@/api/client';
import type { PnlSummaryResponse } from '@/types';
import { pnlColor } from '@/utils/pnl';
import { DASH, fmtPct } from './shared';

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

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      {children}
    </div>
  );
}

export function PnlSummaryStrip() {
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
  const errors = data?.errors ?? {};

  return (
    // 4칸 고정 그리드다. 이전의 flex-wrap은 좁은 폭에서 마지막 칸만 다음 줄로
    // 밀려 라벨과 값이 어긋나 보였다 — 좁아지면 2×2로 접히게 한다.
    <div className="mb-2 grid grid-cols-2 sm:grid-cols-4 divide-x divide-border border border-border text-[12px] tabular-nums">
      {BUCKETS.map(({ key, label }) => {
        const r = ret?.[key];
        const amount = realized?.[key];
        const retFailed = ret === null && settled;
        const realizedFailed = realized === null && settled;
        return (
          <Cell key={key} label={label}>
            {r ? (
              <span className={pnlColor(r.pct)}>{fmtPct(r.pct)}</span>
            ) : retFailed ? (
              // PerformancePanel의 Kpi 관례를 따른다: 실패는 회색이 아니라
              // text-down이고, title로 사유를 보여준다(errors[section]).
              <span className="text-down" title={errors.equity_return}>{FAIL}</span>
            ) : (
              <span className="text-muted">{DASH}</span>
            )}
            {amount === undefined ? (
              realizedFailed ? (
                <span className="text-[10px] text-down" title={errors.realized}>{FAIL}</span>
              ) : (
                <span className="text-[10px] text-muted">{DASH}</span>
              )
            ) : (
              <span
                className={`text-[10px] ${pnlColor(amount)}`}
                title={key === 'total' ? errors.realized_total_scope : undefined}
              >
                {fmtSigned(amount)}
              </span>
            )}
            {r && (
              // 이 %가 어느 스냅샷(거래일) 기준인지 — 장중에는 항상 전일
              // 이전 종가라 오늘 값처럼 보이지 않게 명시한다.
              <span className="text-[9px] text-dim">{r.trade_date}</span>
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
