/**
 * Reasoning Log Component
 *
 * Displays real-time agent reasoning process with enhanced formatting.
 */

import { useRef, useEffect, useState, useMemo } from 'react';
import {
  Brain,
  ChevronRight,
  ChevronDown,
  LineChart,
  Building2,
  MessageSquare,
  Shield,
  Zap,
  Rocket,
  Copy,
  Check,
  X,
} from 'lucide-react';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';

interface ReasoningLogProps {
  entries: string[];
  maxHeight?: number;
  showFilters?: boolean;
}

type AgentType = 'Technical' | 'Fundamental' | 'Sentiment' | 'Risk' | 'Strategic' | 'Execution' | 'Task Decomposition' | 'HITL' | 'Other';

interface ParsedEntry {
  prefix?: string;
  prefixColor: string;
  bgColor: string;
  content: string;
  agentType: AgentType;
  icon: React.ComponentType<{ className?: string }>;
  hasSignal?: boolean;
  signalType?: 'bullish' | 'bearish' | 'neutral';
}

const AGENT_CONFIG: Record<string, {
  color: string;
  bgColor: string;
  icon: React.ComponentType<{ className?: string }>;
  agentType: AgentType;
}> = {
  'Technical': { color: 'text-blue-400', bgColor: 'bg-blue-500/10', icon: LineChart, agentType: 'Technical' },
  'Technical Analysis': { color: 'text-blue-400', bgColor: 'bg-blue-500/10', icon: LineChart, agentType: 'Technical' },
  'Fundamental': { color: 'text-purple-400', bgColor: 'bg-purple-500/10', icon: Building2, agentType: 'Fundamental' },
  'Fundamental Analysis': { color: 'text-purple-400', bgColor: 'bg-purple-500/10', icon: Building2, agentType: 'Fundamental' },
  'Sentiment': { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', icon: MessageSquare, agentType: 'Sentiment' },
  'Sentiment Analysis': { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', icon: MessageSquare, agentType: 'Sentiment' },
  'Risk': { color: 'text-red-400', bgColor: 'bg-red-500/10', icon: Shield, agentType: 'Risk' },
  'Risk Assessment': { color: 'text-red-400', bgColor: 'bg-red-500/10', icon: Shield, agentType: 'Risk' },
  'Strategic': { color: 'text-green-400', bgColor: 'bg-green-500/10', icon: Zap, agentType: 'Strategic' },
  'Strategic Decision': { color: 'text-green-400', bgColor: 'bg-green-500/10', icon: Zap, agentType: 'Strategic' },
  'Execution': { color: 'text-orange-400', bgColor: 'bg-orange-500/10', icon: Rocket, agentType: 'Execution' },
  'Task Decomposition': { color: 'text-cyan-400', bgColor: 'bg-cyan-500/10', icon: Brain, agentType: 'Task Decomposition' },
  'HITL': { color: 'text-amber-400', bgColor: 'bg-amber-500/10', icon: Shield, agentType: 'HITL' },
};

export function ReasoningLog({ entries, maxHeight = 400, showFilters = true }: ReasoningLogProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isExpanded, setIsExpanded] = useState(true);
  const [copied, setCopied] = useState(false);
  const [activeFilters, setActiveFilters] = useState<Set<AgentType>>(new Set());
  const [autoScroll, setAutoScroll] = useState(true);

  // Parse all entries
  const parsedEntries = useMemo(() => {
    return entries.map(entry => parseEntry(entry));
  }, [entries]);

  // Filter entries
  const filteredEntries = useMemo(() => {
    if (activeFilters.size === 0) return parsedEntries;
    return parsedEntries.filter(entry => activeFilters.has(entry.agentType));
  }, [parsedEntries, activeFilters]);

  // Get unique agent types for filter buttons
  const availableAgentTypes = useMemo(() => {
    const types = new Set<AgentType>();
    parsedEntries.forEach(entry => types.add(entry.agentType));
    return Array.from(types);
  }, [parsedEntries]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (containerRef.current && autoScroll) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  // Handle scroll to detect manual scrolling
  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };

  // Copy all entries to clipboard
  const copyToClipboard = async () => {
    const text = entries.join('\n');
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Toggle filter
  const toggleFilter = (agentType: AgentType) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(agentType)) {
        next.delete(agentType);
      } else {
        next.add(agentType);
      }
      return next;
    });
  };

  // Clear all filters
  const clearFilters = () => {
    setActiveFilters(new Set());
  };

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 hover:opacity-80"
        >
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
          <Brain className="w-5 h-5 text-purple-400" />
          <h3 className="font-medium">Agent Reasoning</h3>
        </button>

        <span className="text-xs text-gray-400 ml-auto">
          {filteredEntries.length}{activeFilters.size > 0 ? ` / ${entries.length}` : ''} entries
        </span>

        <button
          onClick={copyToClipboard}
          className="p-1.5 hover:bg-surface-light rounded-lg transition-colors"
          title="Copy to clipboard"
        >
          {copied ? (
            <Check className="w-4 h-4 text-green-400" />
          ) : (
            <Copy className="w-4 h-4 text-gray-400" />
          )}
        </button>
      </div>

      {isExpanded && (
        <>
          {/* Filter Buttons */}
          {showFilters && availableAgentTypes.length > 1 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {availableAgentTypes.map(agentType => {
                const config = Object.values(AGENT_CONFIG).find(c => c.agentType === agentType) || {
                  color: 'text-gray-400',
                  bgColor: 'bg-gray-500/10',
                  icon: Brain,
                };
                const Icon = config.icon;
                const isActive = activeFilters.has(agentType);

                return (
                  <button
                    key={agentType}
                    onClick={() => toggleFilter(agentType)}
                    className={`
                      flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium
                      transition-all duration-200
                      ${isActive
                        ? `${config.bgColor} ${config.color} ring-1 ring-current`
                        : 'bg-surface hover:bg-surface-light text-gray-400'
                      }
                    `}
                  >
                    <Icon className="w-3 h-3" />
                    {agentType}
                  </button>
                );
              })}
              {activeFilters.size > 0 && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium
                    bg-surface hover:bg-surface-light text-gray-400"
                >
                  <X className="w-3 h-3" />
                  Clear
                </button>
              )}
            </div>
          )}

          {/* Log Entries */}
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="space-y-2 overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-gray-700"
            style={{ maxHeight }}
          >
            {filteredEntries.map((parsed, index) => (
              <LogEntry key={index} parsed={parsed} index={index} />
            ))}
          </div>

          {/* Auto-scroll indicator */}
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true);
                if (containerRef.current) {
                  containerRef.current.scrollTop = containerRef.current.scrollHeight;
                }
              }}
              className="mt-2 w-full py-1.5 text-xs text-center text-gray-400 hover:text-white
                bg-surface-light rounded-lg transition-colors"
            >
              ↓ New entries available - click to scroll down
            </button>
          )}
        </>
      )}
    </div>
  );
}

