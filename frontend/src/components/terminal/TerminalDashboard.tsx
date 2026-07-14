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
import { PositionsPanel } from './panels/PositionsPanel';
import { PortfolioPanel } from './panels/PortfolioPanel';
import { PerformancePanel } from './panels/PerformancePanel';
import { DebatePanel } from './panels/DebatePanel';
import { ChartTile } from './panels/ChartTile';
import { FunnelPanel } from './panels/FunnelPanel';

export type PanelId =
  | 'chart' | 'portfolio' | 'positions' | 'debate' | 'performance' | 'funnel';

export const TITLES: Record<PanelId, string> = {
  funnel: 'Funnel · 발견→감시→실행',
  chart: 'Chart',
  portfolio: 'Portfolio',
  positions: 'Positions',
  debate: 'Agent debate',
  performance: 'Performance · 실현손익/수익률',
};

// 레이아웃 v6 — 대시보드 위젯 정리(dashboard-widget-cull, 2026-07-14 §B/§C):
// 8리프 → 6리프. 'scanner'는 DiscoverySection(funnel)의 완전 부분집합이라 제거,
// 'watchlist'(Scratchpad)는 고유 기능(행클릭 차트연동 + 30s 가격폴링)을
// DiscoverySection의 Scratchpad 구획으로 이관한 뒤 타일 자체를 제거, 'operations'
// 등록은 DEFAULT_LAYOUT에 배치된 적 없는 도달불가 죽은 등록이라 정리한다
// (OperationsPanel.tsx 파일은 FunnelPanel이 컬럼 컴포넌트를 import하므로 존치).
// v5 저장 레이아웃은 삭제된 리프를 참조해 깨지므로 키를 새로 부여해 초기화한다.
export const STORAGE_KEY = 'jonber.dashboard.layout.v6';

export const DEFAULT_LAYOUT: MosaicNode<PanelId> = {
  type: 'split',
  direction: 'row',
  splitPercentages: [38, 62],
  children: [
    'funnel',
    {
      type: 'split', direction: 'row', splitPercentages: [40, 30, 30],
      children: [
        'chart',
        {
          type: 'split', direction: 'column', splitPercentages: [22, 50, 28],
          children: ['portfolio', 'performance', 'positions'],
        },
        'debate',
      ],
    },
  ],
};

export function renderBody(id: PanelId) {
  switch (id) {
    case 'funnel': return <FunnelPanel />;
    case 'chart': return <ChartTile />;
    case 'portfolio': return <PortfolioPanel />;
    case 'positions': return <PositionsPanel />;
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
