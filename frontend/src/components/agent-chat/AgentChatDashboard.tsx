/**
 * AgentChatDashboard Component
 *
 * Main dashboard for Agent Group Chat system.
 * Controls coordinator start/stop and shows active discussions.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  MessageSquare,
  Play,
  Square,
  RefreshCw,
  Users,
  Clock,
  TrendingUp,
  AlertCircle,
  Settings,
} from 'lucide-react';
import {
  getAgentChatStatus,
  startAgentChat,
  stopAgentChat,
  getAgentChatActiveDiscussions,
  getAgentChatSessions,
} from '@/api/client';
import type {
  AgentChatCoordinatorStatus,
  AgentChatActiveDiscussion,
  AgentChatSessionSummary,
} from '@/types';
import { ChatSessionList } from './ChatSessionList';
import { ChatSessionViewer } from './ChatSessionViewer';
import { PositionMonitor } from './PositionMonitor';

interface CoordinatorConfig {
  check_interval_minutes: number;
  max_concurrent_discussions: number;
}

export function AgentChatDashboard() {
  const [status, setStatus] = useState<AgentChatCoordinatorStatus | null>(null);
  const [activeDiscussions, setActiveDiscussions] = useState<AgentChatActiveDiscussion[]>([]);
  const [recentSessions, setRecentSessions] = useState<AgentChatSessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [config, setConfig] = useState<CoordinatorConfig>({
    check_interval_minutes: 5,
    max_concurrent_discussions: 3,
  });

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [statusData, activeData, sessionsData] = await Promise.all([
        getAgentChatStatus().catch(() => null),
        getAgentChatActiveDiscussions().catch(() => ({ discussions: [], count: 0 })),
        getAgentChatSessions({ limit: 10 }).catch(() => ({ sessions: [], count: 0 })),
      ]);

      if (statusData) {
        setStatus(statusData);
        setConfig({
          check_interval_minutes: statusData.check_interval_minutes,
          max_concurrent_discussions: statusData.max_concurrent_discussions,
        });
      }
      setActiveDiscussions(activeData.discussions);
      setRecentSessions(sessionsData.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleStart = async () => {
    try {
      setActionLoading(true);
      setError(null);
      await startAgentChat(config);
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start coordinator');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionLoading(true);
      setError(null);
      await stopAgentChat();
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop coordinator');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  // If a session is selected, show the viewer
  if (selectedSessionId) {
    return (
      <ChatSessionViewer
        sessionId={selectedSessionId}
        onClose={() => setSelectedSessionId(null)}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <MessageSquare className="w-6 h-6 text-blue-400" />
          <h2 className="text-xl font-semibold text-white">Agent Group Chat</h2>
        </div>
        <button
          onClick={fetchData}
          className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
        >
          <RefreshCw className="w-5 h-5" />
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-400" />
          <span className="text-red-400">{error}</span>
        </div>
      )}

      {/* Status Card */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <div
              className={`w-3 h-3 rounded-full ${
                status?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'
              }`}
            />
            <span className="text-lg font-medium text-white">
              Coordinator {status?.is_running ? 'Running' : 'Stopped'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowConfig(!showConfig)}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg"
            >
              <Settings className="w-5 h-5" />
            </button>
            {status?.is_running ? (
              <button
                onClick={handleStop}
                disabled={actionLoading}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white rounded-lg"
              >
                {actionLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                Stop
              </button>
            ) : (
              <button
                onClick={handleStart}
                disabled={actionLoading}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white rounded-lg"
              >
                {actionLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                Start
              </button>
            )}
          </div>
        </div>

        {/* Config Panel */}
        {showConfig && (
          <div className="mb-6 p-4 bg-gray-800 rounded-lg space-y-4">
            <h4 className="text-sm font-medium text-gray-300">Configuration</h4>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Check Interval (minutes)
                </label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={config.check_interval_minutes}
                  onChange={(e) =>
                    setConfig({ ...config, check_interval_minutes: parseInt(e.target.value) || 5 })
                  }
                  className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Max Concurrent Discussions
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={config.max_concurrent_discussions}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      max_concurrent_discussions: parseInt(e.target.value) || 3,
                    })
                  }
                  className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm"
                />
              </div>
            </div>
          </div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-gray-800 rounded-lg p-4 text-center">
            <Users className="w-6 h-6 text-blue-400 mx-auto mb-2" />
            <div className="text-2xl font-bold text-white">{status?.active_discussions || 0}</div>
            <div className="text-xs text-gray-400">Active Discussions</div>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 text-center">
            <TrendingUp className="w-6 h-6 text-green-400 mx-auto mb-2" />
            <div className="text-2xl font-bold text-white">{status?.total_sessions || 0}</div>
            <div className="text-xs text-gray-400">Total Sessions</div>
          </div>
          <div className="bg-gray-800 rounded-lg p-4 text-center">
            <Clock className="w-6 h-6 text-yellow-400 mx-auto mb-2" />
            <div className="text-2xl font-bold text-white">
              {status?.check_interval_minutes || 5}m
            </div>
            <div className="text-xs text-gray-400">Check Interval</div>
          </div>
        </div>
      </div>

      {/* Active Discussions */}
      {activeDiscussions.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h3 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            Active Discussions
          </h3>
          <div className="space-y-3">
            {activeDiscussions.map((discussion) => (
              <div
                key={discussion.session_id}
                className="flex items-center justify-between p-4 bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-700"
                onClick={() => setSelectedSessionId(discussion.session_id)}
              >
                <div>
                  <div className="text-white font-medium">
                    {discussion.stock_name} ({discussion.ticker})
                  </div>
                  <div className="text-sm text-gray-400">
                    Status: {discussion.status}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-1 text-xs bg-blue-500/20 text-blue-400 rounded">
                    In Progress
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Main Grid - Sessions and Position Monitor */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Recent Sessions (2/3 width) */}
        <div className="xl:col-span-2">
          <ChatSessionList
            sessions={recentSessions}
            onSelectSession={setSelectedSessionId}
          />
        </div>

        {/* Position Monitor (1/3 width) */}
        <div>
          <PositionMonitor />
        </div>
      </div>
    </div>
  );
}

export default AgentChatDashboard;
