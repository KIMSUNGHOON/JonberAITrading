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
import { FunnelPanel } from './panels/FunnelPanel';

export type PanelId =
  | 'operations' | 'watchlist' | 'chart' | 'portfolio'
  | 'positions' | 'scanner' | 'debate' | 'performance' | 'funnel';

export const TITLES: Record<PanelId, string> = {
  funnel: 'Funnel · 발견→감시→실행',
  operations: 'Operations · 운용 파이프라인',
  watchlist: 'Scratchpad',        // ← 서버 워치리스트(Watchlist)와 구분 (스펙 §7, P2-T3)
  chart: 'Chart',
  portfolio: 'Portfolio',
  positions: 'Positions',
  scanner: 'Scanner · KOSPI+KOSDAQ',
  debate: 'Agent debate',
  performance: 'Performance · 실현손익/수익률',
};

// 레이아웃 v5 — P2 퍼널 통합(P1-b): 신규 'funnel' 패널(발견→감시→실행 세로 조립)이
// 이전 'operations' 보드의 6개 컬럼 중 5개(분석중·승인대기·매수대기·보유·오늘체결)+
// '감시' 컬럼을 함께 흡수하므로, 같은 데이터를 두 타일에 중복 노출하지 않도록
// DEFAULT_LAYOUT에서 'operations'를 'funnel'로 교체한다. 'operations' PanelId/
// TITLES/renderBody 항목 자체는 계속 등록해 둔다(회귀 방지, 기존 테스트 유지).
// v4 저장 레이아웃은 새 'funnel' id를 모르므로 키를 새로 부여해 초기화한다.
export const STORAGE_KEY = 'jonber.dashboard.layout.v5';

export const DEFAULT_LAYOUT: MosaicNode<PanelId> = {
  type: 'split',
  direction: 'row',
  splitPercentages: [38, 62],
  children: [
    'funnel',
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

export function renderBody(id: PanelId) {
  switch (id) {
    case 'funnel': return <FunnelPanel />;
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
