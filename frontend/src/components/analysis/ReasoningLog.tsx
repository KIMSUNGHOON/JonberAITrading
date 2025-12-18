/**
 * Reasoning Log Component
 *
 * Displays real-time agent reasoning process.
 */

import { useRef, useEffect } from 'react';
import { Brain, ChevronRight } from 'lucide-react';

interface ReasoningLogProps {
  entries: string[];
  maxHeight?: number;
}

export function ReasoningLog({ entries, maxHeight = 300 }: ReasoningLogProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries]);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Brain className="w-5 h-5 text-purple-400" />
        <h3 className="font-medium">Agent Reasoning</h3>
        <span className="text-xs text-gray-400 ml-auto">
          {entries.length} entries
        </span>
      </div>

      {/* Log Entries */}
      <div
        ref={containerRef}
        className="space-y-2 overflow-y-auto scrollbar-hide"
        style={{ maxHeight }}
      >
        {entries.map((entry, index) => (
          <LogEntry key={index} entry={entry} index={index} />
        ))}
      </div>
    </div>
  );
}

interface LogEntryProps {
  entry: string;
  index: number;
}

function LogEntry({ entry, index }: LogEntryProps) {
  // Parse entry to extract agent/stage info
  const parsed = parseEntry(entry);

  return (
    <div className="flex items-start gap-2 text-sm animate-fade-in">
      <ChevronRight className="w-4 h-4 text-gray-500 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        {parsed.prefix && (
          <span className={`font-medium ${parsed.prefixColor}`}>
            [{parsed.prefix}]
          </span>
        )}{' '}
        <span className="text-gray-300">{parsed.content}</span>
      </div>
      <span className="text-xs text-gray-500 flex-shrink-0">
        #{index + 1}
      </span>
    </div>
  );
}

interface ParsedEntry {
  prefix?: string;
  prefixColor: string;
  content: string;
}

function parseEntry(entry: string): ParsedEntry {
  // Check for [Agent] prefix pattern
  const match = entry.match(/^\[([^\]]+)\]\s*(.*)$/);

  if (match) {
    const prefix = match[1];
    const content = match[2];

    const colorMap: Record<string, string> = {
      Technical: 'text-blue-400',
      Fundamental: 'text-purple-400',
      Sentiment: 'text-yellow-400',
      Risk: 'text-red-400',
      Strategic: 'text-green-400',
      Execution: 'text-orange-400',
    };

    return {
      prefix,
      prefixColor: colorMap[prefix] || 'text-gray-400',
      content,
    };
  }

  return {
    prefixColor: '',
    content: entry,
  };
}
