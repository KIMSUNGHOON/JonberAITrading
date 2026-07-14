/**
 * TerminalDashboard registration (P2 funnel-consolidation Task 5) — pins
 * that the new 'funnel' PanelId is wired at all 4 required sites (PanelId /
 * TITLES / DEFAULT_LAYOUT / renderBody — a missed site is a crash or a
 * blank tile) and that the mosaic layout storage key was bumped v4→v5 so
 * any previously-saved layout (which doesn't know about 'funnel') is reset
 * to the new default rather than silently hiding the funnel panel forever.
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
  const [a, b] = node.children;
  return [...leavesOf(a), ...leavesOf(b)];
}

describe('TerminalDashboard — mosaic layout v5 + funnel registration', () => {
  it('bumps the layout storage key to v5 (resets any v4-saved layout that predates the funnel panel)', () => {
    expect(STORAGE_KEY).toBe('jonber.dashboard.layout.v5');
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
});
