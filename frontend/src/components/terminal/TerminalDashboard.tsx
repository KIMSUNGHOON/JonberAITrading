/**
 * TerminalDashboard — a tiling command-center (Bloomberg-style).
 *
 * Panels are react-mosaic tiles: drag a panel's title bar to rearrange, drag the
 * splitters to resize. The layout persists to localStorage. Each tile is a
 * self-contained component under ./panels that wires to the store / REST as data
 * becomes available and keeps an honest "awaiting data" state otherwise (no
 * fabricated numbers).
 */
import { useState } from 'react';
import { Mosaic, MosaicWindow, type MosaicNode } from 'react-mosaic-component';
import 'react-mosaic-component/react-mosaic-component.css';
import { OperationsPanel } from './panels/OperationsPanel';
import { WatchlistPanel } from './panels/WatchlistPanel';
import { PositionsPanel } from './panels/PositionsPanel';
import { PortfolioPanel } from './panels/PortfolioPanel';
import { PerformancePanel } from './panels/PerformancePanel';
import { ScannerPanel } from './panels/ScannerPanel';
import { DebatePanel } from './panels/DebatePanel';
import { ChartTile } from './panels/ChartTile';

type PanelId =
  | 'operations' | 'watchlist' | 'chart' | 'portfolio'
  | 'positions' | 'scanner' | 'debate' | 'performance';

const TITLES: Record<PanelId, string> = {
  operations: 'Operations · 운용 파이프라인',
  watchlist: 'Scratchpad',        // ← 서버 워치리스트(Watchlist)와 구분 (스펙 §7, P2-T3)
  chart: 'Chart',
  portfolio: 'Portfolio',
  positions: 'Positions',
  scanner: 'Scanner · KOSPI+KOSDAQ',
  debate: 'Agent debate',
  performance: 'Performance · 실현손익/수익률',
};

// 레이아웃 v4 — PERFORMANCE 타일 추가(TUX4: 실현손익·누적수익률·승률·일별곡선;
// v3 저장 레이아웃은 새 'performance' id를 모르므로 키를 새로 부여)
const STORAGE_KEY = 'jonber.dashboard.layout.v4';

const DEFAULT_LAYOUT: MosaicNode<PanelId> = {
  type: 'split',
  direction: 'column',
  splitPercentages: [34, 66],
  children: [
    'operations',
    {
      type: 'split', direction: 'row', splitPercentages: [40, 30, 30],
      children: [
        { type: 'split', direction: 'column', splitPercentages: [64, 36], children: ['watchlist', 'chart'] },
        {
          type: 'split', direction: 'column', splitPercentages: [16, 46, 16, 22],
          children: ['portfolio', 'performance', 'positions', 'scanner'],
        },
        'debate',
      ],
    },
  ],
};

function renderBody(id: PanelId) {
  switch (id) {
    case 'operations': return <OperationsPanel />;
    case 'watchlist': return <WatchlistPanel />;
    case 'chart': return <ChartTile />;
    case 'portfolio': return <PortfolioPanel />;
    case 'positions': return <PositionsPanel />;
    case 'scanner': return <ScannerPanel />;
    case 'debate': return <DebatePanel />;
    case 'performance': return <PerformancePanel />;
  }
}

export function TerminalDashboard() {
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
            <div className="h-full overflow-auto bg-card">{renderBody(id)}</div>
          </MosaicWindow>
        )}
      />
    </div>
  );
}
