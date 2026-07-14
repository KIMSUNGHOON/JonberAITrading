/**
 * Positions tile — live broker holdings for the active market.
 *
 * Data comes from REST (per-market), NOT the store: the store's activePosition
 * is a single analysis-derived object with no stop/take. Kiwoom + coin have
 * exact column matches. Polls every 10s, keyed on activeMarket so switching
 * the market tab re-fetches (the tile never remounts).
 *
 * P1-4 discretionary control surface: inline STOP/TAKE edit + full close.
 * These are OPERATOR-INITIATED manual actions, not autonomous ones.
 *
 * T7 review fixes (see .superpowers/sdd/task-7-fix-findings.md):
 * - C1: SL/TP save surfaces the backend's real outcome (including an honest
 *   error when the edit can't take effect anywhere) instead of assuming
 *   success — the fake-"updated" case was fixed backend-side
 *   (app/api/routes/trading.py), and the existing axios error interceptor
 *   already threads `detail` through to `e.message` here.
 * - M2: on a successful save, the row's local edit override is cleared so
 *   the field reverts to the freshly-refetched server value instead of
 *   echoing the typed value forever (which would hide a no-op).
 * - C2: 청산 is now FULL CLOSE ONLY via the dedicated
 *   `/positions/{id}/close` endpoints (closeKRStockPosition/
 *   closeCoinPosition) — these are the only routes that actually reduce
 *   the stored position (delete it, in this case). The previous
 *   qty/%-based "partial close" fired a raw sell order that never touched
 *   the position store, so a refetch kept showing the pre-close quantity
 *   while a real sell had gone out — a stale-state oversell hazard. Rather
 *   than add a new partial-reduce backend endpoint (higher-risk surface
 *   for a safety-adjacent control), partial close is disabled; a two-click
 *   confirm guards the destructive full close.
 */
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useStore, selectChartSymbol } from '@/store';
import {
  getKRStockPositions, getCoinPositions,
  updatePositionStopLoss, updatePositionTakeProfit,
  closeKRStockPosition, closeCoinPosition,
} from '@/api/client';
import { pnlColor } from '@/utils/pnl';
import { Awaiting, TH, DASH, fmtInt, fmtPct, fmtPrice } from './shared';

interface Row {
  sym: string;
  code: string; // chartable symbol: KR 6-digit code or coin KRW-XXX market
  qty: number;
  entry: number;
  cur: number;
  pnl: number;
  pnlPct: number;
  stop: number | null;
  take: number | null;
}

type FetchState = 'loading' | 'ready' | 'error';

function usePositions() {
  const activeMarket = useStore((s) => s.activeMarket);
  const [rows, setRows] = useState<Row[]>([]);
  const [state, setState] = useState<FetchState>('loading');
  const [err, setErr] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refetch = useCallback(async (showLoading = false) => {
    if (showLoading) setState('loading');
    setErr(null);
    try {
      if (activeMarket === 'kiwoom') {
        const res = await getKRStockPositions();
        if (!aliveRef.current) return;
        setRows(
          res.positions.map((p) => ({
            sym: p.stk_nm || p.stk_cd,
            code: p.stk_cd,
            qty: p.quantity,
            entry: p.avg_entry_price,
            cur: p.current_price,
            pnl: p.unrealized_pnl,
            pnlPct: p.unrealized_pnl_pct,
            stop: p.stop_loss,
            take: p.take_profit,
          })),
        );
      } else {
        const res = await getCoinPositions();
        if (!aliveRef.current) return;
        setRows(
          res.positions.map((p) => ({
            sym: p.currency || p.market,
            code: p.market,
            qty: p.quantity,
            entry: p.avg_entry_price,
            cur: p.current_price,
            pnl: p.unrealized_pnl,
            pnlPct: p.unrealized_pnl_pct,
            stop: p.stop_loss,
            take: p.take_profit,
          })),
        );
      }
      setState('ready');
    } catch (e) {
      if (!aliveRef.current) return;
      setErr(e instanceof Error ? e.message : '로드 실패');
      setState('error');
    }
  }, [activeMarket]);

  useEffect(() => {
    aliveRef.current = true;
    refetch(true);
    const id = setInterval(() => refetch(false), 10_000);
    return () => {
      aliveRef.current = false;
      clearInterval(id);
    };
  }, [refetch]);

  return { activeMarket, rows, state, err, refetch };
}

