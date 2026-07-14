/**
 * Trading Components
 *
 * Components for the auto-trading dashboard and controls.
 *
 * P2 funnel-consolidation Task 8b: WatchListWidget/TradeQueueWidget were
 * deleted — their actions (convert/remove/re-analyze, cancel-queued,
 * manual queue-process) were backported into the dashboard funnel's
 * WatchingColumn/PendingBuyColumn (frontend/src/components/terminal/panels/
 * OperationsPanel.tsx), which is now the single surface for them.
 */

export { default as TradingDashboard } from './TradingDashboard';
