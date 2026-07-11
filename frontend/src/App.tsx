/**
 * Main Application Component
 *
 * Hybrid Layout: Dashboard + Chat Interface
 */

import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useStore, selectError } from '@/store';
import { TerminalShell } from '@/components/terminal/TerminalShell';
import { TerminalDashboard } from '@/components/terminal/TerminalDashboard';
import { MobileNav } from '@/components/layout/MobileNav';
import { SettingsModal } from '@/components/settings/SettingsModal';
import { ChatToggleButton } from '@/components/chat/ChatToggleButton';
import { ChatPopup } from '@/components/chat/ChatPopup';
import { Toast } from '@/components/ui/Toast';
import { TradeNotificationToast } from '@/components/ui/TradeNotificationToast';
import { getUpbitApiStatus, getKiwoomApiStatus } from '@/api/client';
import { SessionBridge } from '@/routes/SessionBridge';
import { BasketPage } from '@/pages/BasketPage';
import { PositionsPage } from '@/pages/PositionsPage';
import { ChartsPage } from '@/pages/ChartsPage';
import { TradesPage } from '@/pages/TradesPage';
import { AnalysisPage } from '@/pages/AnalysisPage';
import { WorkflowPage } from '@/pages/WorkflowPage';
import { AnalysisDetailPage } from '@/pages/AnalysisDetailPage';
import { ScannerResultsPage } from '@/pages/ScannerResultsPage';
import { TradingDashboard } from '@/components/trading';
import { AgentChatDashboard } from '@/components/agent-chat';

function App() {
  const showSettingsModal = useStore((state) => state.showSettingsModal);
  const setShowSettingsModal = useStore((state) => state.setShowSettingsModal);
  const setUpbitApiConfigured = useStore((state) => state.setUpbitApiConfigured);
  const setKiwoomApiConfigured = useStore((state) => state.setKiwoomApiConfigured);
  const error = useStore(selectError);
  const setError = useStore((state) => state.setError);

  // Chat Popup state - select individual values to avoid re-renders
  const chatPopupOpen = useStore((state) => state.chatPopupOpen);
  const chatPopupSize = useStore((state) => state.chatPopupSize);
  const chatPopupPosition = useStore((state) => state.chatPopupPosition);
  const toggleChatPopup = useStore((state) => state.toggleChatPopup);
  const setChatPopupOpen = useStore((state) => state.setChatPopupOpen);
  const setChatPopupSize = useStore((state) => state.setChatPopupSize);
  const setChatPopupPosition = useStore((state) => state.setChatPopupPosition);

  // Check if there's a notification (awaiting approval or new messages)
  const awaitingApproval = useStore((state) => {
    switch (state.activeMarket) {
      case 'coin': return state.coin.awaitingApproval;
      case 'kiwoom': return state.kiwoom.awaitingApproval;
    }
  });
  const hasMessages = useStore((state) => state.messages.length > 0);
  const hasNotification = !chatPopupOpen && (awaitingApproval || hasMessages);

  // Check API status on mount
  useEffect(() => {
    async function checkApiStatus() {
      // Check Upbit API
      try {
        const upbitStatus = await getUpbitApiStatus();
        setUpbitApiConfigured(upbitStatus.is_configured);
      } catch (err) {
        console.error('Failed to check Upbit API status:', err);
      }

      // Check Kiwoom API
      try {
        const kiwoomStatus = await getKiwoomApiStatus();
        setKiwoomApiConfigured(kiwoomStatus.is_configured);
      } catch (err) {
        console.error('Failed to check Kiwoom API status:', err);
      }
    }
    checkApiStatus();
  }, [setUpbitApiConfigured, setKiwoomApiConfigured]);

  return (
    <div className="h-screen overflow-hidden">
      {/* Dense Terminal Shell: command bar + nav rail + status line wrap all views */}
      <Routes>
        <Route element={<TerminalShell />}>
          <Route index element={<TerminalDashboard />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="analysis/:sessionId" element={<SessionBridge><AnalysisDetailPage /></SessionBridge>} />
          <Route path="workflow/:sessionId" element={<SessionBridge><WorkflowPage /></SessionBridge>} />
          <Route path="positions" element={<PositionsPage />} />
          <Route path="charts" element={<ChartsPage />} />
          <Route path="watchlist" element={<BasketPage />} />
          <Route path="scanner" element={<ScannerResultsPage />} />
          <Route path="agent-chat" element={<div className="p-3 md:p-4"><AgentChatDashboard /></div>} />
          <Route path="trading" element={<TradingDashboard />} />
          <Route path="trades" element={<TradesPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>

      {/* Error Toast - Persistent with dismiss button (overlay) */}
      {error && (
        <Toast
          message={error}
          type="error"
          duration={0}
          onClose={() => setError(null)}
        />
      )}

      {/* Trade Notification Toast - Real-time WebSocket notifications (overlay) */}
      <TradeNotificationToast
        maxToasts={5}
        duration={5000}
        position="top-right"
      />

      {/* Mobile Navigation */}
      <MobileNav />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />

      {/* Chat Toggle Button - Desktop only */}
      <ChatToggleButton
        isOpen={chatPopupOpen}
        onClick={toggleChatPopup}
        hasNotification={hasNotification}
      />

      {/* Chat Popup - Desktop only */}
      <ChatPopup
        isOpen={chatPopupOpen}
        onClose={() => setChatPopupOpen(false)}
        size={chatPopupSize}
        onSizeChange={setChatPopupSize}
        position={chatPopupPosition}
        onPositionChange={setChatPopupPosition}
      />
    </div>
  );
}

export default App;
