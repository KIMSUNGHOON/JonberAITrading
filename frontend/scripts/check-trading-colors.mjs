#!/usr/bin/env node
/**
 * Trading-color grep-gate (d-follow-2 t2).
 *
 * The app used to hardcode raw green/red Tailwind classes for buy/sell/up/down
 * signals in two contradicting conventions (Korean red-up vs Western green-up),
 * so the SAME P&L could render opposite colors depending on which component you
 * were looking at. d-follow + d-follow-2-t1 routed the highest-traffic panels
 * through `@/utils/pnl` (pnlColor/changeColor) as the single source of truth.
 * This script locks that in:
 *
 *   1. It ENUMERATES every remaining raw green/red hit across src/{components,pages}
 *      as "debt" — informational only, does not fail the build. This is the
 *      known-not-yet-gated backlog (most of the codebase still isn't unified).
 *   2. It GATES a hardcoded CLEAN_SET of files that are already unified: any raw
 *      green/red match in one of those files without an inline `color-ok:`
 *      escape-hatch comment is a VIOLATION and fails CI (exit 1). This is what
 *      stops a raw color from silently reappearing in a file we already fixed.
 *
 * Scope (v1, deliberate): only red/green are banned — those are the two colors
 * that encode trading direction (buy/sell, up/down, RISE/FALL) and that's what
 * caused the original bug. Blue/yellow are NOT banned here: blue is used for
 * plain identity/info accents and yellow for warn/pending states, neither of
 * which was ever part of the red/green direction-convention mixup. A future
 * version could widen scope; that's out of bounds for this task.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const FRONTEND_ROOT = join(__dirname, '..');
const SCAN_ROOTS = ['src/components', 'src/pages'];

// Whole-class-token match: text|bg + red|green + 400|500, optionally with a
// Tailwind opacity suffix like `/20`. `\b` on both ends keeps `bg-green-500`
// from also matching e.g. `bg-green-500x` (not a real Tailwind class anyway)
// while still matching `bg-green-500/20`.
const BANNED_PATTERN = /\b(?:text|bg)-(?:red|green)-(?:400|500)(?:\/\d{1,3})?\b/g;

// The escape hatch: any line with this literal substring is exempt. Reviewers
// check that the reason after the marker is genuinely non-directional (error
// banner / destructive action / success confirmation) — never a relabeled
// buy/sell/up/down color.
const ESCAPE_HATCH = 'color-ok';

// Files already unified through d-follow + d-follow-2-t1 (and this task).
// These MUST stay clean — a raw red/green here without `color-ok` fails CI.
const CLEAN_SET = [
  'src/pages/PositionsPage.tsx',
  'src/pages/ScannerResultsPage.tsx',
  'src/pages/WorkflowPage.tsx',
  'src/pages/AnalysisPage.tsx',
  'src/pages/AnalysisDetailPage.tsx',
  'src/pages/ChartsPage.tsx',
  'src/pages/TradesPage.tsx',
  'src/components/kiwoom/KiwoomPositionPanel.tsx',
  'src/components/kiwoom/KiwoomOpenOrders.tsx',
  'src/components/kiwoom/KiwoomAccountBalance.tsx',
  'src/components/kiwoom/KRStockPriceTicker.tsx',
  'src/components/kiwoom/KRStockTradeHistory.tsx',
  'src/components/coin/CoinPositionPanel.tsx',
  'src/components/coin/CoinOpenOrders.tsx',
  'src/components/coin/CoinAccountBalance.tsx',
  'src/components/coin/CoinInfo.tsx',
  'src/components/coin/CoinMarketList.tsx',
  'src/components/coin/CoinPriceTicker.tsx',
  'src/components/coin/CoinTradeHistory.tsx',
  // Spot-checked (d-follow-2 t2): already zero raw-color hits, added with no edits.
  'src/components/terminal/panels/ChartTile.tsx',
  'src/components/terminal/panels/DebatePanel.tsx',
  'src/components/terminal/panels/PortfolioPanel.tsx',
  'src/components/terminal/panels/PositionsPanel.tsx',
  'src/components/terminal/panels/ReasoningPanel.tsx',
  'src/components/terminal/panels/ScannerPanel.tsx',
  'src/components/terminal/panels/shared.tsx',
  'src/components/terminal/panels/WatchlistPanel.tsx',
  // d2 t2: Basket page + widget.
  'src/pages/BasketPage.tsx',
  'src/components/basket/BasketWidget.tsx',
  // d2 t3: Trading dashboard shell.
  'src/components/trading/TradingDashboard.tsx',
  // d2 t4: Trade queue + agent status widgets (BUY/SELL convention unification).
  'src/components/trading/TradeQueueWidget.tsx',
  'src/components/trading/AgentStatusWidget.tsx',
  // d2 t5: Watchlist + strategy-config widgets (signal/confidence/risk spectrums -> LEVEL tokens).
  'src/components/trading/WatchListWidget.tsx',
  'src/components/trading/StrategyConfigWidget.tsx',
  // d2 t6: Agent workflow graph + detail modal (BUY/SELL action map unification).
  'src/components/trading/AgentWorkflowGraph/index.tsx',
  'src/components/trading/AgentWorkflowGraph/AgentNode.tsx',
  'src/components/trading/AgentWorkflowGraph/AgentDetailModal.tsx',
  // d2 t7: Agent-chat dashboard + session list (statusConfig STATUS map,
  // decisionConfig DIRECTIONAL map -> pnlColor).
  'src/components/agent-chat/AgentChatDashboard.tsx',
  'src/components/agent-chat/ChatSessionList.tsx',
];
const CLEAN_SET_ABS = new Set(CLEAN_SET);

/** Recursively collect .ts/.tsx file paths (repo-relative, POSIX slashes) under a root. */
function collectFiles(absRoot) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const abs = join(dir, entry);
      const st = statSync(abs);
      if (st.isDirectory()) {
        walk(abs);
      } else if (/\.(ts|tsx)$/.test(entry)) {
        out.push(abs);
      }
    }
  };
  walk(absRoot);
  return out;
}

