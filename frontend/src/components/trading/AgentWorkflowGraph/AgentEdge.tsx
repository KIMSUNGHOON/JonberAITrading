/**
 * AgentEdge Component
 *
 * Renders SVG connection lines between agent nodes.
 * Supports animated dashed lines for active connections.
 */

import { useMemo } from 'react';
import type { AgentKey, AgentState, WorkflowConnection } from './types';

// -------------------------------------------
// Types
// -------------------------------------------

interface AgentEdgeContainerProps {
  /** Workflow connections to render */
  connections: WorkflowConnection[];
  /** Agent states for determining active status */
  agents: Record<string, AgentState>;
  /** Number of nodes (used for layout calculation) */
  nodeCount: number;
  /** Height of each node in pixels */
  nodeHeight?: number;
  /** Gap between nodes in pixels */
  nodeGap?: number;
  /** Container padding in pixels */
  containerPadding?: number;
}

interface EdgePath {
  key: string;
  startY: number;
  endY: number;
  isActive: boolean;
}

// -------------------------------------------
// Constants
// -------------------------------------------

const DEFAULT_NODE_HEIGHT = 100;
const DEFAULT_NODE_GAP = 16; // gap-4 = 16px
const DEFAULT_CONTAINER_PADDING = 16; // p-4 = 16px

// -------------------------------------------
// Helper Functions
// -------------------------------------------

/**
 * Calculate Y positions for edge paths based on node layout
 */
function calculateEdgePaths(
  connections: WorkflowConnection[],
  agents: Record<string, AgentState>,
  nodeOrder: AgentKey[],
  nodeHeight: number,
  nodeGap: number,
  _containerPadding: number
): EdgePath[] {
  return connections.map((connection) => {
    const fromIndex = nodeOrder.indexOf(connection.from);
    const toIndex = nodeOrder.indexOf(connection.to);

    const fromAgent = agents[connection.from];
    const toAgent = agents[connection.to];
    const isActive = fromAgent?.status === 'working' || toAgent?.status === 'working';

    // Calculate Y positions
    // Each node starts at: index * (nodeHeight + nodeGap)
    // The bottom of a node: startY + nodeHeight
    // The top of next node: (index + 1) * (nodeHeight + nodeGap)
    const startY = (fromIndex + 1) * (nodeHeight + nodeGap) - nodeGap / 2;
    const endY = toIndex * (nodeHeight + nodeGap) + nodeGap / 2;

    return {
      key: `${connection.from}-${connection.to}`,
      startY,
      endY,
      isActive,
    };
  });
}

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface EdgeLineProps {
  startY: number;
  endY: number;
  isActive: boolean;
  containerWidth: number;
}

function EdgeLine({ startY, endY, isActive, containerWidth }: EdgeLineProps) {
  const centerX = containerWidth / 2;
  const arrowSize = 6;

  return (
    <g>
      {/* Main line */}
      <line
        x1={centerX}
        y1={startY}
        x2={centerX}
        y2={endY - arrowSize}
        stroke={isActive ? '#3b82f6' : '#374151'}
        strokeWidth={2}
        strokeDasharray={isActive ? '6 4' : 'none'}
        className={isActive ? 'animate-dash' : ''}
      />
      {/* Arrow head */}
      <polygon
        points={`${centerX - arrowSize},${endY - arrowSize * 1.5} ${centerX},${endY} ${centerX + arrowSize},${endY - arrowSize * 1.5}`}
        fill={isActive ? '#3b82f6' : '#374151'}
      />
    </g>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

const AGENT_ORDER: AgentKey[] = ['strategy', 'portfolio', 'order', 'risk'];

export function AgentEdgeContainer({
  connections,
  agents,
  nodeCount,
  nodeHeight = DEFAULT_NODE_HEIGHT,
  nodeGap = DEFAULT_NODE_GAP,
  containerPadding = DEFAULT_CONTAINER_PADDING,
}: AgentEdgeContainerProps) {
  // Calculate edge paths
  const edgePaths = useMemo(
    () =>
      calculateEdgePaths(
        connections,
        agents,
        AGENT_ORDER,
        nodeHeight,
        nodeGap,
        containerPadding
      ),
    [connections, agents, nodeHeight, nodeGap, containerPadding]
  );

  // Calculate total height
  const totalHeight = nodeCount * (nodeHeight + nodeGap) - nodeGap;

  return (
    <svg
      className="absolute inset-0 w-full pointer-events-none overflow-visible"
      style={{ height: totalHeight }}
      preserveAspectRatio="none"
    >
      {edgePaths.map((edge) => (
        <EdgeLine
          key={edge.key}
          startY={edge.startY}
          endY={edge.endY}
          isActive={edge.isActive}
          containerWidth={500} // Will be replaced by actual width
        />
      ))}
    </svg>
  );
}

/**
 * Simple Edge component for basic use
 * Draws a vertical line between two Y positions
 */
interface SimpleEdgeProps {
  fromY: number;
  toY: number;
  isActive?: boolean;
  width?: number;
}

export function SimpleEdge({ fromY, toY, isActive = false, width = 100 }: SimpleEdgeProps) {
  const centerX = width / 2;
  const arrowSize = 6;

  return (
    <svg
      className="absolute left-0 top-0 pointer-events-none"
      style={{ width, height: Math.max(fromY, toY) + arrowSize }}
    >
      <line
        x1={centerX}
        y1={fromY}
        x2={centerX}
        y2={toY - arrowSize}
        stroke={isActive ? '#3b82f6' : '#374151'}
        strokeWidth={2}
        strokeDasharray={isActive ? '6 4' : 'none'}
        className={isActive ? 'animate-dash' : ''}
      />
      <polygon
        points={`${centerX - arrowSize},${toY - arrowSize * 1.5} ${centerX},${toY} ${centerX + arrowSize},${toY - arrowSize * 1.5}`}
        fill={isActive ? '#3b82f6' : '#374151'}
      />
    </svg>
  );
}

export default AgentEdgeContainer;
