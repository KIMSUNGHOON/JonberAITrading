/**
 * DiscoveryLedgerPanel — FI-4: 전용 발굴 조회 페이지.
 *
 * FI-2의 GET /trading/discovery/candidates · /performance 라우트를 그대로
 * 소비하는 드릴다운 뷰: 날짜/승격 필터로 discovery_candidates 원장을 훑고,
 * 전략 태그별 성과(승격 수·평균 fwd_1d/5d·hit_rate_5d)를 함께 보여준다.
 *
 * EOD 패널(PerformancePanel.tsx의 EodDiscoveryBlock, FI-3)은 "오늘"의
 * 스냅샷만 보여주는 반면, 이 페이지는 임의 과거 날짜/필터를 드릴다운할 수
 * 있는 전용 조회다 — 둘은 서로 다른 목적이라 겹치지 않는다.
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { useGoTo } from '@/hooks/useNav';
import { getDiscoveryCandidates, getDiscoveryPerformance } from '@/api/client';
import type { DiscoveryCandidate, DiscoveryPerformanceBucket } from '@/types';
import { Awaiting, TH, DASH } from './shared';
import UsSignalCard from './UsSignalCard';

interface DiscoveryLedgerPanelProps {
  onBack?: () => void;
}

export type PromotedFilter = 'all' | 'promoted' | 'skipped';

const PAGE_SIZE = 50;
const PERFORMANCE_WINDOWS = [7, 14, 30, 60] as const;

/** Pure filter-state -> query-param mapping (unit-tested independently). */
export function promotedFilterToParam(filter: PromotedFilter): boolean | undefined {
  if (filter === 'promoted') return true;
  if (filter === 'skipped') return false;
  return undefined;
}

/**
 * discovery_candidates.fwd_1d/5d/20d (and the performance bucket's
 * avg_fwd_1d/5d) are raw fractions ((price/close_price) - 1.0, see
 * ledger.py), NOT pre-scaled like cumulative_return_pct -- fmtPct() would
 * render 0.0123 as "+0.01%" instead of the intended "+1.23%". Duplicated
 * (not imported) from PerformancePanel.tsx's identically-documented local
 * helper of the same name: this task's global constraint (기존 패널·뷰
 * 무변경 -- additive 등록만) keeps that file untouched, and FI-3's own
 * fmtFwdPct is likewise a local, non-exported duplication of the same idea
 * relative to fmtPct -- this follows that established convention.
 */
function fmtFwdPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  const pct = n * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function fmtScore(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return n.toFixed(3);
}

function fmtClosePrice(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return `₩${Math.round(n).toLocaleString('ko-KR')}`;
}

function fmtHitRate(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return DASH;
  return `${(n * 100).toFixed(0)}%`;
}

