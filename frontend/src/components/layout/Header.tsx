/**
 * Header Component
 *
 * Top navigation bar with branding, market status, and controls.
 */

import { Menu, Settings, Bell, Activity, PanelLeftClose, PanelLeft } from 'lucide-react';
import { useStore, selectStatus, selectTicker } from '@/store';
import { MarketStatusBadge, MarketStatusCompact } from './MarketStatusBadge';

export function Header() {
  const status = useStore(selectStatus);
  const ticker = useStore(selectTicker);
  const setMobileMenuOpen = useStore((state) => state.setMobileMenuOpen);
  const sidebarCollapsed = useStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useStore((state) => state.toggleSidebar);

  const isActive = status === 'running' || status === 'awaiting_approval';

  return (
    <header className="h-16 border-b border-border bg-surface-light px-4 flex items-center justify-between">
      {/* Left Section */}
      <div className="flex items-center gap-4">
        {/* Mobile Menu Button */}
        <button
          className="lg:hidden p-2 hover:bg-surface rounded-lg"
          onClick={() => setMobileMenuOpen(true)}
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Sidebar Toggle Button (Desktop) */}
        <button
          className="hidden lg:flex p-2 hover:bg-surface rounded-lg transition-colors"
          onClick={toggleSidebar}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {sidebarCollapsed ? (
            <PanelLeft className="w-5 h-5" />
          ) : (
            <PanelLeftClose className="w-5 h-5" />
          )}
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2">
          <Activity className="w-6 h-6 text-blue-500" />
          <span className="font-bold text-lg hidden sm:block">
            Agentic Trading
          </span>
        </div>

        {/* Active Session Badge */}
        {isActive && ticker && (
          <div className="flex items-center gap-2 px-3 py-1 bg-surface rounded-full">
            <span className="live-indicator text-sm font-medium">
              {ticker}
            </span>
          </div>
        )}
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-2">
        {/* Market Status (Desktop) */}
        <MarketStatusBadge />

        {/* Market Status (Mobile) */}
        <MarketStatusCompact />

        {/* Divider */}
        <div className="hidden md:block w-px h-6 bg-border" />

        {/* Status Indicator */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-surface rounded-lg">
          <div
            className={`w-2 h-2 rounded-full ${
              status === 'running'
                ? 'bg-bull animate-pulse'
                : status === 'awaiting_approval'
                ? 'bg-yellow-500 animate-pulse'
                : status === 'error'
                ? 'bg-bear'
                : 'bg-gray-500'
            }`}
          />
          <span className="text-sm text-gray-400 capitalize">
            {status === 'idle' ? 'Ready' : status.replace('_', ' ')}
          </span>
        </div>

        {/* Notifications */}
        <button className="p-2 hover:bg-surface rounded-lg relative">
          <Bell className="w-5 h-5" />
          {status === 'awaiting_approval' && (
            <span className="absolute top-1 right-1 w-2 h-2 bg-yellow-500 rounded-full" />
          )}
        </button>

        {/* Settings */}
        <button className="p-2 hover:bg-surface rounded-lg">
          <Settings className="w-5 h-5" />
        </button>
      </div>
    </header>
  );
}
