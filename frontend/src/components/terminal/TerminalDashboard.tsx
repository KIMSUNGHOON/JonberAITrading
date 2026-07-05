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
import { WatchlistPanel } from './panels/WatchlistPanel';
import { PositionsPanel } from './panels/PositionsPanel';
import { PortfolioPanel } from './panels/PortfolioPanel';
import { ScannerPanel } from './panels/ScannerPanel';
import { DebatePanel } from './panels/DebatePanel';
import { ReasoningPanel } from './panels/ReasoningPanel';
import { ChartTile } from './panels/ChartTile';

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

function renderBody(id: PanelId) {
  switch (id) {
    case 'watchlist': return <WatchlistPanel />;
    case 'chart': return <ChartTile />;
    case 'portfolio': return <PortfolioPanel />;
    case 'positions': return <PositionsPanel />;
    case 'scanner': return <ScannerPanel />;
    case 'debate': return <DebatePanel />;
    case 'reasoning': return <ReasoningPanel />;
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
