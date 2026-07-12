/**
 * 마켓별 트레이딩 모드(HITL | AUTONOMOUS) 토글 섹션 (R3).
 *
 * SettingsModal(General 탭)과 자율 운용 관제(/trading)가 공유한다 — R5-P2에서
 * SettingsModal 내부 함수를 추출. 응답이 진실의 원천(낙관적 업데이트 없음),
 * 마스터 게이트(AUTONOMY_ENABLED, env)가 꺼져 있으면 토글 비활성.
 */

import { useEffect, useState } from 'react';

import { getTradingMode, setTradingMode } from '@/api/client';
import { useStore } from '@/store';
import type { TradingMode } from '@/types';

const TRADING_MODE_MARKETS: { id: 'kiwoom' | 'coin'; label: string }[] = [
  { id: 'kiwoom', label: 'KR · KRX' },
  { id: 'coin', label: 'COIN' },
];

export function TradingModeSection({ onError }: { onError: (message: string) => void }) {
  const tradingModes = useStore((s) => s.tradingModes);
  const masterEnabled = useStore((s) => s.autonomyMasterEnabled);
  const setStoreTradingModes = useStore((s) => s.setTradingModes);
  const [saving, setSaving] = useState<'kiwoom' | 'coin' | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  // Fetch current modes on section mount.
  useEffect(() => {
    getTradingMode()
      .then((resp) => {
        setStoreTradingModes(resp);
        setLoadFailed(false);
      })
      .catch(() => setLoadFailed(true)); // modes stay null → toggles disabled
  }, [setStoreTradingModes]);

  const handleSelect = async (market: 'kiwoom' | 'coin', mode: TradingMode) => {
    if (!tradingModes || tradingModes[market] === mode) return;
    setSaving(market);
    try {
      // No optimistic update — the response is the source of truth.
      setStoreTradingModes(await setTradingMode(market, mode));
    } catch (err) {
      console.error(err);
      onError('트레이딩 모드 변경 실패 — 잠시 후 다시 시도하세요');
    } finally {
      setSaving(null);
    }
  };

  const disabled = !tradingModes || !masterEnabled || saving !== null;

  return (
    <div className="bg-card border border-hairline rounded p-4 font-mono">
      <h3 className="text-sm font-medium text-ink mb-3">트레이딩 모드</h3>
      <div className="space-y-2">
        {TRADING_MODE_MARKETS.map((m) => {
          const current = tradingModes?.[m.id] ?? null;
          return (
            <div key={m.id} className="flex items-center justify-between">
              <span className="text-sm text-muted tracking-wide">{m.label}</span>
              <div className="flex gap-0.5 border border-hairline rounded p-0.5 bg-elevated">
                {(['hitl', 'autonomous'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    disabled={disabled}
                    onClick={() => handleSelect(m.id, mode)}
                    className={`px-2 py-0.5 rounded text-[11px] tracking-wide uppercase disabled:cursor-not-allowed ${
                      disabled ? 'opacity-50' : ''
                    } ${
                      current === mode
                        ? mode === 'autonomous'
                          ? 'bg-card text-accent'
                          : 'bg-card text-ink'
                        : 'text-dim hover:text-ink'
                    }`}
                  >
                    {mode === 'hitl' ? 'HITL' : 'AUTONOMOUS'}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {loadFailed ? (
        <p className="mt-3 text-[11px] text-dim">모드 조회 실패 — 토글이 비활성화되었습니다</p>
      ) : tradingModes && !masterEnabled ? (
        <p className="mt-3 text-[11px] text-dim">
          AUTONOMY_ENABLED=false — .env에서 마스터 게이트를 켜야 적용됩니다
        </p>
      ) : null}
    </div>
  );
}
