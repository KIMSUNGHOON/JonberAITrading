/**
 * StrategyConfigWidget Component
 *
 * Allows users to configure their trading strategy:
 * - Select from presets (conservative, growth, technical, value)
 * - Customize entry/exit conditions
 * - Set system prompt for AI behavior
 * - View current strategy settings
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Settings,
  Save,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Sliders,
  Shield,
  TrendingUp,
  Target,
  MessageSquare,
  AlertCircle,
  Check,
} from 'lucide-react';
import {
  getStrategyPresets,
  getCurrentStrategy,
  applyStrategyPreset,
  setStrategy,
  clearStrategy,
} from '@/api/client';
import type {
  TradingStrategyResponse,
  RiskTolerance,
  TradingStyle,
  StrategyPreset,
} from '@/types';

// -------------------------------------------
// Constants
// -------------------------------------------

// Risk-tolerance LEVEL (not P&L): low-risk=up, mid=warn, high-risk=down.
const RISK_TOLERANCE_LABELS: Record<RiskTolerance, { label: string; color: string }> = {
  conservative: { label: '보수적', color: 'text-up' },
  moderate: { label: '중립적', color: 'text-warn' },
  aggressive: { label: '공격적', color: 'text-down' },
};

const TRADING_STYLE_LABELS: Record<TradingStyle, string> = {
  value: '가치투자',
  growth: '성장주 투자',
  momentum: '모멘텀 투자',
  swing: '스윙 트레이딩',
  position: '포지션 트레이딩',
  dividend: '배당 투자',
};

const PRESET_LABELS: Record<StrategyPreset, { label: string; icon: React.ReactNode }> = {
  conservative_income: { label: '안정적 배당투자', icon: <Shield className="w-4 h-4" /> },
  growth_momentum: { label: '성장 모멘텀', icon: <TrendingUp className="w-4 h-4" /> },
  technical_breakout: { label: '기술적 돌파', icon: <Target className="w-4 h-4" /> },
  value_investing: { label: '가치 투자', icon: <Sliders className="w-4 h-4" /> },
  custom: { label: '사용자 정의', icon: <Settings className="w-4 h-4" /> },
};

// System Prompt Examples
const SYSTEM_PROMPT_EXAMPLES = [
  {
    label: '보수적 투자',
    prompt: `당신은 보수적인 투자 전략을 따르는 투자 에이전트입니다.

주요 원칙:
1. 손실 최소화를 최우선으로 합니다
2. 안정적인 배당 수익이 있는 우량주를 선호합니다
3. 변동성이 높은 종목은 피합니다
4. 장기 보유를 전제로 투자합니다

투자 판단 시 고려사항:
- PER, PBR이 업종 평균 이하인가
- 배당 수익률이 2% 이상인가
- 부채비율이 100% 이하인가`,
  },
  {
    label: '성장주 투자',
    prompt: `당신은 고성장 기업에 투자하는 적극적인 투자 에이전트입니다.

주요 원칙:
1. 높은 매출/이익 성장률을 가진 기업을 찾습니다
2. 시장을 선도하는 혁신 기업을 선호합니다
3. 적정 수준의 손실은 감수합니다
4. 모멘텀이 강한 종목에 집중합니다

투자 판단 시 고려사항:
- 연간 매출 성장률 20% 이상인가
- 산업 내 리더십이 있는가
- 긍정적 뉴스와 시장 관심이 있는가`,
  },
  {
    label: '기술적 분석',
    prompt: `당신은 기술적 분석 기반 매매를 하는 투자 에이전트입니다.

주요 원칙:
1. 차트 패턴과 기술적 지표를 중시합니다
2. 지지선/저항선 돌파 시점을 포착합니다
3. 거래량 동반 상승을 확인합니다
4. 빠른 손절과 익절을 실행합니다

투자 판단 시 고려사항:
- RSI가 30 이하(과매도) 또는 70 이상(과매수)인가
- MACD 골든크로스/데드크로스 여부
- 이동평균선 배열 상태`,
  },
  {
    label: '가치 투자',
    prompt: `당신은 벤저민 그레이엄 스타일의 가치 투자자입니다.

주요 원칙:
1. 내재가치 대비 저평가된 종목을 찾습니다
2. 안전마진(Margin of Safety)을 중시합니다
3. 재무제표 분석을 철저히 합니다
4. 단기 시세 변동에 흔들리지 않습니다

투자 판단 시 고려사항:
- PER이 업종 평균 대비 낮은가
- PBR이 1 이하인가
- ROE가 꾸준히 10% 이상인가
- 현금흐름이 양호한가`,
  },
];

// -------------------------------------------
// Sub-components
// -------------------------------------------

interface PresetCardProps {
  preset: string;
  info: {
    name: string;
    description: string;
    risk_tolerance: string;
    trading_style: string;
  };
  isSelected: boolean;
  onSelect: () => void;
}

function PresetCard({ preset, info, isSelected, onSelect }: PresetCardProps) {
  const presetKey = preset as StrategyPreset;
  const presetLabel = PRESET_LABELS[presetKey];

  return (
    <button
      onClick={onSelect}
      className={`w-full p-4 rounded-lg border text-left transition-all ${
        isSelected
          ? 'border-accent bg-accent/10'
          : 'border-hairline bg-elevated/50 hover:border-dim'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-lg ${isSelected ? 'bg-accent/20 text-accent' : 'bg-elevated text-muted'}`}>
          {presetLabel?.icon || <Settings className="w-4 h-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-ink">{info.name}</span>
            {isSelected && <Check className="w-4 h-4 text-accent" />}
          </div>
          <p className="text-sm text-muted mt-1 line-clamp-2">{info.description}</p>
          <div className="flex items-center gap-3 mt-2 text-xs">
            <span className={RISK_TOLERANCE_LABELS[info.risk_tolerance as RiskTolerance]?.color || 'text-muted'}>
              {RISK_TOLERANCE_LABELS[info.risk_tolerance as RiskTolerance]?.label || info.risk_tolerance}
            </span>
            <span className="text-dim">|</span>
            <span className="text-muted">
              {TRADING_STYLE_LABELS[info.trading_style as TradingStyle] || info.trading_style}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

interface ConditionSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  unit?: string;
  onChange: (value: number) => void;
}

function ConditionSlider({ label, value, min, max, unit = '', onChange }: ConditionSliderProps) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-muted">{label}</span>
        <span className="text-ink tabular-nums">{value}{unit}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-2 bg-elevated rounded-lg appearance-none cursor-pointer accent-accent"
      />
    </div>
  );
}

// -------------------------------------------
// Main Component
// -------------------------------------------

interface StrategyConfigWidgetProps {
  onStrategyChange?: (strategy: TradingStrategyResponse | null) => void;
}

export default function StrategyConfigWidget({ onStrategyChange }: StrategyConfigWidgetProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Strategy state
  const [currentStrategy, setCurrentStrategy] = useState<TradingStrategyResponse | null>(null);
  const [presets, setPresets] = useState<Record<string, {
    name: string;
    description: string;
    risk_tolerance: string;
    trading_style: string;
  }>>({});
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);

  // Expanded sections
  const [expandedSections, setExpandedSections] = useState({
    presets: true,
    entry: false,
    exit: false,
    position: false,
    prompt: false,
  });

  // Custom configuration
  const [customConfig, setCustomConfig] = useState({
    entryConditions: {
      min_technical_score: 50,
      min_fundamental_score: 50,
      min_sentiment_score: 40,
      max_risk_score: 70,
    },
    exitConditions: {
      stop_loss_pct: 7,
      take_profit_pct: 15,
    },
    positionSizing: {
      max_position_pct: 10,
      min_cash_ratio: 20,
    },
    systemPrompt: '',
  });

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      setError(null);
      setLoading(true);

      const [presetsData, strategyData] = await Promise.all([
        getStrategyPresets(),
        getCurrentStrategy(),
      ]);

      setPresets(presetsData.presets);

      if ('id' in strategyData) {
        setCurrentStrategy(strategyData);
        setSelectedPreset(strategyData.preset);

        // Initialize custom config from current strategy
        setCustomConfig({
          entryConditions: {
            min_technical_score: strategyData.entry_conditions.min_technical_score,
            min_fundamental_score: strategyData.entry_conditions.min_fundamental_score,
            min_sentiment_score: strategyData.entry_conditions.min_sentiment_score,
            max_risk_score: strategyData.entry_conditions.max_risk_score,
          },
          exitConditions: {
            stop_loss_pct: Math.round(strategyData.exit_conditions.stop_loss_pct * 100),
            take_profit_pct: Math.round(strategyData.exit_conditions.take_profit_pct * 100),
          },
          positionSizing: {
            max_position_pct: Math.round(strategyData.position_sizing.max_position_pct * 100),
            min_cash_ratio: Math.round(strategyData.position_sizing.min_cash_ratio * 100),
          },
          systemPrompt: strategyData.system_prompt,
        });
      } else {
        setCurrentStrategy(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load strategy data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Toggle section
  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  // Apply preset
  const handleApplyPreset = async (presetName: string) => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const result = await applyStrategyPreset(presetName);
      setCurrentStrategy(result.strategy);
      setSelectedPreset(presetName);

      // Update custom config
      setCustomConfig({
        entryConditions: {
          min_technical_score: result.strategy.entry_conditions.min_technical_score,
          min_fundamental_score: result.strategy.entry_conditions.min_fundamental_score,
          min_sentiment_score: result.strategy.entry_conditions.min_sentiment_score,
          max_risk_score: result.strategy.entry_conditions.max_risk_score,
        },
        exitConditions: {
          stop_loss_pct: Math.round(result.strategy.exit_conditions.stop_loss_pct * 100),
          take_profit_pct: Math.round(result.strategy.exit_conditions.take_profit_pct * 100),
        },
        positionSizing: {
          max_position_pct: Math.round(result.strategy.position_sizing.max_position_pct * 100),
          min_cash_ratio: Math.round(result.strategy.position_sizing.min_cash_ratio * 100),
        },
        systemPrompt: result.strategy.system_prompt,
      });

      setSuccess(`전략 적용: ${result.strategy.name}`);
      onStrategyChange?.(result.strategy);

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply preset');
    } finally {
      setSaving(false);
    }
  };

  // Save custom strategy
  const handleSaveCustom = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const result = await setStrategy({
        name: '사용자 정의 전략',
        description: '사용자가 커스터마이징한 매매 전략',
        preset: selectedPreset || undefined,
        system_prompt: customConfig.systemPrompt,
        entry_conditions: {
          min_technical_score: customConfig.entryConditions.min_technical_score,
          min_fundamental_score: customConfig.entryConditions.min_fundamental_score,
          min_sentiment_score: customConfig.entryConditions.min_sentiment_score,
          max_risk_score: customConfig.entryConditions.max_risk_score,
        },
        exit_conditions: {
          stop_loss_pct: customConfig.exitConditions.stop_loss_pct / 100,
          take_profit_pct: customConfig.exitConditions.take_profit_pct / 100,
        },
        position_sizing: {
          max_position_pct: customConfig.positionSizing.max_position_pct / 100,
          min_cash_ratio: customConfig.positionSizing.min_cash_ratio / 100,
        },
      });

      setCurrentStrategy(result.strategy);
      setSuccess('전략이 저장되었습니다');
      onStrategyChange?.(result.strategy);

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save strategy');
    } finally {
      setSaving(false);
    }
  };

  // Clear strategy
  const handleClearStrategy = async () => {
    try {
      setSaving(true);
      setError(null);

      await clearStrategy();
      setCurrentStrategy(null);
      setSelectedPreset(null);
      setSuccess('전략이 해제되었습니다');
      onStrategyChange?.(null);

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear strategy');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-card rounded p-6 border border-hairline">
        <div className="flex items-center justify-center h-32">
          <RefreshCw className="w-6 h-6 animate-spin text-accent" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card rounded border border-hairline">
      {/* Header */}
      <div className="p-4 border-b border-hairline">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-accent" />
            <h2 className="text-lg font-semibold text-ink">Trading Strategy</h2>
          </div>
          <div className="flex items-center gap-2">
            {currentStrategy && (
              <button
                onClick={handleClearStrategy}
                disabled={saving}
                className="px-3 py-1.5 text-sm text-muted hover:text-ink disabled:opacity-50"
              >
                Reset
              </button>
            )}
            <button
              onClick={fetchData}
              disabled={loading}
              className="p-2 text-muted hover:text-ink hover:bg-elevated rounded-lg"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Current Strategy Status */}
        {currentStrategy && (
          <div className="mt-3 p-3 bg-accent/10 border border-accent/30 rounded-lg">
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-accent" />
              <span className="text-sm text-accent">
                활성 전략: {currentStrategy.name}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Messages */}
      {error && (
        <div className="mx-4 mt-4 p-3 bg-down/20 border border-down/30 rounded-lg flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-down" />
          <span className="text-sm text-down">{error}</span>
        </div>
      )}
      {success && (
        <div className="mx-4 mt-4 p-3 bg-up/20 border border-up/30 rounded-lg flex items-center gap-2">
          <Check className="w-4 h-4 text-up" />
          <span className="text-sm text-up">{success}</span>
        </div>
      )}

      {/* Sections */}
      <div className="p-4 space-y-4">
        {/* Preset Selection */}
        <div>
          <button
            onClick={() => toggleSection('presets')}
            className="w-full flex items-center justify-between p-2 text-left"
          >
            <span className="font-medium text-ink">전략 프리셋</span>
            {expandedSections.presets ? (
              <ChevronUp className="w-4 h-4 text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted" />
            )}
          </button>

          {expandedSections.presets && (
            <div className="mt-2 space-y-2">
              {Object.entries(presets).map(([key, info]) => (
                <PresetCard
                  key={key}
                  preset={key}
                  info={info}
                  isSelected={selectedPreset === key}
                  onSelect={() => handleApplyPreset(key)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Entry Conditions */}
        <div className="border-t border-hairline pt-4">
          <button
            onClick={() => toggleSection('entry')}
            className="w-full flex items-center justify-between p-2 text-left"
          >
            <span className="font-medium text-ink">진입 조건</span>
            {expandedSections.entry ? (
              <ChevronUp className="w-4 h-4 text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted" />
            )}
          </button>

          {expandedSections.entry && (
            <div className="mt-3 space-y-4 px-2">
              <ConditionSlider
                label="최소 기술적 점수"
                value={customConfig.entryConditions.min_technical_score}
                min={0}
                max={100}
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    entryConditions: { ...prev.entryConditions, min_technical_score: v },
                  }))
                }
              />
              <ConditionSlider
                label="최소 펀더멘털 점수"
                value={customConfig.entryConditions.min_fundamental_score}
                min={0}
                max={100}
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    entryConditions: { ...prev.entryConditions, min_fundamental_score: v },
                  }))
                }
              />
              <ConditionSlider
                label="최소 감성 점수"
                value={customConfig.entryConditions.min_sentiment_score}
                min={0}
                max={100}
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    entryConditions: { ...prev.entryConditions, min_sentiment_score: v },
                  }))
                }
              />
              <ConditionSlider
                label="최대 리스크 점수"
                value={customConfig.entryConditions.max_risk_score}
                min={0}
                max={100}
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    entryConditions: { ...prev.entryConditions, max_risk_score: v },
                  }))
                }
              />
            </div>
          )}
        </div>

        {/* Exit Conditions */}
        <div className="border-t border-hairline pt-4">
          <button
            onClick={() => toggleSection('exit')}
            className="w-full flex items-center justify-between p-2 text-left"
          >
            <span className="font-medium text-ink">청산 조건</span>
            {expandedSections.exit ? (
              <ChevronUp className="w-4 h-4 text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted" />
            )}
          </button>

          {expandedSections.exit && (
            <div className="mt-3 space-y-4 px-2">
              <ConditionSlider
                label="손절 비율"
                value={customConfig.exitConditions.stop_loss_pct}
                min={1}
                max={30}
                unit="%"
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    exitConditions: { ...prev.exitConditions, stop_loss_pct: v },
                  }))
                }
              />
              <ConditionSlider
                label="익절 비율"
                value={customConfig.exitConditions.take_profit_pct}
                min={5}
                max={100}
                unit="%"
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    exitConditions: { ...prev.exitConditions, take_profit_pct: v },
                  }))
                }
              />
            </div>
          )}
        </div>

        {/* Position Sizing */}
        <div className="border-t border-hairline pt-4">
          <button
            onClick={() => toggleSection('position')}
            className="w-full flex items-center justify-between p-2 text-left"
          >
            <span className="font-medium text-ink">포지션 설정</span>
            {expandedSections.position ? (
              <ChevronUp className="w-4 h-4 text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted" />
            )}
          </button>

          {expandedSections.position && (
            <div className="mt-3 space-y-4 px-2">
              <ConditionSlider
                label="최대 포지션 비율"
                value={customConfig.positionSizing.max_position_pct}
                min={1}
                max={50}
                unit="%"
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    positionSizing: { ...prev.positionSizing, max_position_pct: v },
                  }))
                }
              />
              <ConditionSlider
                label="최소 현금 비율"
                value={customConfig.positionSizing.min_cash_ratio}
                min={0}
                max={90}
                unit="%"
                onChange={(v) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    positionSizing: { ...prev.positionSizing, min_cash_ratio: v },
                  }))
                }
              />
            </div>
          )}
        </div>

        {/* System Prompt */}
        <div className="border-t border-hairline pt-4">
          <button
            onClick={() => toggleSection('prompt')}
            className="w-full flex items-center justify-between p-2 text-left"
          >
            <div className="flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-purple-400" /> {/* color-ok: system-prompt category identity, not directional */}
              <span className="font-medium text-ink">System Prompt</span>
            </div>
            {expandedSections.prompt ? (
              <ChevronUp className="w-4 h-4 text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-muted" />
            )}
          </button>

          {expandedSections.prompt && (
            <div className="mt-3 px-2">
              {/* Example Buttons */}
              <div className="mb-3">
                <p className="text-xs text-muted mb-2">예시 템플릿:</p>
                <div className="flex flex-wrap gap-2">
                  {SYSTEM_PROMPT_EXAMPLES.map((example, idx) => (
                    <button
                      key={idx}
                      onClick={() =>
                        setCustomConfig((prev) => ({
                          ...prev,
                          systemPrompt: example.prompt,
                        }))
                      }
                      className="px-2.5 py-1 text-xs bg-purple-500/10 text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/20 transition-colors" // color-ok: system-prompt category identity, not directional
                    >
                      {example.label}
                    </button>
                  ))}
                </div>
              </div>

              <textarea
                value={customConfig.systemPrompt}
                onChange={(e) =>
                  setCustomConfig((prev) => ({
                    ...prev,
                    systemPrompt: e.target.value,
                  }))
                }
                placeholder="AI 투자 에이전트의 투자 철학과 원칙을 입력하세요..."
                rows={8}
                className="w-full p-3 bg-elevated border border-hairline rounded-lg text-sm text-ink placeholder-dim focus:border-accent focus:outline-none resize-none"
              />
              <p className="mt-2 text-xs text-dim">
                AI가 투자 결정을 내릴 때 따를 원칙과 철학을 자연어로 작성하세요.
              </p>
            </div>
          )}
        </div>

        {/* Save Button */}
        <div className="border-t border-hairline pt-4">
          <button
            onClick={handleSaveCustom}
            disabled={saving}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-accent hover:bg-accent/90 text-canvas rounded-lg disabled:opacity-50"
          >
            {saving ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saving ? '저장 중...' : '전략 저장'}
          </button>
        </div>
      </div>
    </div>
  );
}
