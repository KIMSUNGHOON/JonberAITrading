/**
 * TerminalDashboard — a tiling command-center (Bloomberg-style).
 *
 * Panels are react-mosaic tiles: drag a panel's title bar to rearrange, drag the
 * splitters to resize. The layout persists to localStorage. Data wires to the
 * store as it becomes available; until then panels show their intended column
 * structure with honest "awaiting data" states (no fabricated numbers).
 */
import { useState } from 'react';
import { Mosaic, MosaicWindow, type MosaicNode } from 'react-mosaic-component';
import 'react-mosaic-component/react-mosaic-component.css';
import { useStore } from '@/store';

type PanelId =
  | 'watchlist' | 'chart' | 'portfolio' | 'positions' | 'scanner' | 'debate' | 'reasoning';

const TITLES: Record<PanelId, string> = {
  watchlist: 'Watchlist',
  chart: 'Chart',
  portfolio: 'Portfolio',
  positions: 'Positions',
  scanner: 'Scanner · KOSPI+KOSDAQ',
  debate: 'Agent debate',
  reasoning: 'Reasoning · tail -f',
};

const STORAGE_KEY = 'jonber.dashboard.layout.v1';

const DEFAULT_LAYOUT: MosaicNode<PanelId> = {
  type: 'split',
  direction: 'row',
  splitPercentages: [40, 30, 30],
  children: [
    { type: 'split', direction: 'column', splitPercentages: [64, 36], children: ['watchlist', 'chart'] },
    { type: 'split', direction: 'column', splitPercentages: [16, 62, 22], children: ['portfolio', 'positions', 'scanner'] },
    { type: 'split', direction: 'column', splitPercentages: [46, 54], children: ['debate', 'reasoning'] },
  ],
};

function Awaiting({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full py-6 text-[11px] text-dim text-center px-4">
      <span className="w-1.5 h-1.5 rounded-full bg-dim mr-2 flex-none" />{label}
    </div>
  );
}

const TH = 'sticky top-0 bg-card text-right font-semibold text-muted text-[10px] tracking-wide px-2.5 py-1.5 border-b border-hairline whitespace-nowrap';

function WatchlistBody({ marketLabel }: { marketLabel: string }) {
  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>SYM · {marketLabel}</th>
          <th className={TH}>LAST</th><th className={TH}>CHG%</th>
          <th className={TH}>VOL</th><th className={TH}>RSI</th><th className={TH}>SIGNAL</th>
        </tr>
      </thead>
      <tbody><tr><td colSpan={6}><Awaiting label="관심종목 데이터 대기 · 백엔드 연결 시 표시" /></td></tr></tbody>
    </table>
  );
}

function PositionsBody() {
  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>SYM</th>
          <th className={TH}>QTY</th><th className={TH}>ENTRY</th><th className={TH}>CUR</th>
          <th className={TH}>P&amp;L</th><th className={TH}>%</th><th className={TH}>STOP</th><th className={TH}>TAKE</th>
        </tr>
      </thead>
      <tbody><tr><td colSpan={8}><Awaiting label="보유 포지션 없음 · 백엔드 연결 시 표시" /></td></tr></tbody>
    </table>
  );
}

function PortfolioBody() {
  return (
    <div className="grid grid-cols-4 tabular-nums h-full">
      {[['총 자산', '—'], ['평가손익', '—'], ['보유', '0'], ['가용', '—']].map(([k, v]) => (
        <div key={k} className="px-2.5 py-2 border-r border-hairline last:border-r-0">
          <div className="text-[10px] uppercase tracking-wide text-muted">{k}</div>
          <div className="text-[14px] font-bold mt-0.5">{v}</div>
        </div>
      ))}
    </div>
  );
}

function ScannerBody() {
  return (
    <div className="flex items-center gap-3 px-2.5 py-2 text-[11px] h-full">
      <span className="text-muted">idle</span>
      <div className="flex-1 h-1.5 rounded bg-elevated overflow-hidden"><i className="block h-full w-0 bg-accent" /></div>
      <span className="text-dim tabular-nums">0 / 2,100</span>
    </div>
  );
}

function DebateBody() {
  return (
    <div className="flex flex-col h-full">
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
      <div className="flex items-center gap-2.5 px-2.5 py-2 border-t border-hairline mt-auto">
        <span className="text-[10px] text-muted">CONSENSUS</span>
        <span className="text-[16px] font-bold text-dim tabular-nums">—</span>
        <div className="flex-1 h-1.5 rounded bg-elevated relative">
          <span className="absolute top-[-3px] bottom-[-3px] left-[75%] w-0.5 bg-warn" />
        </div>
        <span className="text-[11px] text-muted">gate 75%</span>
      </div>
    </div>
  );
}

function renderBody(id: PanelId, marketLabel: string) {
  switch (id) {
    case 'watchlist': return <WatchlistBody marketLabel={marketLabel} />;
    case 'chart': return <Awaiting label="차트 대기 · 종목 선택 시 표시" />;
    case 'portfolio': return <PortfolioBody />;
    case 'positions': return <PositionsBody />;
    case 'scanner': return <ScannerBody />;
    case 'debate': return <DebateBody />;
    case 'reasoning': return <Awaiting label="활성 토론 없음 · :analyze <종목> 실행 시 스트리밍" />;
  }
}

export function TerminalDashboard() {
  const activeMarket = useStore((s) => s.activeMarket);
  const marketLabel = activeMarket === 'kiwoom' ? 'KRX' : activeMarket === 'coin' ? 'UPBIT' : 'US';

  const [layout, setLayout] = useState<MosaicNode<PanelId> | null>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw) as MosaicNode<PanelId>;
    } catch { /* ignore */ }
    return DEFAULT_LAYOUT;
  });

  const handleChange = (node: MosaicNode<PanelId> | null) => {
    setLayout(node);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(node)); } catch { /* ignore */ }
  };

  return (
    <div className="relative h-full w-full">
      <Mosaic<PanelId>
        className="jonber-mosaic"
        value={layout}
        onChange={handleChange}
        renderTile={(id, path) => (
          <MosaicWindow<PanelId> path={path} title={TITLES[id]} toolbarControls={<span />}>
            <div className="h-full overflow-auto bg-card">{renderBody(id, marketLabel)}</div>
          </MosaicWindow>
        )}
      />
    </div>
  );
}