export function DiscoveryLedgerPanel({ onBack }: DiscoveryLedgerPanelProps) {
  const goTo = useGoTo();

  // Candidate filters
  const [tradeDate, setTradeDate] = useState('');
  const [promotedFilter, setPromotedFilter] = useState<PromotedFilter>('all');
  const [page, setPage] = useState(0);

  // Performance window
  const [performanceDays, setPerformanceDays] = useState<number>(14);

  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(true);
  const [candidatesError, setCandidatesError] = useState<string | null>(null);

  const [performance, setPerformance] = useState<Record<string, DiscoveryPerformanceBucket>>({});
  const [performanceLoading, setPerformanceLoading] = useState(true);
  const [performanceError, setPerformanceError] = useState<string | null>(null);

  const loadCandidates = useCallback(async () => {
    setCandidatesLoading(true);
    setCandidatesError(null);
    try {
      const data = await getDiscoveryCandidates({
        trade_date: tradeDate || undefined,
        promoted: promotedFilterToParam(promotedFilter),
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setCandidates(data.candidates);
    } catch (err) {
      console.error('Failed to load discovery candidates:', err);
      setCandidatesError('발굴 후보를 불러오지 못했습니다.');
      setCandidates([]);
    } finally {
      setCandidatesLoading(false);
    }
  }, [tradeDate, promotedFilter, page]);

  const loadPerformance = useCallback(async () => {
    setPerformanceLoading(true);
    setPerformanceError(null);
    try {
      const data = await getDiscoveryPerformance(performanceDays);
      setPerformance(data.by_strategy_tag);
    } catch (err) {
      console.error('Failed to load discovery performance:', err);
      setPerformanceError('전략별 성과를 불러오지 못했습니다.');
      setPerformance({});
    } finally {
      setPerformanceLoading(false);
    }
  }, [performanceDays]);

  useEffect(() => {
    loadCandidates();
  }, [loadCandidates]);

  useEffect(() => {
    loadPerformance();
  }, [loadPerformance]);

  // Filter changes reset to page 0 -- a stale offset on a narrower result
  // set would otherwise silently show an empty page instead of the match.
  const handleDateChange = (v: string) => {
    setTradeDate(v);
    setPage(0);
  };
  const handlePromotedChange = (v: PromotedFilter) => {
    setPromotedFilter(v);
    setPage(0);
  };

  const handleBack = () => {
    if (onBack) onBack();
    else goTo('dashboard');
  };

  const performanceEntries = Object.entries(performance);

  return (
    <div className="h-full flex flex-col bg-canvas">
      {/* Header */}
      <div className="flex-none border-b border-hairline bg-card">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <button
            onClick={handleBack}
            className="p-1.5 hover:bg-elevated rounded transition-colors"
            title="Back to Dashboard"
          >
            <ArrowLeft className="w-4 h-4 text-muted" />
          </button>
          <div>
            <h1 className="text-sm font-semibold text-ink">발굴 원장</h1>
            <p className="text-[11px] text-dim">discovery_candidates 조회 · 날짜/승격 필터 · 전략별 성과</p>
          </div>
          <button
            onClick={() => {
              loadCandidates();
              loadPerformance();
            }}
            className="ml-auto flex items-center gap-1.5 px-2.5 py-1 bg-accent hover:bg-accent/90 text-canvas text-xs font-medium rounded transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${candidatesLoading || performanceLoading ? 'animate-spin' : ''}`} />
            새로고침
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-6xl mx-auto space-y-4">
          <UsSignalCard />

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-[11px] text-muted">
              날짜
              <input
                type="date"
                aria-label="날짜"
                value={tradeDate}
                onChange={(e) => handleDateChange(e.target.value)}
                className="px-2 py-1 bg-card border border-hairline rounded text-ink text-xs focus:outline-none focus:border-accent"
              />
            </label>
            {tradeDate && (
              <button
                onClick={() => handleDateChange('')}
                className="text-[11px] text-dim hover:text-ink underline"
              >
                날짜 필터 해제
              </button>
            )}
            <div className="flex gap-1">
              {(['all', 'promoted', 'skipped'] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => handlePromotedChange(f)}
                  className={`px-2.5 py-1 rounded-full text-[11px] transition-colors ${
                    promotedFilter === f
                      ? 'bg-accent text-canvas'
                      : 'bg-elevated text-ink hover:bg-hairline'
                  }`}
                >
                  {f === 'all' ? '전체' : f === 'promoted' ? '승격만' : '스킵만'}
                </button>
              ))}
            </div>
          </div>

          {candidatesError && (
            <div className="p-3 bg-down/10 border border-down/30 rounded text-down text-xs">
              {candidatesError}
            </div>
          )}

          {/* Candidates table */}
          <div className="bg-card rounded-lg border border-hairline overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] tabular-nums">
                <thead>
                  <tr>
                    <th className={`${TH} text-left`}>종목</th>
                    <th className={TH}>종합점수</th>
                    <th className={`${TH} text-left`}>최고기여전략</th>
                    <th className={`${TH} text-center`}>승격</th>
                    <th className={`${TH} text-left`}>스킵사유</th>
                    <th className={TH}>종가</th>
                    <th className={TH}>fwd 1d</th>
                    <th className={TH}>fwd 5d</th>
                    <th className={TH}>fwd 20d</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {candidatesLoading ? (
                    <tr>
                      <td colSpan={9} className="px-4 py-8 text-center text-dim">
                        <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                        로딩 중...
                      </td>
                    </tr>
                  ) : candidates.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="p-0">
                        <Awaiting label="발굴 이력 없음" />
                      </td>
                    </tr>
                  ) : (
                    candidates.map((c) => (
                      <tr key={c.id ?? `${c.ticker}-${c.trade_date}`} className="hover:bg-elevated/40 transition-colors">
                        <td className="text-left px-2.5 py-1.5">
                          <div className="text-ink truncate max-w-[140px]">{c.name ?? DASH}</div>
                          <div className="text-dim">{c.ticker ?? DASH}</div>
                        </td>
                        <td className="text-right px-2.5 py-1.5">{fmtScore(c.composite_score)}</td>
                        <td className="text-left px-2.5 py-1.5 text-muted">{c.top_strategy_tag ?? DASH}</td>
                        <td className="text-center px-2.5 py-1.5">
                          {c.promoted ? (
                            <span className="text-[9px] px-1 py-px rounded bg-accent/10 text-accent font-medium">
                              승격
                            </span>
                          ) : (
                            <span className="text-dim">—</span>
                          )}
                        </td>
                        <td className="text-left px-2.5 py-1.5 text-dim">{c.skip_reason ?? DASH}</td>
                        <td className="text-right px-2.5 py-1.5">{fmtClosePrice(c.close_price)}</td>
                        <td className="text-right px-2.5 py-1.5">{fmtFwdPct(c.fwd_1d)}</td>
                        <td className="text-right px-2.5 py-1.5">{fmtFwdPct(c.fwd_5d)}</td>
                        <td className="text-right px-2.5 py-1.5">{fmtFwdPct(c.fwd_20d)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="px-3 py-2 border-t border-hairline flex items-center justify-between text-[11px] text-muted">
              <span>{candidates.length}건 · 페이지 {page + 1}</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-2 py-1 rounded hover:bg-elevated disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  이전
                </button>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={candidates.length < PAGE_SIZE}
                  className="px-2 py-1 rounded hover:bg-elevated disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  다음
                </button>
              </div>
            </div>
          </div>

          {/* Performance summary */}
          <div className="bg-card rounded-lg border border-hairline p-3">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-[11px] uppercase tracking-wide text-muted font-semibold">전략별 성과</h2>
              <div className="flex gap-1">
                {PERFORMANCE_WINDOWS.map((d) => (
                  <button
                    key={d}
                    onClick={() => setPerformanceDays(d)}
                    className={`px-2 py-0.5 rounded text-[10px] ${
                      performanceDays === d
                        ? 'bg-accent text-canvas'
                        : 'bg-elevated text-ink hover:bg-hairline'
                    }`}
                  >
                    {d}일
                  </button>
                ))}
              </div>
            </div>
            {performanceError && (
              <div className="p-2 bg-down/10 border border-down/30 rounded text-down text-xs mb-2">
                {performanceError}
              </div>
            )}
            {performanceLoading ? (
              <div className="text-dim text-[11px] py-4 text-center">로딩 중...</div>
            ) : performanceEntries.length === 0 ? (
              <Awaiting label="성과 데이터 없음" />
            ) : (
              <table className="w-full text-[11px] tabular-nums">
                <thead>
                  <tr>
                    <th className={`${TH} text-left`}>전략</th>
                    <th className={TH}>후보</th>
                    <th className={TH}>승격</th>
                    <th className={TH}>평균 fwd 1d</th>
                    <th className={TH}>평균 fwd 5d</th>
                    <th className={TH}>hit rate 5d</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {performanceEntries.map(([tag, bucket]) => (
                    <tr key={tag}>
                      <td className="text-left px-2.5 py-1.5 text-ink">{tag}</td>
                      <td className="text-right px-2.5 py-1.5">{bucket.candidates}</td>
                      <td className="text-right px-2.5 py-1.5">{bucket.promoted}</td>
                      <td className="text-right px-2.5 py-1.5">{fmtFwdPct(bucket.avg_fwd_1d)}</td>
                      <td className="text-right px-2.5 py-1.5">{fmtFwdPct(bucket.avg_fwd_5d)}</td>
                      <td className="text-right px-2.5 py-1.5">{fmtHitRate(bucket.hit_rate_5d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default DiscoveryLedgerPanel;