interface LogEntryProps {
  parsed: ParsedEntry;
  index: number;
}

function LogEntry({ parsed, index }: LogEntryProps) {
  const Icon = parsed.icon;

  return (
    <div
      className={`
        flex items-start gap-3 text-sm p-3 rounded-lg
        animate-slide-in transition-colors
        ${parsed.bgColor} hover:brightness-110
      `}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <div className="flex flex-col items-center gap-1">
        <Icon className={`w-5 h-5 flex-shrink-0 ${parsed.prefixColor}`} />
        <span className="text-xs text-gray-500">#{index + 1}</span>
      </div>
      <div className="flex-1 min-w-0">
        {parsed.prefix && (
          <div className={`font-semibold mb-1 ${parsed.prefixColor}`}>
            {parsed.prefix}
          </div>
        )}
        <MarkdownRenderer content={parsed.content} compact />
      </div>
    </div>
  );
}

function parseEntry(entry: string): ParsedEntry {
  // Check for [Agent] prefix pattern
  const match = entry.match(/^\[([^\]]+)\]\s*(.*)$/);

  if (match) {
    const prefix = match[1];
    const content = match[2];

    const config = AGENT_CONFIG[prefix] || {
      color: 'text-gray-400',
      bgColor: 'bg-surface-light',
      icon: ChevronRight,
      agentType: 'Other' as AgentType,
    };

    // Detect signal type
    let signalType: 'bullish' | 'bearish' | 'neutral' | undefined;
    const lowerContent = content.toLowerCase();
    if (lowerContent.includes('strong_buy') || lowerContent.includes('buy')) {
      signalType = 'bullish';
    } else if (lowerContent.includes('strong_sell') || lowerContent.includes('sell')) {
      signalType = 'bearish';
    } else if (lowerContent.includes('hold')) {
      signalType = 'neutral';
    }

    return {
      prefix,
      prefixColor: config.color,
      bgColor: config.bgColor,
      content,
      agentType: config.agentType,
      icon: config.icon,
      hasSignal: !!signalType,
      signalType,
    };
  }

  return {
    prefixColor: 'text-gray-400',
    bgColor: 'bg-surface-light',
    content: entry,
    agentType: 'Other',
    icon: ChevronRight,
  };
}
