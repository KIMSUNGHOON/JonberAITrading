/**
 * Sidebar Component
 *
 * Navigation for page views.
 * - Dashboard, Analysis, Charts, Positions, My Basket, Trades
 */

import { useMemo } from 'react';
import {
  BarChart3,
  Settings,
  Wallet,
  BookOpen,
  HelpCircle,
  ShoppingBasket,
  LayoutDashboard,
  Activity,
  Receipt,
  Bot,
} from 'lucide-react';
import { useStore } from '@/store';
import { MarketTabs } from '@/components/layout/MarketTabs';
import { useTranslations } from '@/utils/translations';

interface NavItemProps {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  badge?: string;
  onClick?: () => void;
  collapsed?: boolean;
}

function NavItem({ icon, label, active, badge, onClick, collapsed }: NavItemProps) {
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

interface SidebarProps {
  collapsed?: boolean;
}

export function Sidebar({ collapsed = false }: SidebarProps) {
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const currentView = useStore((state) => state.currentView);
  const setCurrentView = useStore((state) => state.setCurrentView);
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  // Get counts for badges - use primitive selectors to avoid infinite loops
  const basketItemsCount = useStore((state) => state.basket.items.length);
  const activeMarket = useStore((state) => state.activeMarket);
  const stockPosition = useStore((state) => state.stock.activePosition);
  const coinPosition = useStore((state) => state.coin.activePosition);
  const kiwoomPosition = useStore((state) => state.kiwoom.activePosition);

  // Get running session counts from each market
  const stockStatus = useStore((state) => state.stock.status);
  const coinStatus = useStore((state) => state.coin.status);
  const kiwoomSessions = useStore((state) => state.kiwoom.sessions);

  // Calculate active position based on current market
  const activePosition = useMemo(() => {
    if (activeMarket === 'stock') return stockPosition;
    if (activeMarket === 'coin') return coinPosition;
    return kiwoomPosition;
  }, [activeMarket, stockPosition, coinPosition, kiwoomPosition]);

  // Calculate running analyses count
  const runningCount = useMemo(() => {
    let count = 0;
    if (stockStatus === 'running' || stockStatus === 'awaiting_approval') count++;
    if (coinStatus === 'running' || coinStatus === 'awaiting_approval') count++;
    count += kiwoomSessions.filter(
      s => s.status === 'running' || s.status === 'awaiting_approval'
    ).length;
    return count;
  }, [stockStatus, coinStatus, kiwoomSessions]);

  return (
    <div className={`h-full flex flex-col overflow-hidden ${collapsed ? 'p-2' : 'p-3'}`}>
      {/* Market Tabs - Hidden when collapsed */}
      {!collapsed && (
        <div className="mb-3 flex-shrink-0">
          <MarketTabs />
        </div>
      )}

      {/* Navigation */}
      <nav className="space-y-1">
        <NavItem
          icon={<LayoutDashboard className="w-5 h-5" />}
          label={t('nav_dashboard')}
          active={currentView === 'dashboard'}
          onClick={() => setCurrentView('dashboard')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<Activity className="w-5 h-5" />}
          label={t('nav_analysis')}
          active={currentView === 'analysis'}
          badge={runningCount > 0 ? String(runningCount) : undefined}
          onClick={() => setCurrentView('analysis')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<BarChart3 className="w-5 h-5" />}
          label={t('nav_charts')}
          active={currentView === 'charts'}
          onClick={() => setCurrentView('charts')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<Wallet className="w-5 h-5" />}
          label={t('nav_positions')}
          active={currentView === 'positions'}
          badge={activePosition ? '1' : undefined}
          onClick={() => setCurrentView('positions')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<ShoppingBasket className="w-5 h-5" />}
          label={t('nav_basket')}
          active={currentView === 'basket'}
          badge={basketItemsCount > 0 ? String(basketItemsCount) : undefined}
          onClick={() => setCurrentView('basket')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<Receipt className="w-5 h-5" />}
          label={t('nav_trades')}
          active={currentView === 'trades'}
          onClick={() => setCurrentView('trades')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<Bot className="w-5 h-5" />}
          label={t('nav_auto_trading')}
          active={currentView === 'trading'}
          onClick={() => setCurrentView('trading')}
          collapsed={collapsed}
        />
      </nav>

      {/* Spacer to push secondary nav down */}
      <div className="flex-1" />

      {/* Divider */}
      <div className="border-t border-border my-4 flex-shrink-0" />

      {/* Secondary Navigation */}
      <nav className="space-y-1 flex-shrink-0">
        <NavItem
          icon={<BookOpen className="w-5 h-5" />}
          label={t('nav_documentation')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<HelpCircle className="w-5 h-5" />}
          label={t('nav_help')}
          collapsed={collapsed}
        />
        <NavItem
          icon={<Settings className="w-5 h-5" />}
          label={t('nav_settings')}
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
