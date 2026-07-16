/**
 * 리스크 파라미터 편집 패널 (Task 4).
 *
 * `/trading/risk-params`(GET)로 전체 필드를 불러와 편집 컨트롤로 노출하고,
 * 저장 시 변경된 필드만 `PUT /trading/risk-params`로 보낸다(코디네이터가
 * 지정한 필드만 갱신하므로 unchanged 필드를 함께 보내도 무해하지만, 변경분만
 * 보내는 편이 의도를 명확히 한다).
 *
 * 1건당 명목 상한(`max_trade_notional_pct`)은 총 계좌 자산 대비 %로
 * 저장된다(과거 고정 ₩ 값에서 전환, 자율사이징 T4) — `totalEquity` prop으로
 * ₩ 환산값을 함께 보여준다. 백엔드 바운드(services/trading/models.py
 * RiskParameters.max_trade_notional_pct)는 [0.5, 50]이며, 이 컴포넌트는
 * 저장 전 동일 범위를 클라이언트에서도 검증한다.
 */
import { useEffect, useState } from 'react';

import { getTradingRiskParams, updateTradingRiskParams } from '../../api/client';
import type { StopLossMode } from '../../types';

const NOTIONAL_PCT_MIN = 0.5;
const NOTIONAL_PCT_MAX = 50;

interface RiskParamsFormState {
  max_trade_notional_pct: number;
  max_single_position_pct: number;
  min_cash_ratio: number;
  max_daily_loss_pct: number;
  max_open_positions: number;
  stop_loss_mode: StopLossMode;
  take_profit_mode: StopLossMode;
}

const DEFAULTS: RiskParamsFormState = {
  max_trade_notional_pct: 15,
  max_single_position_pct: 0.15,
  min_cash_ratio: 0.2,
  max_daily_loss_pct: 3,
  max_open_positions: 5,
  stop_loss_mode: 'user_approval',
  take_profit_mode: 'user_approval',
};

const STOP_MODES: { value: StopLossMode; label: string }[] = [
  { value: 'user_approval', label: '사용자 승인' },
  { value: 'agent_auto', label: '에이전트 자동' },
];

function normalize(raw: Record<string, unknown>): RiskParamsFormState {
  const num = (key: keyof RiskParamsFormState, fallback: number): number =>
    typeof raw[key] === 'number' ? (raw[key] as number) : fallback;
  const mode = (key: keyof RiskParamsFormState, fallback: StopLossMode): StopLossMode =>
    raw[key] === 'user_approval' || raw[key] === 'agent_auto'
      ? (raw[key] as StopLossMode)
      : fallback;
  return {
    max_trade_notional_pct: num('max_trade_notional_pct', DEFAULTS.max_trade_notional_pct),
    max_single_position_pct: num('max_single_position_pct', DEFAULTS.max_single_position_pct),
    min_cash_ratio: num('min_cash_ratio', DEFAULTS.min_cash_ratio),
    max_daily_loss_pct: num('max_daily_loss_pct', DEFAULTS.max_daily_loss_pct),
    max_open_positions: num('max_open_positions', DEFAULTS.max_open_positions),
    stop_loss_mode: mode('stop_loss_mode', DEFAULTS.stop_loss_mode),
    take_profit_mode: mode('take_profit_mode', DEFAULTS.take_profit_mode),
  };
}

function fieldKeys(): (keyof RiskParamsFormState)[] {
  return [
    'max_trade_notional_pct',
    'max_single_position_pct',
    'min_cash_ratio',
    'max_daily_loss_pct',
    'max_open_positions',
    'stop_loss_mode',
    'take_profit_mode',
  ];
}

