/**
 * Reasoning Log Component
 *
 * Displays real-time agent reasoning process with auto-collapse for completed entries.
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
  Eye,
  EyeOff,
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

export function ReasoningLog({ entries, maxHeight, showFilters = false }: ReasoningLogProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isExpanded, setIsExpanded] = useState(true);
  const [copied, setCopied] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [expandedEntries, setExpandedEntries] = useState<Set<number>>(new Set());
  const [autoScroll, setAutoScroll] = useState(true);

  // Parse all entries
  const parsedEntries = useMemo(() => {
    return entries.map(entry => parseEntry(entry));
  }, [entries]);

  // Group entries by agent type
  const groupedEntries = useMemo(() => {
    const groups = new Map<AgentType, { entries: ParsedEntry[]; indices: number[] }>();
    parsedEntries.forEach((entry, index) => {
      const existing = groups.get(entry.agentType);
      if (existing) {
        existing.entries.push(entry);
        existing.indices.push(index);
      } else {
        groups.set(entry.agentType, { entries: [entry], indices: [index] });
      }
    });
    return groups;
  }, [parsedEntries]);

  // Get the latest entry for display
  const latestEntry = parsedEntries.length > 0 ? parsedEntries[parsedEntries.length - 1] : null;
  const latestIndex = parsedEntries.length - 1;

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (containerRef.current && autoScroll && isExpanded) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries, autoScroll, isExpanded]);

  // Auto-expand latest entry
  useEffect(() => {
    if (parsedEntries.length > 0) {
      setExpandedEntries(new Set([parsedEntries.length - 1]));
    }
  }, [parsedEntries.length]);

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

  // Toggle entry expansion
  const toggleEntry = (index: number) => {
    setExpandedEntries(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  if (entries.length === 0) {
    return null;
  }

  const containerStyle = maxHeight !== undefined
    ? { maxHeight }
    : { flex: 1 };

  return (
    <div className="card h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2 flex-shrink-0">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 hover:opacity-80"
        >
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
          <Brain className="w-4 h-4 text-purple-400" />
          <h3 className="font-medium text-sm">Agent Reasoning</h3>
        </button>

        <span className="text-xs text-gray-400 ml-auto">
          {entries.length} entries
        </span>

        <button
          onClick={() => setShowAll(!showAll)}
          className="p-1 hover:bg-surface rounded transition-colors"
          title={showAll ? 'Show latest only' : 'Show all entries'}
        >
          {showAll ? (
            <EyeOff className="w-3.5 h-3.5 text-gray-400" />
          ) : (
            <Eye className="w-3.5 h-3.5 text-gray-400" />
          )}
        </button>

        <button
          onClick={copyToClipboard}
          className="p-1 hover:bg-surface rounded transition-colors"
          title="Copy to clipboard"
        >
          {copied ? (
            <Check className="w-3.5 h-3.5 text-green-400" />
          ) : (
            <Copy className="w-3.5 h-3.5 text-gray-400" />
          )}
        </button>
      </div>

      {isExpanded && (
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-gray-700"
          style={containerStyle}
        >
          {showAll ? (
            // Show all entries with collapse/expand
            parsedEntries.map((parsed, index) => (
              <CollapsibleLogEntry
                key={index}
                parsed={parsed}
                index={index}
                isExpanded={expandedEntries.has(index)}
                onToggle={() => toggleEntry(index)}
                isLatest={index === latestIndex}
              />
            ))
          ) : (
            // Show summary by agent type + latest entry
            <>
              {/* Agent Summary Pills */}
              <div className="flex flex-wrap gap-1 mb-2">
                {Array.from(groupedEntries.entries()).map(([agentType, { entries: agentEntries }]) => {
                  const config = Object.values(AGENT_CONFIG).find(c => c.agentType === agentType) || {
                    color: 'text-gray-400',
                    bgColor: 'bg-gray-500/10',
                    icon: Brain,
                  };
                  const Icon = config.icon;
                  return (
                    <div
                      key={agentType}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs ${config.bgColor} ${config.color}`}
                    >
                      <Icon className="w-3 h-3" />
                      <span>{agentType}</span>
                      <span className="opacity-60">({agentEntries.length})</span>
                    </div>
                  );
                })}
              </div>

              {/* Latest Entry - Always Expanded */}
              {latestEntry && (
                <div className="animate-slide-in">
                  <LogEntry parsed={latestEntry} index={latestIndex} />
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Show more indicator when collapsed */}
      {!isExpanded && entries.length > 0 && (
        <div className="text-xs text-gray-500 mt-1">
          Click to expand {entries.length} reasoning entries
        </div>
      )}
    </div>
  );
}

interface CollapsibleLogEntryProps {
  parsed: ParsedEntry;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
  isLatest: boolean;
}

function CollapsibleLogEntry({ parsed, index, isExpanded, onToggle, isLatest }: CollapsibleLogEntryProps) {
  const Icon = parsed.icon;

  return (
    <div
      className={`
        rounded-lg transition-all duration-200
        ${parsed.bgColor}
        ${isLatest ? 'ring-1 ring-blue-500/50' : ''}
      `}
    >
      {/* Header - Always visible */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 p-2 text-left hover:brightness-110"
      >
        {isExpanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        )}
        <Icon className={`w-4 h-4 flex-shrink-0 ${parsed.prefixColor}`} />
        <span className={`text-xs font-medium ${parsed.prefixColor}`}>
          {parsed.prefix || 'System'}
        </span>
        <span className="text-xs text-gray-500">#{index + 1}</span>
        {isLatest && (
          <span className="ml-auto text-xs text-blue-400 bg-blue-500/20 px-1.5 py-0.5 rounded">
            Latest
          </span>
        )}
      </button>

      {/* Content - Collapsible */}
      {isExpanded && (
        <div className="px-3 pb-2 pl-9">
          <MarkdownRenderer content={parsed.content} compact />
        </div>
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
        flex items-start gap-2 text-sm p-2.5 rounded-lg
        ${parsed.bgColor}
      `}
    >
      <div className="flex flex-col items-center gap-1 flex-shrink-0">
        <Icon className={`w-4 h-4 ${parsed.prefixColor}`} />
        <span className="text-xs text-gray-500">#{index + 1}</span>
      </div>
      <div className="flex-1 min-w-0">
        {parsed.prefix && (
          <div className={`font-semibold text-xs mb-1 ${parsed.prefixColor}`}>
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
