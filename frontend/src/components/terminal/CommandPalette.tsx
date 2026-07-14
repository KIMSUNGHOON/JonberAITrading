// frontend/src/components/terminal/CommandPalette.tsx
// ⌘K modal: single input filters the static command registry (commands.ts)
// and runs the selected command. Pure logic (buildCommands/filterCommands)
// lives in commands.ts — this component owns only rendering + key handling.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '@/store';
import { useGoTo } from '@/hooks/useNav';
import { useStartAnalysis } from '@/hooks/useStartAnalysis';
import { startScan, startAgentChatDiscussion, createKRStockOrder, createCoinOrder } from '@/api/client';
import { Toast } from '@/components/ui/Toast';
import { buildCommands, filterCommands, type CommandCtx } from './commands';

// Section order in the results list — matches the group labels used in
// commands.ts (buildCommands).
const GROUP_ORDER = ['이동', '마켓', '액션'];

type Props = { open: boolean; onClose: () => void };

export function CommandPalette({ open, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // M1 (T7 review): :buy/:sell used to be fire-and-forget — success was
  // invisible and failure only reached the app-wide error Toast. This
  // component instance stays mounted for the app's lifetime (TerminalShell
  // renders it unconditionally, gating only its own JSX on `open`), so this
  // local toast survives the palette closing right after the command runs.
  const [orderResult, setOrderResult] = useState<{ kind: 'success' | 'error'; msg: string } | null>(null);

  const goTo = useGoTo();
  const setActiveMarket = useStore((s) => s.setActiveMarket);
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const setShowSettingsModal = useStore((s) => s.setShowSettingsModal);
  const setError = useStore((s) => s.setError);
  const start = useStartAnalysis();

  const ctx = useMemo<CommandCtx>(
    () => {
      // These three actions fire async work (start-analysis throws on failure;
      // startScan/startAgentChatDiscussion reject on API error). Surface any
      // failure through the app's error Toast instead of a silent unhandled
      // rejection. (start() switches the active market first, so setError lands
      // on the market being analyzed.)
      const fail = (msg: string) => (e: unknown) =>
        setError(`${msg}: ${e instanceof Error ? e.message : '요청 실패'}`);
      return {
        goTo,
        setActiveMarket,
        setChartSymbol,
        setShowSettingsModal,
        startAnalysis: (t) => {
          const m = useStore.getState().activeMarket;
          start(m, t).catch(fail(`분석 시작 실패 (${t})`));
        },
        startScan: () => {
          startScan().catch(fail('스캔 시작 실패'));
        },
        startDebate: (t) => {
          startAgentChatDiscussion({ ticker: t, stock_name: t }).catch(fail(`토론 시작 실패 (${t})`));
        },
        // P1-4 discretionary control surface: manual :buy/:sell. Resolves the
        // market from activeMarket at call time (same convention as
        // startAnalysis) and calls the SAME order-create endpoint the rest of
        // the app uses — no separate/bypassing execution path. Upbit has no
        // qty-based market-buy (its market-buy semantics take a KRW amount,
        // not a coin volume) so a coin :buy with no price is rejected instead
        // of silently reinterpreting qty as a KRW amount.
        //
        // M1 (T7 review): previously fire-and-forget (`.catch` only, no
        // success path) — a filled order gave the operator no visible
        // confirmation at all, and it doesn't create/update a row in
        // PositionsPanel (order-create doesn't touch the position store —
        // see task-7-fix-findings.md C2/M1), so the success message says so
        // honestly instead of implying the position list will reflect it.
        placeOrder: (side, sym, qty, px) => {
          const m = useStore.getState().activeMarket;
          const promise = m === 'coin'
            ? side === 'buy' && px == null
              ? Promise.reject(new Error('코인 시장가 매수는 미지원 — 가격을 지정하세요: :buy SYM QTY PX'))
              : createCoinOrder({
                  market: sym,
                  side: side === 'buy' ? 'bid' : 'ask',
                  ord_type: px != null ? 'limit' : 'market',
                  price: px,
                  volume: qty,
                })
            : createKRStockOrder({
                stk_cd: sym,
                side,
                ord_type: px != null ? 'limit' : 'market',
                price: px,
                quantity: qty,
              });
          promise.then(
            () => {
              setOrderResult({
                kind: 'success',
                msg: `:${side} ${sym} ${qty}${px != null ? ` @ ${px}` : ''} 주문 접수 완료 — `
                  + '수동 주문은 포지션 패널에 자동 반영되지 않습니다. 체결/보유량은 별도로 확인하세요.',
              });
            },
            (e: unknown) => {
              setOrderResult({
                kind: 'error',
                msg: `:${side} ${sym} 주문 실패: ${e instanceof Error ? e.message : '요청 실패'}`,
              });
            },
          );
        },
        reportError: (msg) => setError(msg),
      };
    },
    [goTo, setActiveMarket, setChartSymbol, setShowSettingsModal, setError, setOrderResult, start]
  );

  const commands = useMemo(() => buildCommands(ctx), [ctx]);
  const hits = useMemo(() => filterCommands(commands, query), [commands, query]);

  // Reset query + selection every time the palette opens — otherwise
  // reopening would show stale filter/selection state. Focus itself is
  // handled by the input's `autoFocus` prop below: since this component
  // returns null while closed, the input element fully unmounts/remounts
  // on every open, so autoFocus re-fires each time. (A requestAnimationFrame
  // fallback here would be less reliable — rAF is throttled/skipped in
  // backgrounded or automated tabs, which was observed to leave focus stuck
  // on the trigger button.)
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelected(0);
    }
  }, [open]);

  // Typing changes the result set — clamp selection back to the top so it
  // never points past the end of a shorter, freshly-filtered list.
  useEffect(() => {
    setSelected(0);
  }, [query]);

  // M1: independent of `open` — this is how a :buy/:sell result stays
  // visible even though the palette closes synchronously right after the
  // command runs (see `runAt` below), well before the order promise
  // settles.
  const orderToast = orderResult && (
    <Toast
      key={`${orderResult.kind}:${orderResult.msg}`}
      message={orderResult.msg}
      type={orderResult.kind}
      duration={6000}
      onClose={() => setOrderResult(null)}
    />
  );

  if (!open) return orderToast;

  const runAt = (idx: number) => {
    const hit = hits[idx];
    if (!hit) return;
    hit.command.run(ctx, hit.arg);
    onClose();
  };

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((s) => (hits.length ? (s + 1) % hits.length : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((s) => (hits.length ? (s - 1 + hits.length) % hits.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      runAt(selected);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  // Group the flat filtered list for display while keeping each item's flat
  // index so ↑/↓ selection (over the flat list) maps cleanly onto the
  // grouped rendering.
  const grouped = GROUP_ORDER.map((group) => ({
    group,
    items: hits
      .map((hit, idx) => ({ hit, idx }))
      .filter(({ hit }) => hit.command.group === group),
  })).filter((g) => g.items.length > 0);

  return (
    <>
      {orderToast}
      <div
        className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/50"
        onClick={onClose}
      >
        <div
          role="dialog"
          aria-modal="true"
          className="w-full max-w-[560px] bg-elevated border border-hairline rounded shadow-xl font-mono text-[13px] overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-2 px-3 py-2 border-b border-hairline">
            <span className="text-accent font-bold">❯</span>
            <input
              ref={inputRef}
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder=":analyze 005930 · :go positions · posi"
              className="flex-1 bg-transparent outline-none text-ink placeholder:text-dim"
            />
            <span className="text-[10px] text-dim border border-hairline rounded px-1.5">esc</span>
          </div>
          <div className="max-h-[360px] overflow-y-auto py-1">
            {hits.length === 0 && (
              <div className="px-3 py-4 text-dim text-center">일치하는 명령이 없습니다</div>
            )}
            {grouped.map(({ group, items }) => (
              <div key={group} className="py-1">
                <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-dim">{group}</div>
                {items.map(({ hit, idx }) => (
                  <button
                    key={hit.command.id}
                    type="button"
                    onClick={() => runAt(idx)}
                    onMouseEnter={() => setSelected(idx)}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 text-left ${
                      idx === selected ? 'bg-canvas text-ink' : 'text-muted hover:text-ink'
                    }`}
                  >
                    <span>{hit.command.title}</span>
                    {hit.arg && <span className="ml-auto text-dim text-[11px] tabular-nums">{hit.arg}</span>}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
