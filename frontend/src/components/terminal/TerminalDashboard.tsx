/**
 * TerminalDashboard — the dense "command center" dashboard grid.
 *
 * Renders the target information architecture (watchlist blotter, chart,
 * portfolio strip, positions blotter, agent debate lane, scanner). Data wires
 * to the store as it becomes available; until the backend feeds it, panels show
 * their intended column structure with an honest "awaiting data" state (no
 * fabricated numbers).
 */
import { useStore } from '@/store';

function Panel({
  title, right, children, className = '', accent = false,
}: {
  title: string; right?: React.ReactNode; children: React.ReactNode; className?: string; accent?: boolean;
}) {
  return (
    <div className={`flex flex-col min-h-0 border-b border-hairline ${className}`}>
      <div className="flex items-center gap-2 h-6 px-2.5 bg-card border-b border-hairline text-[10px] uppercase tracking-[0.11em] text-muted flex-none">
        <span className={`w-1.5 h-1.5 rounded-full ${accent ? 'bg-accent' : 'bg-up'}`} />
        {title}
        {right && <span className="ml-auto text-dim normal-case tracking-normal">{right}</span>}
      </div>
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  );
}

function Awaiting({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full py-8 text-[11px] text-dim">
      <span className="w-1.5 h-1.5 rounded-full bg-dim mr-2" />{label}
    </div>
  );
}

const THEAD = 'sticky top-0 bg-card text-right font-semibold text-muted text-[10px] tracking-wide px-2.5 py-1.5 border-b border-hairline whitespace-nowrap';

export function TerminalDashboard() {
  const activeMarket = useStore((s) => s.activeMarket);
  const marketLabel = activeMarket === 'kiwoom' ? 'KRX' : activeMarket === 'coin' ? 'UPBIT' : 'US';

  return (
    <div className="h-full grid grid-cols-1 xl:grid-cols-[1.35fr_1.05fr_1.15fr] min-h-0 font-mono">
      {/* col 1: watchlist + chart */}
      <div className="flex flex-col min-h-0 border-r border-hairline">
        <Panel title={`Watchlist · ${marketLabel}`} right="rule-signal" className="flex-1">
          <table className="w-full text-[12px] tabular-nums">
            <thead>
              <tr>
                <th className={`${THEAD} text-left`}>SYM</th>
                <th className={THEAD}>LAST</th><th className={THEAD}>CHG%</th>
                <th className={THEAD}>VOL</th><th className={THEAD}>RSI</th><th className={THEAD}>SIGNAL</th>
              </tr>
            </thead>
            <tbody><tr><td colSpan={6}><Awaiting label="관심종목 데이터 대기 · 백엔드 연결 시 표시" /></td></tr></tbody>
          </table>
        </Panel>
        <Panel title="Chart · 종목 선택" right="1D" className="flex-none h-40">
          <Awaiting label="차트 대기 · 종목 선택 시 표시" />
        </Panel>
      </div>

      {/* col 2: portfolio + positions + scanner */}
      <div className="flex flex-col min-h-0 border-r border-hairline">
        <Panel title="Portfolio" className="flex-none">
          <div className="grid grid-cols-4 tabular-nums">
            {[
              ['총 자산', '—'], ['평가손익', '—'], ['보유', '0'], ['가용', '—'],
            ].map(([k, v]) => (
              <div key={k} className="px-2.5 py-2 border-r border-hairline last:border-r-0">
                <div className="text-[10px] uppercase tracking-wide text-muted">{k}</div>
                <div className="text-[14px] font-bold mt-0.5">{v}</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Positions" right="unreal. —" className="flex-1">
          <table className="w-full text-[12px] tabular-nums">
            <thead>
              <tr>
                <th className={`${THEAD} text-left`}>SYM</th>
                <th className={THEAD}>QTY</th><th className={THEAD}>ENTRY</th><th className={THEAD}>CUR</th>
                <th className={THEAD}>P&amp;L</th><th className={THEAD}>%</th><th className={THEAD}>STOP</th><th className={THEAD}>TAKE</th>
              </tr>
            </thead>
            <tbody><tr><td colSpan={8}><Awaiting label="보유 포지션 없음 · 백엔드 연결 시 표시" /></td></tr></tbody>
          </table>
        </Panel>
        <Panel title="Scanner · KOSPI+KOSDAQ" accent className="flex-none">
          <div className="flex items-center gap-3 px-2.5 py-2 text-[11px]">
            <span className="text-muted">idle</span>
            <div className="flex-1 h-1.5 rounded bg-elevated overflow-hidden"><i className="block h-full w-0 bg-accent" /></div>
            <span className="text-dim tabular-nums">0 / 2,100</span>
          </div>
        </Panel>
      </div>

      {/* col 3: agent lane (the distinctive surface) */}
      <div className="flex flex-col min-h-0">
        <Panel title="Agent debate" right="round —" className="flex-none">
          <table className="w-full text-[12px] tabular-nums">
            <tbody className="text-muted">
              {['TECHNICAL', 'FUNDAMENTAL', 'SENTIMENT', 'RISK'].map((a) => (
                <tr key={a} className="border-b border-hairline/60">
                  <td className="text-left px-2.5 h-6">
                    <span className="inline-flex items-center gap-2 font-semibold">
                      <span className="w-2 h-2 rounded-sm bg-dim" />{a}
                    </span>
                  </td>
                  <td className="text-right px-2.5 text-dim">—</td>
                  <td className="text-right px-2.5 text-dim">—</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center gap-2.5 px-2.5 py-2 border-t border-hairline">
            <span className="text-[10px] text-muted">CONSENSUS</span>
            <span className="text-[16px] font-bold text-dim tabular-nums">—</span>
            <div className="flex-1 h-1.5 rounded bg-elevated relative">
              <span className="absolute top-[-3px] bottom-[-3px] left-[75%] w-0.5 bg-warn" />
            </div>
            <span className="text-[11px] text-muted">gate 75%</span>
          </div>
        </Panel>
        <Panel title="Reasoning · tail -f" className="flex-1">
          <Awaiting label="활성 토론 없음 · :analyze &lt;종목&gt; 실행 시 스트리밍" />
        </Panel>
      </div>
    </div>
  );
}
