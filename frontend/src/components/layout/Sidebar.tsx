/**
 * Sidebar Component
 *
 * Mobile hamburger-menu navigation. Renders from NAV_ITEMS (frontend/src/nav.ts)
 * — the same single source of truth the desktop TerminalShell rail and the
 * ⌘K command palette use — so this menu can never drift out of sync with
 * the rest of the app's nav surface again (nav-rationalize, 2026-07-14).
 */

import { useMemo } from 'react';
import {
  Settings,
  Wallet,
  BookOpen,
  HelpCircle,
  LayoutDashboard,
  Activity,
  Receipt,
  Bot,
  Scan,
  Telescope,
  MessageSquare,
} from 'lucide-react';
import { useStore } from '@/store';
import { useGoTo, useActiveView } from '@/hooks/useNav';
import { NAV_ITEMS, type ViewKey } from '@/nav';
import { MarketTabs } from '@/components/layout/MarketTabs';
import { useTranslations } from '@/utils/translations';

// Icon lookup for NAV_ITEMS — mirrors TerminalShell's NAV_ICONS (icons are
// kept local to each nav consumer per nav.ts's "icons stay in
// TerminalShell/Sidebar" convention; only the ViewKeys present in NAV_ITEMS
// need an entry here).
const NAV_ICONS: Partial<Record<ViewKey, React.ReactNode>> = {
  dashboard: <LayoutDashboard className="w-5 h-5" />,
  analysis: <Activity className="w-5 h-5" />,
  positions: <Wallet className="w-5 h-5" />,
  'agent-chat': <MessageSquare className="w-5 h-5" />,
  scanner: <Scan className="w-5 h-5" />,
  trading: <Bot className="w-5 h-5" />,
  trades: <Receipt className="w-5 h-5" />,
  discovery: <Telescope className="w-5 h-5" />,
};

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
  const goTo = useGoTo();
  const activeView = useActiveView();
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const language = useStore((state) => state.language);
  const t = useTranslations(language);

  const activePosition = useStore((state) => state.kiwoom.activePosition);

  // Get running session count
  const kiwoomSessions = useStore((state) => state.kiwoom.sessions);

  // Calculate running analyses count
  const runningCount = useMemo(() => {
    return kiwoomSessions.filter(
      s => s.status === 'running' || s.status === 'awaiting_approval'
    ).length;
  }, [kiwoomSessions]);

  // Only 'analysis' (running session count) and 'positions' (active
  // position present) carry a badge.
  const badgeFor = (view: ViewKey): string | undefined => {
    if (view === 'analysis') return runningCount > 0 ? String(runningCount) : undefined;
    if (view === 'positions') return activePosition ? '1' : undefined;
    return undefined;
  };

  return (
    <div className={`h-full flex flex-col overflow-hidden ${collapsed ? 'p-2' : 'p-3'}`}>
      {/* Market Tabs - Hidden when collapsed */}
      {!collapsed && (
        <div className="mb-3 flex-shrink-0">
          <MarketTabs />
        </div>
      )}

      {/* Navigation — single source: NAV_ITEMS (frontend/src/nav.ts) */}
      <nav className="space-y-1">
        {NAV_ITEMS.map((n) => (
          <NavItem
            key={n.view}
            icon={NAV_ICONS[n.view]}
            label={n.label}
            active={activeView === n.view}
            badge={badgeFor(n.view)}
            onClick={() => goTo(n.view)}
            collapsed={collapsed}
          />
        ))}
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
