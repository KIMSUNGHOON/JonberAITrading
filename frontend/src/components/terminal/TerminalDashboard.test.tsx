/**
 * TerminalDashboard registration (P2 funnel-consolidation Task 5; layout
 * pruned 8→6 leaves by the dashboard-widget-cull pass, 2026-07-14) — pins
 * that the 'funnel' PanelId is wired at all 4 required sites (PanelId /
 * TITLES / DEFAULT_LAYOUT / renderBody — a missed site is a crash or a
 * blank tile) and that the mosaic layout storage key was bumped v5→v6 so
 * any previously-saved layout (which may reference the now-removed
 * 'scanner'/'watchlist'/'operations' leaves) is reset to the new default
 * rather than rendering a blank/undefined tile.
 *
 * These exercise the exported pure data (TITLES/DEFAULT_LAYOUT/renderBody)
 * directly rather than mounting the full <TerminalDashboard/> tree, so the
 * test doesn't need to stand up every child panel's REST/router deps just
 * to prove the registry is self-consistent (mirrors the ./commands.test.ts
 * convention of unit-testing exported registration tables directly).
 */
import { describe, expect, it } from 'vitest';
import { isValidElement } from 'react';
import type { MosaicNode } from 'react-mosaic-component';
import {
  STORAGE_KEY, TITLES, DEFAULT_LAYOUT, renderBody, type PanelId,
} from './TerminalDashboard';
import { FunnelPanel } from './panels/FunnelPanel';

function leavesOf(node: MosaicNode<PanelId>): PanelId[] {
  if (typeof node === 'string') return [node];
  if (!('children' in node)) return []; // tabs nodes unused by DEFAULT_LAYOUT
  // Split nodes are n-ary (react-mosaic's MosaicSplitNode.children is an
  // array, not a fixed pair) — DEFAULT_LAYOUT nests 3- and 4-child splits,
  // so this must walk every child, not just the first two.
  return node.children.flatMap(leavesOf);
}

describe('TerminalDashboard — mosaic layout v6 + funnel registration', () => {
  it('bumps the layout storage key to v6 (resets any v5-saved layout that references the removed scanner/watchlist/operations leaves)', () => {
    expect(STORAGE_KEY).toBe('jonber.dashboard.layout.v6');
  });

  it('registers "funnel" in the DEFAULT_LAYOUT tree', () => {
    expect(leavesOf(DEFAULT_LAYOUT)).toContain('funnel');
  });

  it('registers "funnel" with a title', () => {
    expect(TITLES.funnel).toBeTruthy();
  });

  it('renderBody("funnel") returns <FunnelPanel/>', () => {
    const el = renderBody('funnel');
    expect(isValidElement(el)).toBe(true);
    expect((el as React.ReactElement).type).toBe(FunnelPanel);
  });

  it('every leaf in DEFAULT_LAYOUT has a title AND a non-crashing renderBody case (4-site consistency)', () => {
    for (const id of leavesOf(DEFAULT_LAYOUT)) {
      expect(TITLES[id]).toBeTruthy();
      expect(renderBody(id)).toBeDefined();
    }
  });

  it('is trimmed to exactly 6 leaves — scanner/watchlist/operations are gone', () => {
    const leaves = leavesOf(DEFAULT_LAYOUT);
    expect(leaves.sort()).toEqual(
      ['chart', 'debate', 'funnel', 'performance', 'portfolio', 'positions'].sort()
    );
    expect(leaves).not.toContain('scanner');
    expect(leaves).not.toContain('watchlist');
    expect(leaves).not.toContain('operations');
  });
});
