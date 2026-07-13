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
import { ScannerPanel } from './panels/ScannerPanel';
import { DebatePanel } from './panels/DebatePanel';
import { ChartTile } from './panels/ChartTile';

type PanelId =
  | 'operations' | 'watchlist' | 'chart' | 'portfolio'
  | 'positions' | 'scanner' | 'debate';

const TITLES: Record<PanelId, string> = {
  operations: 'Operations · 운용 파이프라인',
  watchlist: 'Basket',            // ← 서버 워치리스트와 구분 (스펙 §7)
  chart: 'Chart',
  portfolio: 'Portfolio',
  positions: 'Positions',
  scanner: 'Scanner · KOSPI+KOSDAQ',
  debate: 'Agent debate',
};

// 레이아웃 v3 — REASONING 타일 제거(perf: 스트리밍 델타가 uncapped 로그를 강제
// 스크롤과 함께 매 delta마다 전체 재렌더 — 배치 플러시로도 tile 자체는 불필요해
// 제거; v2 저장 레이아웃은 삭제된 'reasoning' id를 참조하므로 키를 새로 부여)
const STORAGE_KEY = 'jonber.dashboard.layout.v3';

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
        { type: 'split', direction: 'column', splitPercentages: [16, 62, 22], children: ['portfolio', 'positions', 'scanner'] },
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
