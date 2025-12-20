/**
 * Sidebar Component
 *
 * Navigation and quick actions with ticker history.
 */

import { useState } from 'react';
import {
  BarChart3,
  History,
  Settings,
  TrendingUp,
  Wallet,
  BookOpen,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
} from 'lucide-react';
import { useStore, selectTickerHistory, type TickerHistoryItem } from '@/store';
import { TickerInput } from '@/components/analysis/TickerInput';
import { CoinTickerInput } from '@/components/coin/CoinTickerInput';
import { MarketTabs } from '@/components/layout/MarketTabs';

interface NavItemProps {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  badge?: string;
  onClick?: () => void;
  expandable?: boolean;
  expanded?: boolean;
  collapsed?: boolean;
}

function NavItem({ icon, label, active, badge, onClick, expandable, expanded, collapsed }: NavItemProps) {
  return (
    <button
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors relative ${
        active
          ? 'bg-blue-600/20 text-blue-400'
          : 'text-gray-400 hover:bg-surface hover:text-gray-200'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      {icon}
      {!collapsed && (
        <>
          <span className="flex-1 text-left text-sm font-medium">{label}</span>
          {badge && (
            <span className="px-2 py-0.5 text-xs bg-blue-600 text-white rounded-full">
              {badge}
            </span>
          )}
          {expandable && (
            expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )
          )}
        </>
      )}
      {collapsed && badge && (
        <span className="absolute -top-1 -right-1 w-4 h-4 text-[10px] bg-blue-600 text-white rounded-full flex items-center justify-center">
          {badge}
        </span>
      )}
    </button>
  );
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />;
    case 'error':
    case 'cancelled':
      return <XCircle className="w-3.5 h-3.5 text-red-400" />;
    case 'running':
    case 'awaiting_approval':
      return <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />;
    default:
      return <Clock className="w-3.5 h-3.5 text-gray-400" />;
  }
}

function formatTime(date: Date): string {
  const d = new Date(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return d.toLocaleDateString();
}

interface HistoryItemProps {
  item: TickerHistoryItem;
  isActive: boolean;
}

function HistoryItem({ item, isActive, collapsed }: HistoryItemProps & { collapsed?: boolean }) {
  return (
    <div
      title={collapsed ? `${item.ticker} - ${item.status}` : undefined}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
        isActive
          ? 'bg-blue-600/20 text-blue-400'
          : 'text-gray-400 hover:bg-surface hover:text-gray-300'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      {getStatusIcon(item.status)}
      {!collapsed && (
        <>
          <span className="font-medium">{item.ticker}</span>
          <span className="ml-auto text-xs opacity-60">
            {formatTime(item.timestamp)}
          </span>
        </>
      )}
    </div>
  );
}

interface SidebarProps {
  collapsed?: boolean;
}

export function Sidebar({ collapsed = false }: SidebarProps) {
  const [showHistory, setShowHistory] = useState(true);
  const activeMarket = useStore((state) => state.activeMarket);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const activePosition = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.activePosition : state.coin.activePosition
  );
  const analyses = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.analyses : state.coin.analyses
  );
  const tickerHistory = useStore(selectTickerHistory);
  const activeSessionId = useStore((state) =>
    state.activeMarket === 'stock' ? state.stock.activeSessionId : state.coin.activeSessionId
  );

  return (
    <div className={`h-full flex flex-col ${collapsed ? 'p-2' : 'p-4'}`}>
      {/* Market Tabs - Hidden when collapsed */}
      {!collapsed && (
        <div className="mb-4">
          <MarketTabs />
        </div>
      )}

      {/* Ticker Input - Hidden when collapsed */}
      {!collapsed && (
        <div className="mb-4">
          {activeMarket === 'stock' ? <TickerInput /> : <CoinTickerInput />}
        </div>
      )}

      {/* Navigation */}
      <nav className="space-y-1">
        <NavItem
          icon={<TrendingUp className="w-5 h-5" />}
          label="Analysis"
          active
          badge={analyses.length > 0 ? String(analyses.length) : undefined}
          collapsed={collapsed}
        />
        <NavItem
          icon={<BarChart3 className="w-5 h-5" />}
          label="Charts"
          collapsed={collapsed}
        />
        <NavItem
          icon={<Wallet className="w-5 h-5" />}
          label="Positions"
          badge={activePosition ? '1' : undefined}
          collapsed={collapsed}
        />
        <NavItem
          icon={<History className="w-5 h-5" />}
          label="History"
          badge={tickerHistory.length > 0 ? String(tickerHistory.length) : undefined}
          expandable={!collapsed}
          expanded={showHistory}
          onClick={() => !collapsed && setShowHistory(!showHistory)}
          collapsed={collapsed}
        />
      </nav>

      {/* History Panel - Hidden when collapsed */}
      {!collapsed && showHistory && tickerHistory.length > 0 && (
        <div className="mt-2 ml-2 space-y-1 max-h-48 overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-gray-700">
          {tickerHistory.map((item) => (
            <HistoryItem
              key={item.sessionId}
              item={item}
              isActive={item.sessionId === activeSessionId}
              collapsed={collapsed}
            />
          ))}
        </div>
      )}

      {/* Empty History Message - Hidden when collapsed */}
      {!collapsed && showHistory && tickerHistory.length === 0 && (
        <div className="mt-2 ml-2 px-3 py-2 text-xs text-gray-500">
          No analysis history yet
        </div>
      )}

      {/* Spacer to push secondary nav down */}
      <div className="flex-1" />

      {/* Divider */}
      <div className="border-t border-border my-4 flex-shrink-0" />

      {/* Secondary Navigation */}
      <nav className="space-y-1 flex-shrink-0">
        <NavItem
          icon={<BookOpen className="w-5 h-5" />}
          label="Documentation"
          collapsed={collapsed}
        />
        <NavItem
          icon={<HelpCircle className="w-5 h-5" />}
          label="Help"
          collapsed={collapsed}
        />
        <NavItem
          icon={<Settings className="w-5 h-5" />}
          label="Settings"
          onClick={() => setShowSettingsModal(true)}
          collapsed={collapsed}
        />
      </nav>

      {/* Version - Hidden when collapsed */}
      {!collapsed && (
        <div className="mt-4 px-3 py-2 text-xs text-gray-500 flex-shrink-0">
          v1.0.0 - Beta
        </div>
      )}
    </div>
  );
}