// Per-field local edit overrides, keyed by row code. A field is only
// present here while the operator has an in-progress edit that hasn't been
// saved yet; a successful save deletes the field's key so `editFor` falls
// back to the (freshly-refetched) server value again — see M2 in
// task-7-fix-findings.md. Deliberately per-field (not one blob per row) so
// clearing STOP on save doesn't clobber an in-progress TAKE edit.
type RowEdit = { stop?: string; take?: string };

function editValue(row: Row, edit: RowEdit | undefined, field: 'stop' | 'take'): string {
  const local = edit?.[field];
  if (local !== undefined) return local;
  const serverVal = row[field];
  return serverVal != null ? String(serverVal) : '';
}

export function PositionsPanel() {
  const { activeMarket, rows, state, err, refetch } = usePositions();
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const chartSymbol = useStore(selectChartSymbol);

  const [edits, setEdits] = useState<Record<string, RowEdit>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [busyRow, setBusyRow] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);

  const setField = (code: string, field: 'stop' | 'take', value: string) => {
    setEdits((prev) => ({ ...prev, [code]: { ...(prev[code] ?? {}), [field]: value } }));
  };

  // Deletes the field's override entirely (not set to '') so editValue()
  // falls back to the server value on the next render — that's what
  // actually reveals a no-op instead of echoing the typed value forever.
  const clearField = (code: string, field: 'stop' | 'take') => {
    setEdits((prev) => {
      const rowEdit = prev[code];
      if (!rowEdit || !(field in rowEdit)) return prev;
      const next = { ...rowEdit };
      delete next[field];
      return { ...prev, [code]: next };
    });
  };

  const setRowErr = (code: string, msg: string | null) => {
    setRowError((prev) => {
      const next = { ...prev };
      if (msg == null) delete next[code];
      else next[code] = msg;
      return next;
    });
  };

  async function handleSaveStop(row: Row) {
    const raw = editValue(row, edits[row.code], 'stop').trim();
    const val = Number(raw);
    if (!raw || !Number.isFinite(val) || val <= 0) {
      setRowErr(row.code, `손절가가 올바르지 않습니다: "${raw}"`);
      return;
    }
    setBusyRow(row.code);
    try {
      await updatePositionStopLoss(row.code, val);
      setRowErr(row.code, null);
      // C1/M2: only treat this as a real change once the backend confirms
      // it took effect somewhere (risk_monitor OR the coin position store —
      // see trading.py). refetch() BEFORE clearing the override so the
      // field flips straight to the true post-save server value with no
      // flash of a stale one.
      await refetch();
      clearField(row.code, 'stop');
    } catch (e) {
      setRowErr(row.code, `손절가 저장 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
    } finally {
      setBusyRow(null);
    }
  }

  async function handleSaveTake(row: Row) {
    const raw = editValue(row, edits[row.code], 'take').trim();
    const val = Number(raw);
    if (!raw || !Number.isFinite(val) || val <= 0) {
      setRowErr(row.code, `익절가가 올바르지 않습니다: "${raw}"`);
      return;
    }
    setBusyRow(row.code);
    try {
      await updatePositionTakeProfit(row.code, val);
      setRowErr(row.code, null);
      await refetch();
      clearField(row.code, 'take');
    } catch (e) {
      setRowErr(row.code, `익절가 저장 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
    } finally {
      setBusyRow(null);
    }
  }

  // C2: full close ONLY. The dedicated /positions/{id}/close endpoints are
  // the only routes that actually reduce the stored position (they delete
  // it on success), so this is the one action guaranteed not to leave a
  // stale, too-large quantity behind. A raw sell order for a partial
  // amount does NOT touch the position store — see task-7-fix-findings.md
  // C2 — so partial close is intentionally not offered here. Two-click
  // confirm guards the destructive action (mirrors the existing
  // CoinPositionPanel/KiwoomPositionPanel convention).
  async function handleFullClose(row: Row) {
    if (confirmClose !== row.code) {
      setConfirmClose(row.code);
      return;
    }
    setConfirmClose(null);
    setBusyRow(row.code);
    try {
      if (activeMarket === 'kiwoom') {
        await closeKRStockPosition(row.code);
      } else {
        await closeCoinPosition(row.code);
      }
      setRowErr(row.code, null);
      await refetch();
    } catch (e) {
      setRowErr(row.code, `청산 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
    } finally {
      setBusyRow(null);
    }
  }

  if (state === 'loading') return <Awaiting label="포지션 로드 중…" />;
  if (state === 'error') return <Awaiting label={`포지션 오류 · ${err ?? '연결 실패'}`} />;
  if (rows.length === 0) return <Awaiting label="보유 포지션 없음 · 체결 시 표시" />;

  return (
    <table className="w-full text-[12px] tabular-nums">
      <thead>
        <tr>
          <th className={`${TH} text-left`}>SYM</th>
          <th className={TH}>QTY</th>
          <th className={TH}>ENTRY</th>
          <th className={TH}>CUR</th>
          <th className={TH}>P&amp;L</th>
          <th className={TH}>%</th>
          <th className={TH}>STOP</th>
          <th className={TH}>TAKE</th>
          <th className={TH} title="부분청산은 지원되지 않습니다 — 전량 매도만 가능합니다 (두 번 클릭하여 확인)">청산</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const rowEdit = edits[r.code];
          const stopVal = editValue(r, rowEdit, 'stop');
          const takeVal = editValue(r, rowEdit, 'take');
          const busy = busyRow === r.code;
          const armed = confirmClose === r.code;
          return (
            <Fragment key={`${r.code}-${i}`}>
              <tr
                onClick={() => setChartSymbol(r.code)}
                title="차트에 표시"
                className={`border-b border-hairline/60 cursor-pointer hover:bg-elevated/40 ${
                  chartSymbol === r.code ? 'bg-elevated/60' : ''
                }`}
              >
                <td className="text-left px-2.5 py-1 font-semibold truncate max-w-[120px]">{r.sym}</td>
                <td className="text-right px-2.5 py-1">{fmtInt(r.qty)}</td>
                <td className="text-right px-2.5 py-1 text-muted">{fmtPrice(r.entry, activeMarket)}</td>
                <td className="text-right px-2.5 py-1">{fmtPrice(r.cur, activeMarket)}</td>
                <td className={`text-right px-2.5 py-1 ${pnlColor(r.pnl)}`}>{fmtInt(r.pnl)}</td>
                <td className={`text-right px-2.5 py-1 ${pnlColor(r.pnlPct)}`}>{fmtPct(r.pnlPct)}</td>
                <td className="text-right px-1.5 py-1 text-dim" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-1 justify-end">
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label={`손절가 편집 ${r.code}`}
                      value={stopVal}
                      onChange={(e) => setField(r.code, 'stop', e.target.value)}
                      placeholder={r.stop != null ? undefined : DASH}
                      className="w-16 bg-canvas border border-hairline rounded px-1 py-0.5 text-right text-[11px] tabular-nums text-ink"
                    />
                    <button
                      type="button"
                      aria-label={`손절가 저장 ${r.code}`}
                      disabled={busy}
                      onClick={() => handleSaveStop(r)}
                      className="text-accent text-[10px] font-medium disabled:opacity-50"
                    >
                      저장
                    </button>
                  </div>
                </td>
                <td className="text-right px-1.5 py-1 text-dim" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-1 justify-end">
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label={`익절가 편집 ${r.code}`}
                      value={takeVal}
                      onChange={(e) => setField(r.code, 'take', e.target.value)}
                      placeholder={r.take != null ? undefined : DASH}
                      className="w-16 bg-canvas border border-hairline rounded px-1 py-0.5 text-right text-[11px] tabular-nums text-ink"
                    />
                    <button
                      type="button"
                      aria-label={`익절가 저장 ${r.code}`}
                      disabled={busy}
                      onClick={() => handleSaveTake(r)}
                      className="text-accent text-[10px] font-medium disabled:opacity-50"
                    >
                      저장
                    </button>
                  </div>
                </td>
                <td className="text-right px-1.5 py-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    aria-label={`전량청산 ${r.code}`}
                    title="부분청산 미지원 — 전량 매도만 가능합니다"
                    disabled={busy}
                    onClick={() => handleFullClose(r)}
                    className="text-warn text-[10px] font-medium disabled:opacity-50"
                  >
                    {armed ? '확인?' : '청산'}
                  </button>
                </td>
              </tr>
              {rowError[r.code] && (
                <tr>
                  <td colSpan={9} className="px-2.5 py-1 text-[11px] text-down bg-down/5">
                    {rowError[r.code]}
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
