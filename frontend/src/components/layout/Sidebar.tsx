/**
 * Sidebar Component
 *
 * Navigation and quick actions.
 */

import {
  BarChart3,
  History,
  Settings,
  TrendingUp,
  Wallet,
  BookOpen,
  HelpCircle,
} from 'lucide-react';
import { useStore } from '@/store';
import { TickerInput } from '@/components/analysis/TickerInput';

interface NavItemProps {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  badge?: string;
  onClick?: () => void;
}

function NavItem({ icon, label, active, badge, onClick }: NavItemProps) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
        active
          ? 'bg-blue-600/20 text-blue-400'
          : 'text-gray-400 hover:bg-surface hover:text-gray-200'
      }`}
    >
      {icon}
      <span className="flex-1 text-left text-sm font-medium">{label}</span>
      {badge && (
        <span className="px-2 py-0.5 text-xs bg-blue-600 text-white rounded-full">
          {badge}
        </span>
      )}
    </button>
  );
}

export function Sidebar() {
  const activePosition = useStore((state) => state.activePosition);
  const analyses = useStore((state) => state.analyses);

  return (
    <div className="h-full flex flex-col p-4">
      {/* Ticker Input */}
      <div className="mb-6">
        <TickerInput />
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1">
        <NavItem
          icon={<TrendingUp className="w-5 h-5" />}
          label="Analysis"
          active
          badge={analyses.length > 0 ? String(analyses.length) : undefined}
        />
        <NavItem
          icon={<BarChart3 className="w-5 h-5" />}
          label="Charts"
        />
        <NavItem
          icon={<Wallet className="w-5 h-5" />}
          label="Positions"
          badge={activePosition ? '1' : undefined}
        />
        <NavItem
          icon={<History className="w-5 h-5" />}
          label="History"
        />
      </nav>

      {/* Divider */}
      <div className="border-t border-border my-4" />

      {/* Secondary Navigation */}
      <nav className="space-y-1">
        <NavItem
          icon={<BookOpen className="w-5 h-5" />}
          label="Documentation"
        />
        <NavItem
          icon={<HelpCircle className="w-5 h-5" />}
          label="Help"
        />
        <NavItem
          icon={<Settings className="w-5 h-5" />}
          label="Settings"
        />
      </nav>

      {/* Version */}
      <div className="mt-4 px-3 py-2 text-xs text-gray-500">
        v1.0.0 - Beta
      </div>
    </div>
  );
}