export function RiskParamsPanel({ totalEquity }: { totalEquity: number }) {
  const [loaded, setLoaded] = useState<RiskParamsFormState | null>(null);
  const [form, setForm] = useState<RiskParamsFormState>(DEFAULTS);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTradingRiskParams()
      .then((data) => {
        if (cancelled) return;
        const next = normalize(data);
        setLoaded(next);
        setForm(next);
      })
      .catch(() => {
        if (!cancelled) setLoadError('리스크 파라미터 조회 실패 — 잠시 후 다시 시도하세요');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const notionalKrw = Math.round((form.max_trade_notional_pct / 100) * totalEquity);

  const setField = <K extends keyof RiskParamsFormState>(key: K, value: RiskParamsFormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setSaveError(null);
    setSavedAt(null);
  };

  const validate = (): string | null => {
    if (
      Number.isNaN(form.max_trade_notional_pct) ||
      form.max_trade_notional_pct < NOTIONAL_PCT_MIN ||
      form.max_trade_notional_pct > NOTIONAL_PCT_MAX
    ) {
      return `1건당 명목 상한은 ${NOTIONAL_PCT_MIN}~${NOTIONAL_PCT_MAX}% 범위여야 합니다`;
    }
    if (!Number.isFinite(form.max_open_positions) || form.max_open_positions < 1) {
      return '최대 동시 보유 종목 수는 1 이상이어야 합니다';
    }
    return null;
  };

  const handleSave = async () => {
    const validationError = validate();
    if (validationError) {
      setSaveError(validationError);
      return;
    }
    setSaveError(null);
    setSaving(true);
    try {
      const diff: Record<string, unknown> = {};
      for (const key of fieldKeys()) {
        if (loaded == null || form[key] !== loaded[key]) {
          diff[key] = form[key];
        }
      }
      await updateTradingRiskParams(diff);
      setLoaded(form);
      setSavedAt(Date.now());
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : '저장 실패 — 잠시 후 다시 시도하세요');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-card border border-hairline rounded p-4 font-mono">
      <h3 className="text-sm font-medium text-ink mb-3">리스크 파라미터</h3>

      <div className="space-y-3">
        <div>
          <label htmlFor="risk-notional-pct" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
            1건당 명목 상한 (%)
          </label>
          <div className="flex items-center gap-2">
            <input
              id="risk-notional-pct"
              type="number"
              step="0.5"
              min={NOTIONAL_PCT_MIN}
              max={NOTIONAL_PCT_MAX}
              value={form.max_trade_notional_pct}
              onChange={(e) => setField('max_trade_notional_pct', Number(e.target.value))}
              className="w-24 bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            />
            <input
              type="range"
              min={NOTIONAL_PCT_MIN}
              max={NOTIONAL_PCT_MAX}
              step="0.5"
              value={form.max_trade_notional_pct}
              onChange={(e) => setField('max_trade_notional_pct', Number(e.target.value))}
              className="flex-1"
              aria-label="명목 상한 조절 슬라이더"
            />
          </div>
          <div className="mt-1 text-sm text-ink tabular-nums">
            {form.max_trade_notional_pct}% (≈₩{notionalKrw.toLocaleString('ko-KR')})
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="risk-single-position-pct" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              종목당 최대 비중 (0~1)
            </label>
            <input
              id="risk-single-position-pct"
              type="number"
              step="0.01"
              min={0.01}
              max={0.5}
              value={form.max_single_position_pct}
              onChange={(e) => setField('max_single_position_pct', Number(e.target.value))}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            />
          </div>
          <div>
            <label htmlFor="risk-min-cash-ratio" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              최소 현금 비율 (0~1)
            </label>
            <input
              id="risk-min-cash-ratio"
              type="number"
              step="0.01"
              min={0}
              max={0.9}
              value={form.min_cash_ratio}
              onChange={(e) => setField('min_cash_ratio', Number(e.target.value))}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            />
          </div>
          <div>
            <label htmlFor="risk-daily-loss-pct" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              일일 손실 한도 (%)
            </label>
            <input
              id="risk-daily-loss-pct"
              type="number"
              step="0.1"
              min={0.1}
              max={20}
              value={form.max_daily_loss_pct}
              onChange={(e) => setField('max_daily_loss_pct', Number(e.target.value))}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            />
          </div>
          <div>
            <label htmlFor="risk-max-open-positions" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              최대 동시 보유 종목
            </label>
            <input
              id="risk-max-open-positions"
              type="number"
              step="1"
              min={1}
              max={50}
              value={form.max_open_positions}
              onChange={(e) => setField('max_open_positions', Number(e.target.value))}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            />
          </div>
          <div>
            <label htmlFor="risk-stop-loss-mode" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              손절 모드
            </label>
            <select
              id="risk-stop-loss-mode"
              value={form.stop_loss_mode}
              onChange={(e) => setField('stop_loss_mode', e.target.value as StopLossMode)}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            >
              {STOP_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="risk-take-profit-mode" className="block text-[11px] text-dim uppercase tracking-wide mb-1">
              익절 모드
            </label>
            <select
              id="risk-take-profit-mode"
              value={form.take_profit_mode}
              onChange={(e) => setField('take_profit_mode', e.target.value as StopLossMode)}
              className="w-full bg-elevated border border-hairline rounded px-2 py-1 text-sm text-ink"
            >
              {STOP_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {loadError && <p className="mt-3 text-[11px] text-down">{loadError}</p>}
      {saveError && <p className="mt-3 text-[11px] text-down">{saveError}</p>}
      {savedAt != null && !saveError && (
        <p className="mt-3 text-[11px] text-up">저장되었습니다</p>
      )}

      <button
        type="button"
        onClick={handleSave}
        disabled={saving || loaded == null}
        className="mt-3 inline-flex items-center px-3 py-1.5 rounded text-xs font-medium bg-accent text-canvas hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        저장
      </button>
    </div>
  );
}

export default RiskParamsPanel;
