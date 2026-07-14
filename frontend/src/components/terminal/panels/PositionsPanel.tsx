/**
 * Positions tile — live broker holdings for the active market.
 *
 * Data comes from REST (per-market), NOT the store: the store's activePosition
 * is a single analysis-derived object with no stop/take. Kiwoom + coin have
 * exact column matches. Polls every 10s, keyed on activeMarket so switching
 * the market tab re-fetches (the tile never remounts).
 *
 * P1-4 discretionary control surface: inline STOP/TAKE edit + partial close.
 * These are OPERATOR-INITIATED manual actions, not autonomous ones — they go
 * through the same order/positions endpoints the rest of the app uses
 * (createKRStockOrder/createCoinOrder, updatePositionStopLoss/TakeProfit),
 * never a separate execution path. Partial close is implemented as a manual
 * sell order for the entered qty/% rather than the dedicated
 * `/positions/{id}/close` endpoints — those only support closing the FULL
 * position (no qty param exists on them), so a manual sell order is the
 * correct primitive for a partial reduction (see task-7 report for detail).
 */
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useStore, selectChartSymbol } from '@/store';
import {
  getKRStockPositions, getCoinPositions,
  updatePositionStopLoss, updatePositionTakeProfit,
  createKRStockOrder, createCoinOrder,
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

type RowEdit = { stop: string; take: string; close: string };

function initEdit(row: Row): RowEdit {
  return {
    stop: row.stop != null ? String(row.stop) : '',
    take: row.take != null ? String(row.take) : '',
    close: '',
  };
}

/**
 * Resolves a partial-close "qty or %" field into a concrete sell quantity.
 * `wholeUnits` (true for KR shares, false for coin volumes) enforces integer
 * quantities where the market requires them. Returns null for anything
 * malformed or exceeding the held quantity — callers must reject, never
 * silently clamp.
 */
export function resolvePartialQty(raw: string, heldQty: number, wholeUnits: boolean): number | null {
  const trimmed = raw.trim();
  if (!trimmed || heldQty <= 0) return null;

  let qty: number;
  if (trimmed.endsWith('%')) {
    const pct = Number(trimmed.slice(0, -1));
    if (!Number.isFinite(pct) || pct <= 0 || pct > 100) return null;
    qty = (heldQty * pct) / 100;
    if (wholeUnits) qty = Math.floor(qty);
  } else {
    qty = Number(trimmed);
  }

  if (!Number.isFinite(qty) || qty <= 0 || qty > heldQty) return null;
  if (wholeUnits && !Number.isInteger(qty)) return null;
  return qty;
}

export function PositionsPanel() {
  const { activeMarket, rows, state, err, refetch } = usePositions();
  const setChartSymbol = useStore((s) => s.setChartSymbol);
  const chartSymbol = useStore(selectChartSymbol);

  const [edits, setEdits] = useState<Record<string, RowEdit>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [busyRow, setBusyRow] = useState<string | null>(null);

  const editFor = (row: Row): RowEdit => edits[row.code] ?? initEdit(row);

  const setField = (row: Row, field: keyof RowEdit, value: string) => {
    setEdits((prev) => ({ ...prev, [row.code]: { ...(prev[row.code] ?? initEdit(row)), [field]: value } }));
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
    const raw = editFor(row).stop.trim();
    const val = Number(raw);
    if (!raw || !Number.isFinite(val) || val <= 0) {
      setRowErr(row.code, `손절가가 올바르지 않습니다: "${raw}"`);
      return;
    }
    setBusyRow(row.code);
    try {
      await updatePositionStopLoss(row.code, val);
      setRowErr(row.code, null);
      await refetch();
    } catch (e) {
      setRowErr(row.code, `손절가 저장 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
    } finally {
      setBusyRow(null);
    }
  }

  async function handleSaveTake(row: Row) {
    const raw = editFor(row).take.trim();
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
    } catch (e) {
      setRowErr(row.code, `익절가 저장 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
    } finally {
      setBusyRow(null);
    }
  }

  async function handleClose(row: Row) {
    const raw = editFor(row).close.trim();
    const qty = resolvePartialQty(raw, row.qty, activeMarket === 'kiwoom');
    if (qty == null) {
      setRowErr(row.code, `청산 수량/비율이 올바르지 않습니다: "${raw}"`);
      return;
    }
    setBusyRow(row.code);
    try {
      if (activeMarket === 'kiwoom') {
        await createKRStockOrder({ stk_cd: row.code, side: 'sell', ord_type: 'market', quantity: qty });
      } else {
        await createCoinOrder({ market: row.code, side: 'ask', ord_type: 'market', volume: qty });
      }
      setRowErr(row.code, null);
      setField(row, 'close', '');
      await refetch();
    } catch (e) {
      setRowErr(row.code, `청산 주문 실패: ${e instanceof Error ? e.message : '요청 실패'}`);
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
          <th className={TH}>청산</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const edit = editFor(r);
          const busy = busyRow === r.code;
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
                      value={edit.stop}
                      onChange={(e) => setField(r, 'stop', e.target.value)}
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
                      value={edit.take}
                      onChange={(e) => setField(r, 'take', e.target.value)}
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
                  <div className="flex items-center gap-1 justify-end">
                    <input
                      type="text"
                      aria-label={`부분청산 수량 ${r.code}`}
                      value={edit.close}
                      onChange={(e) => setField(r, 'close', e.target.value)}
                      placeholder="수량/%"
                      className="w-14 bg-canvas border border-hairline rounded px-1 py-0.5 text-right text-[11px] tabular-nums text-ink placeholder:text-dim"
                    />
                    <button
                      type="button"
                      aria-label={`부분청산 실행 ${r.code}`}
                      disabled={busy}
                      onClick={() => handleClose(r)}
                      className="text-warn text-[10px] font-medium disabled:opacity-50"
                    >
                      청산
                    </button>
                  </div>
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