function scan() {
  const violations = []; // { file, line, match }
  const debtByFile = new Map(); // file -> count

  for (const root of SCAN_ROOTS) {
    const absRoot = join(FRONTEND_ROOT, root);
    let files;
    try {
      files = collectFiles(absRoot);
    } catch {
      continue; // root doesn't exist — nothing to scan
    }

    for (const absFile of files) {
      const relFile = relative(FRONTEND_ROOT, absFile).split('\\').join('/');
      const lines = readFileSync(absFile, 'utf8').split('\n');

      lines.forEach((line, idx) => {
        if (line.includes(ESCAPE_HATCH)) return; // justified, skip entirely

        const matches = line.match(BANNED_PATTERN);
        if (!matches) return;

        for (const m of matches) {
          if (CLEAN_SET_ABS.has(relFile)) {
            violations.push({ file: relFile, line: idx + 1, match: m });
          } else {
            debtByFile.set(relFile, (debtByFile.get(relFile) ?? 0) + 1);
          }
        }
      });
    }
  }

  return { violations, debtByFile };
}

function printDebtSummary(debtByFile) {
  console.log('--- Known raw-color debt (not yet gated) ---');
  const sorted = [...debtByFile.entries()].sort((a, b) => b[1] - a[1]);
  let total = 0;
  for (const [file, count] of sorted) {
    console.log(`  ${count}  ${file}`);
    total += count;
  }
  console.log(`Total debt: ${total} raw match(es) across ${sorted.length} file(s)`);
}

function main() {
  const reportOnly = process.argv.includes('--report');
  const { violations, debtByFile } = scan();

  if (reportOnly) {
    printDebtSummary(debtByFile);
    process.exit(0);
  }

  if (violations.length > 0) {
    console.log('=== VIOLATIONS (clean-set files with raw green/red) ===');
    for (const v of violations) {
      console.log(`VIOLATION  ${v.file}:${v.line}  ${v.match}`);
    }
    console.log('');
  }

  printDebtSummary(debtByFile);
  console.log('');

  if (violations.length > 0) {
    console.log(`FAIL: ${violations.length} violation(s) in the clean-set.`);
    process.exit(1);
  }

  console.log('PASS: clean-set has zero raw-color violations.');
  process.exit(0);
}

main();
