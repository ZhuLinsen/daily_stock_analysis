import type React from 'react';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronUp, ExternalLink, Minus, X } from 'lucide-react';
import { backtestApi } from '../api/backtest';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { ApiErrorAlert, Card, Badge, EmptyState, Pagination, StatusDot, Tooltip } from '../components/common';
import { BacktestQuantInsights } from '../components/backtest/BacktestQuantInsights';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText, type UiLanguage } from '../i18n/uiText';
import { BACKTEST_QUANT_TEXT } from '../locales/backtestQuantText';
import {
  BACKTEST_DIRECTION_EXPECTED_LABELS,
  BACKTEST_MOVEMENT_LABELS,
  BACKTEST_OUTCOME_LABELS,
  BACKTEST_PHASE_FILTER_OPTIONS,
  BACKTEST_PHASE_LABELS,
  BACKTEST_STATUS_LABELS,
  BACKTEST_TEXT,
} from '../locales/featureText';
import type {
  BacktestResultItem,
  BacktestRunResponse,
  PerformanceMetrics,
  BacktestPhaseFilter,
} from '../types/backtest';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../utils/decisionAction';
import { getMarketPhaseSummaryLabel } from '../utils/marketPhase';

const BACKTEST_INPUT_CLASS =
  'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
const BACKTEST_COMPACT_INPUT_CLASS =
  'input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 py-2 text-xs transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';
type BacktestText = (typeof BACKTEST_TEXT)[UiLanguage];

interface AppliedBacktestFilters {
  code?: string;
  windowDays?: number;
  analysisDateFrom?: string;
  analysisDateTo?: string;
  phase: BacktestPhaseFilter;
}

// ============ Helpers ============

function pct(value?: number | null): string {
  if (value == null) return '--';
  return `${value.toFixed(1)}%`;
}

function phaseLabel(row: BacktestResultItem, language: UiLanguage): string {
  const label = getMarketPhaseSummaryLabel(row.marketPhaseSummary, language);
  if (label) {
    return label
      .replace('市场阶段: ', '')
      .replace('市场阶段：', '')
      .replace('Market phase: ', '');
  }
  return (row.marketPhase ? BACKTEST_PHASE_LABELS[language][row.marketPhase] : undefined) || row.marketPhase || '--';
}

function normalizeBacktestCode(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return trimmed.toUpperCase();
}

function parseEvalWindowDays(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed = parseInt(trimmed, 10);
  if (Number.isNaN(parsed) || parsed < 1) {
    return undefined;
  }

  return parsed;
}

function labelFromMap(value: string | null | undefined, labels: Record<string, string>): string {
  if (!value) return '--';
  return labels[value] ?? value;
}

function outcomeBadge(outcome: string | undefined, language: UiLanguage) {
  const labels = BACKTEST_OUTCOME_LABELS[language];
  if (!outcome) return <Badge variant="default">--</Badge>;
  switch (outcome) {
    case 'win':
      return <Badge variant="success" glow>{labels.win}</Badge>;
    case 'loss':
      return <Badge variant="danger" glow>{labels.loss}</Badge>;
    case 'neutral':
      return <Badge variant="warning">{labels.neutral}</Badge>;
    default:
      return <Badge variant="default">{outcome}</Badge>;
  }
}

function classifySimulatedPnl(row: BacktestResultItem): 'win' | 'loss' | 'neutral' | null {
  if (typeof row.simulatedReturnPct !== 'number' || !Number.isFinite(row.simulatedReturnPct)) {
    return null;
  }
  if (row.simulatedReturnPct > 0) return 'win';
  if (row.simulatedReturnPct < 0) return 'loss';
  return 'neutral';
}

function statusBadge(status: string, language: UiLanguage) {
  const labels = BACKTEST_STATUS_LABELS[language];
  switch (status) {
    case 'completed':
      return <Badge variant="success">{labels.completed}</Badge>;
    case 'insufficient':
    case 'insufficient_data':
      return <Badge variant="warning">{labels.insufficient}</Badge>;
    case 'error':
      return <Badge variant="danger">{labels.error}</Badge>;
    default:
      return <Badge variant="default">{status}</Badge>;
  }
}

function actualMovementBadge(movement: string | null | undefined, language: UiLanguage) {
  const labels = BACKTEST_MOVEMENT_LABELS[language];
  switch (movement) {
    case 'up':
      return <Badge variant="success">{labels.up}</Badge>;
    case 'down':
      return <Badge variant="danger">{labels.down}</Badge>;
    case 'flat':
      return <Badge variant="warning">{labels.flat}</Badge>;
    default:
      return <Badge variant="default">--</Badge>;
  }
}

function boolIcon(value: boolean | null | undefined, text: BacktestText) {
  if (value === true) {
    return (
      <span
        className="backtest-status-chip backtest-status-chip-success"
        aria-label={text.yes}
      >
        <StatusDot tone="success" className="backtest-status-chip-dot" />
        <Check className="h-3.5 w-3.5" />
      </span>
    );
  }

  if (value === false) {
    return (
      <span
        className="backtest-status-chip backtest-status-chip-danger"
        aria-label={text.no}
      >
        <StatusDot tone="danger" className="backtest-status-chip-dot" />
        <X className="h-3.5 w-3.5" />
      </span>
    );
  }

  return (
    <span
      className="backtest-status-chip backtest-status-chip-neutral"
      aria-label={text.unknown}
    >
      <StatusDot tone="neutral" className="backtest-status-chip-dot" />
      <Minus className="h-3.5 w-3.5" />
    </span>
  );
}

// ============ Metric Row ============

const MetricRow: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div className="backtest-metric-row">
    <span className="label">{label}</span>
    <span className={`value ${accent ? 'accent' : ''}`}>{value}</span>
  </div>
);

function phaseBreakdownText(metrics: PerformanceMetrics, language: UiLanguage): string | null {
  const breakdown = metrics.diagnostics?.phaseBreakdown;
  if (!breakdown || typeof breakdown !== 'object') return null;
  const item = breakdown as Record<string, unknown>;
  const phaseLabels = BACKTEST_PHASE_LABELS[language];
  const parts = [
    [phaseLabels.premarket, item.premarket],
    [phaseLabels.intraday, item.intraday],
    [phaseLabels.postmarket, item.postmarket],
    [phaseLabels.unknown, item.unknown],
  ]
    .map(([label, value]) => `${label} ${Number(value || 0)}`)
    .join(' / ');
  return parts;
}

// ============ Performance Card ============

const PerformanceCard: React.FC<{ metrics: PerformanceMetrics; title: string; language: UiLanguage }> = ({ metrics, title, language }) => {
  const text = BACKTEST_TEXT[language];
  const phaseText = phaseBreakdownText(metrics, language);
  return (
    <Card variant="gradient" padding="md" className="animate-fade-in">
      <div className="mb-3">
        <span className="label-uppercase">{title}</span>
      </div>
      <MetricRow label={text.directionAccuracy} value={pct(metrics.directionAccuracyPct)} accent />
      <MetricRow label={text.winRate} value={pct(metrics.winRatePct)} accent />
      <MetricRow label={text.avgSimulatedReturn} value={pct(metrics.avgSimulatedReturnPct)} />
      <MetricRow label={text.avgStockReturn} value={pct(metrics.avgStockReturnPct)} />
      <MetricRow label={text.stopLossTriggerRate} value={pct(metrics.stopLossTriggerRate)} />
      <MetricRow label={text.takeProfitTriggerRate} value={pct(metrics.takeProfitTriggerRate)} />
      <MetricRow label={text.avgDaysToFirstHit} value={metrics.avgDaysToFirstHit != null ? metrics.avgDaysToFirstHit.toFixed(1) : '--'} />
      <div className="backtest-metric-footer">
        <span className="text-xs text-muted-text">{text.evaluationCount}</span>
        <span className="text-xs text-secondary-text font-mono">
          {Number(metrics.completedCount)} / {Number(metrics.totalEvaluations)}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-text">{text.outcomeSummary}</span>
        <span className="text-xs font-mono">
          <span className="text-success">{metrics.winCount}</span>
          {' / '}
          <span className="text-danger">{metrics.lossCount}</span>
          {' / '}
          <span className="text-warning">{metrics.neutralCount}</span>
        </span>
      </div>
      {phaseText ? (
        <div className="mt-3 border-t border-white/10 pt-2 text-xs text-muted-text">
          {formatUiText(text.phaseDistribution, { text: phaseText })}
        </div>
      ) : null}
    </Card>
  );
};

// ============ Run Summary ============

const RunSummary: React.FC<{ data: BacktestRunResponse; language: UiLanguage }> = ({ data, language }) => {
  const text = BACKTEST_TEXT[language];
  return (
  <div className="backtest-summary animate-fade-in">
    <span className="label">{text.processed} <span className="value">{data.processed}</span></span>
    <span className="label">{text.saved} <span className="value primary">{data.saved}</span></span>
    <span className="label">{text.completed} <span className="value success">{data.completed}</span></span>
    <span className="label">{text.insufficient} <span className="value warning">{data.insufficient}</span></span>
    {data.errors > 0 && (
      <span className="label">{text.errors} <span className="value danger">{data.errors}</span></span>
    )}
    {data.message && (
      <span className="label message">{data.message}</span>
    )}
  </div>
  );
};

// ============ Main Page ============

function fmtPrice(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(2);
}

function fmtSignedPct(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

const BacktestPage: React.FC = () => {
  const { language, t } = useUiLanguage();
  const text = BACKTEST_TEXT[language];
  const qt = BACKTEST_QUANT_TEXT[language];
  const phaseFilterOptions = BACKTEST_PHASE_FILTER_OPTIONS[language];
  const actionLabels = buildDecisionActionLabelMap(t);

  // Set page title
  useEffect(() => {
    document.title = text.documentTitle;
  }, [text.documentTitle]);

  // Input state
  const [codeFilter, setCodeFilter] = useState('');
  const [analysisDateFrom, setAnalysisDateFrom] = useState('');
  const [analysisDateTo, setAnalysisDateTo] = useState('');
  const [phaseFilter, setPhaseFilter] = useState<BacktestPhaseFilter>('all');
  const [evalDays, setEvalDays] = useState('');
  const [forceRerun, setForceRerun] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState<BacktestRunResponse | null>(null);
  const [runError, setRunError] = useState<ParsedApiError | null>(null);
  const [resultsRefreshError, setResultsRefreshError] = useState<ParsedApiError | null>(null);
  const [paginationError, setPaginationError] = useState<ParsedApiError | null>(null);
  const [perfError, setPerfError] = useState<ParsedApiError | null>(null);
  const pageError = paginationError ?? resultsRefreshError ?? perfError;

  // Results state
  const [results, setResults] = useState<BacktestResultItem[]>([]);
  const [totalResults, setTotalResults] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoadingResults, setIsLoadingResults] = useState(false);
  const [outcomeFilter, setOutcomeFilter] = useState<'all' | 'win' | 'loss' | 'neutral'>('all');
  const [sortBy, setSortBy] = useState<'default' | 'sim_desc' | 'sim_asc' | 'stock_desc'>('default');
  const [expandedIds, setExpandedIds] = useState<Record<number, boolean>>({});
  const pageSize = 20;

  // Performance state
  const [overallPerf, setOverallPerf] = useState<PerformanceMetrics | null>(null);
  const [stockPerf, setStockPerf] = useState<PerformanceMetrics | null>(null);
  const [isLoadingPerf, setIsLoadingPerf] = useState(false);
  const [appliedFilters, setAppliedFilters] = useState<AppliedBacktestFilters>({ phase: 'all' });
  const mountedRef = useRef(true);
  const resultsRequestIdRef = useRef(0);
  const perfRequestIdRef = useRef(0);
  const evalDaysEditedRef = useRef(false);
  const effectiveWindowDays = appliedFilters.windowDays;
  const isNextDayValidation = effectiveWindowDays === 1;
  const showNextDayActualColumns = isNextDayValidation;

  const outcomeCounts = useMemo(() => {
    const counts = { all: results.length, win: 0, loss: 0, neutral: 0 };
    for (const row of results) {
      const bucket = classifySimulatedPnl(row);
      if (bucket === 'win') counts.win += 1;
      else if (bucket === 'loss') counts.loss += 1;
      else if (bucket === 'neutral') counts.neutral += 1;
    }
    return counts;
  }, [results]);

  const filteredSortedResults = useMemo(() => {
    const filtered = outcomeFilter === 'all'
      ? results
      : results.filter((row) => classifySimulatedPnl(row) === outcomeFilter);
    if (sortBy === 'default') return filtered;
    const copy = [...filtered];
    copy.sort((a, b) => {
      if (sortBy === 'sim_desc') {
        return (b.simulatedReturnPct ?? Number.NEGATIVE_INFINITY) - (a.simulatedReturnPct ?? Number.NEGATIVE_INFINITY);
      }
      if (sortBy === 'sim_asc') {
        return (a.simulatedReturnPct ?? Number.POSITIVE_INFINITY) - (b.simulatedReturnPct ?? Number.POSITIVE_INFINITY);
      }
      return (b.actualReturnPct ?? Number.NEGATIVE_INFINITY) - (a.actualReturnPct ?? Number.NEGATIVE_INFINITY);
    });
    return copy;
  }, [results, outcomeFilter, sortBy]);

  const toggleRowExpand = (historyId: number) => {
    setExpandedIds((prev) => ({ ...prev, [historyId]: !prev[historyId] }));
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      resultsRequestIdRef.current += 1;
      perfRequestIdRef.current += 1;
    };
  }, []);

  // Fetch results
  const fetchResults = useCallback(async (
    page = 1,
    code?: string,
    windowDays?: number,
    startDate?: string,
    endDate?: string,
    phase?: BacktestPhaseFilter,
    options?: { isPagination?: boolean },
  ) => {
    const requestId = ++resultsRequestIdRef.current;
    const isPagination = Boolean(options?.isPagination);
    setIsLoadingResults(true);
    try {
      const response = await backtestApi.getResults({
        code: code || undefined,
        evalWindowDays: windowDays,
        analysisDateFrom: startDate || undefined,
        analysisDateTo: endDate || undefined,
        analysisPhase: phase && phase !== 'all' ? phase : undefined,
        page,
        limit: pageSize,
      });
      if (!mountedRef.current || requestId !== resultsRequestIdRef.current) {
        return;
      }
      setResults(response.items);
      setExpandedIds({});
      setTotalResults(response.total);
      setCurrentPage(response.page);
      setAppliedFilters({
        code,
        windowDays,
        analysisDateFrom: startDate || undefined,
        analysisDateTo: endDate || undefined,
        phase: phase ?? 'all',
      });
      if (isPagination) {
        setPaginationError(null);
      } else {
        setOutcomeFilter('all');
        setResultsRefreshError(null);
        setPaginationError(null);
      }
    } catch (err) {
      if (!mountedRef.current || requestId !== resultsRequestIdRef.current) {
        return;
      }
      console.error('Failed to fetch backtest results:', err);
      const parsedErr = getParsedApiError(err);
      if (isPagination) {
        setPaginationError(parsedErr);
      } else {
        setResultsRefreshError(parsedErr);
        setPaginationError(null);
      }
    } finally {
      if (mountedRef.current && requestId === resultsRequestIdRef.current) {
        setIsLoadingResults(false);
      }
    }
  }, []);

  // Fetch performance
  const fetchPerformance = useCallback((
    code?: string,
    windowDays?: number,
    startDate?: string,
    endDate?: string,
    phase?: BacktestPhaseFilter,
  ) => {
    const requestId = ++perfRequestIdRef.current;
    const params = {
      evalWindowDays: windowDays,
      analysisDateFrom: startDate || undefined,
      analysisDateTo: endDate || undefined,
      analysisPhase: phase && phase !== 'all' ? phase : undefined,
    };
    setIsLoadingPerf(true);
    let pending = code ? 2 : 1;
    let overallError: ParsedApiError | null = null;
    let stockError: ParsedApiError | null = null;
    if (!code) {
      setStockPerf(null);
    }

    const markSettled = () => {
      if (!mountedRef.current || requestId !== perfRequestIdRef.current) {
        return;
      }
      setPerfError(overallError ?? stockError);
      pending -= 1;
      if (pending === 0) {
        setIsLoadingPerf(false);
      }
    };

    void backtestApi.getOverallPerformance(params).then(
      (overallValue) => {
        if (!mountedRef.current || requestId !== perfRequestIdRef.current) {
          return;
        }
        setOverallPerf(overallValue);
        overallError = null;
        markSettled();
      },
      (reason) => {
        if (!mountedRef.current || requestId !== perfRequestIdRef.current) {
          return;
        }
        console.error('Failed to fetch overall performance:', reason);
        overallError = getParsedApiError(reason);
        markSettled();
      },
    );

    if (code) {
      void backtestApi.getStockPerformance(code, params).then(
        (stockValue) => {
          if (!mountedRef.current || requestId !== perfRequestIdRef.current) {
            return;
          }
          setStockPerf(stockValue);
          stockError = null;
          markSettled();
        },
        (reason) => {
          if (!mountedRef.current || requestId !== perfRequestIdRef.current) {
            return;
          }
          console.error('Failed to fetch stock performance:', reason);
          setStockPerf(null);
          stockError = getParsedApiError(reason);
          markSettled();
        },
      );
    }
  }, []);

  // Initial load — fetch performance first, then filter results by its window
  useEffect(() => {
    const initRequestId = ++perfRequestIdRef.current;
    const init = async () => {
      setIsLoadingPerf(true);
      let windowDays: number | undefined;
      try {
        // Get latest performance (unfiltered returns most recent summary)
        const overall = await backtestApi.getOverallPerformance();
        if (!mountedRef.current || initRequestId !== perfRequestIdRef.current) {
          return;
        }
        setOverallPerf(overall);
        setPerfError(null);
        // Use the summary's eval_window_days to filter results consistently
        windowDays = overall?.evalWindowDays;
        if (windowDays && !evalDaysEditedRef.current) {
          setEvalDays((current) => current || String(windowDays));
        }
      } catch (err) {
        if (!mountedRef.current || initRequestId !== perfRequestIdRef.current) {
          return;
        }
        console.error('Failed to fetch initial performance:', err);
        setPerfError(getParsedApiError(err));
      } finally {
        if (mountedRef.current && initRequestId === perfRequestIdRef.current) {
          setIsLoadingPerf(false);
        }
      }

      if (!mountedRef.current || initRequestId !== perfRequestIdRef.current) {
        return;
      }
      await fetchResults(1, undefined, windowDays, undefined, undefined, 'all');
    };
    void init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Run backtest
  const handleRun = async () => {
    setIsRunning(true);
    setRunResult(null);
    setRunError(null);
    try {
      const code = normalizeBacktestCode(codeFilter);
      const requestedEvalWindowDays = parseEvalWindowDays(evalDays);
      const dateFrom = analysisDateFrom || undefined;
      const dateTo = analysisDateTo || undefined;
      const response = await backtestApi.run({
        code,
        force: forceRerun || undefined,
        minAgeDays: forceRerun ? 0 : undefined,
        evalWindowDays: requestedEvalWindowDays,
        analysisDateFrom: dateFrom,
        analysisDateTo: dateTo,
      });
      if (!mountedRef.current) {
        return;
      }
      setRunResult(response);
      const effectiveEvalWindowDays =
        response.appliedEvalWindowDays
        ?? requestedEvalWindowDays
        ?? parseEvalWindowDays(evalDays)
        ?? overallPerf?.evalWindowDays;
      if (effectiveEvalWindowDays != null) {
        evalDaysEditedRef.current = true;
        setEvalDays(String(effectiveEvalWindowDays));
      }
      // Refresh data with same eval_window_days; currentPage and appliedFilters commit when results resolve.
      void fetchResults(1, code, effectiveEvalWindowDays, dateFrom, dateTo, phaseFilter);
      void fetchPerformance(code, effectiveEvalWindowDays, dateFrom, dateTo, phaseFilter);
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setRunError(getParsedApiError(err));
    } finally {
      if (mountedRef.current) {
        setIsRunning(false);
      }
    }
  };

  // Filter by code
  const handleFilter = () => {
    const code = normalizeBacktestCode(codeFilter);
    const requestedWindowDays = parseEvalWindowDays(evalDays);
    const dateFrom = analysisDateFrom || undefined;
    const dateTo = analysisDateTo || undefined;
    const phase = phaseFilter;
    void fetchResults(1, code, requestedWindowDays, dateFrom, dateTo, phase);
    void fetchPerformance(code, requestedWindowDays, dateFrom, dateTo, phase);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleFilter();
    }
  };

  const handleShowNextDay = () => {
    const code = normalizeBacktestCode(codeFilter);
    const dateFrom = analysisDateFrom || undefined;
    const dateTo = analysisDateTo || undefined;
    evalDaysEditedRef.current = true;
    setEvalDays('1');
    void fetchResults(1, code, 1, dateFrom, dateTo, phaseFilter);
    void fetchPerformance(code, 1, dateFrom, dateTo, phaseFilter);
  };

  // Pagination
  const totalPages = Math.ceil(totalResults / pageSize);
  const handlePageChange = (page: number) => {
    const windowDays = appliedFilters.windowDays;
    void fetchResults(
      page,
      appliedFilters.code,
      windowDays,
      appliedFilters.analysisDateFrom,
      appliedFilters.analysisDateTo,
      appliedFilters.phase,
      { isPagination: true },
    );
  };

  return (
    <div className="min-h-full flex flex-col rounded-[1.5rem] bg-transparent">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-white/5 px-3 py-3 sm:px-4">
        <div className="flex max-w-5xl flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-[1_1_220px]">
            <input
              type="text"
              value={codeFilter}
              onChange={(e) => setCodeFilter(e.target.value.toUpperCase())}
              onKeyDown={handleKeyDown}
              placeholder={text.codePlaceholder}
              disabled={isRunning}
              className={BACKTEST_INPUT_CLASS}
            />
          </div>
          <button
            type="button"
            onClick={handleFilter}
            disabled={isLoadingResults}
            className="btn-secondary flex items-center gap-1.5 whitespace-nowrap"
          >
            {text.filter}
          </button>
          <div className="flex items-center gap-2 whitespace-nowrap lg:w-40 lg:justify-between">
            <span className="text-xs text-muted-text">{text.evalWindow}</span>
            <input
              type="number"
              min={1}
              max={120}
              value={evalDays}
              onChange={(e) => {
                evalDaysEditedRef.current = true;
                setEvalDays(e.target.value);
              }}
              onKeyDown={handleKeyDown}
              placeholder="10"
              disabled={isRunning}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-24 text-center tabular-nums`}
            />
          </div>
          <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-xs text-muted-text">{text.phase}</span>
            <select
              value={phaseFilter}
              onChange={(e) => setPhaseFilter(e.target.value as BacktestPhaseFilter)}
              disabled={isRunning}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-28`}
            >
              {phaseFilterOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-xs text-muted-text">{text.startDate}</span>
            <input
              type="date"
              aria-label={text.startDateAria}
              value={analysisDateFrom}
              onChange={(e) => setAnalysisDateFrom(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-40 text-center tabular-nums`}
            />
          </div>
          <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-xs text-muted-text">{text.endDate}</span>
            <input
              type="date"
              aria-label={text.endDateAria}
              value={analysisDateTo}
              onChange={(e) => setAnalysisDateTo(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
              className={`${BACKTEST_COMPACT_INPUT_CLASS} w-40 text-center tabular-nums`}
            />
          </div>
          <button
            type="button"
            onClick={handleShowNextDay}
            disabled={isLoadingResults || isLoadingPerf}
            className={`backtest-force-btn ${isNextDayValidation ? 'active' : ''}`}
          >
            <span className="dot" />
            {text.oneDayValidation}
          </button>
          <button
            type="button"
            onClick={() => setForceRerun(!forceRerun)}
            disabled={isRunning}
            className={`backtest-force-btn ${forceRerun ? 'active' : ''}`}
          >
            <span className="dot" />
            {text.forceRerun}
          </button>
          <button
            type="button"
            onClick={handleRun}
            disabled={isRunning}
            className="btn-primary flex items-center gap-1.5 whitespace-nowrap"
          >
            {isRunning ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                {text.running}
              </>
            ) : (
              text.runBacktest
            )}
          </button>
        </div>
        {runResult && (
          <div className="mt-2 max-w-4xl">
            <RunSummary data={runResult} language={language} />
          </div>
        )}
        {runError && (
          <ApiErrorAlert error={runError} className="mt-2 max-w-4xl" />
        )}
        <p className="mt-2 text-xs text-muted-text">
          {isNextDayValidation
            ? text.oneDayModeDescription
            : text.windowModeDescription}
        </p>
      </header>

      {/* Main content */}
      <main className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 lg:flex-row">
        {/* Left sidebar - Performance */}
        <div className="flex max-h-[38vh] flex-col gap-3 overflow-y-auto lg:max-h-none lg:w-60 lg:flex-shrink-0">
          {isLoadingPerf ? (
            <div className="flex items-center justify-center py-8">
              <div className="backtest-spinner sm" />
            </div>
          ) : overallPerf ? (
            <PerformanceCard metrics={overallPerf} title={text.overallPerformance} language={language} />
          ) : (
            <EmptyState
              title={text.noMetricsTitle}
              description={text.noMetricsDescription}
              className="h-full min-h-[12rem] border-dashed bg-card/45 shadow-none"
            />
          )}

          {stockPerf && (
            <PerformanceCard metrics={stockPerf} title={`${stockPerf.code || codeFilter}`} language={language} />
          )}
        </div>

        {/* Right content - Results table */}
        <section className="min-h-0 flex-1 overflow-y-auto">
          {pageError ? (
            <ApiErrorAlert error={pageError} className="mb-3" />
          ) : null}
          {!isLoadingPerf && (overallPerf || stockPerf) ? (
            <BacktestQuantInsights
              overallPerf={overallPerf}
              stockPerf={stockPerf}
              language={language}
            />
          ) : null}
          {isLoadingResults ? (
            <div className="flex flex-col items-center justify-center h-64">
              <div className="backtest-spinner md" />
              <p className="mt-3 text-secondary-text text-sm">{text.loadingResults}</p>
            </div>
          ) : results.length === 0 ? (
            <EmptyState
              title={text.noResultsTitle}
              description={text.noResultsDescription}
              className="backtest-empty-state border-dashed"
              icon={(
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
              )}
            />
          ) : (
            <div className="animate-fade-in">
              <div className="backtest-table-toolbar">
                <div className="backtest-table-toolbar-meta">
                  <span className="label-uppercase">{isNextDayValidation ? text.nextDayValidation : text.resultSet}</span>
                  <span className="text-xs text-secondary-text">
                    {appliedFilters.code ? formatUiText(text.filteredStock, { code: appliedFilters.code }) : text.allStocks}
                    {effectiveWindowDays ? ` · ${formatUiText(text.dayWindow, { days: effectiveWindowDays })}` : ''}
                    {appliedFilters.phase !== 'all' ? ` · ${phaseFilterOptions.find((item) => item.value === appliedFilters.phase)?.label ?? appliedFilters.phase}` : ''}
                    {appliedFilters.analysisDateFrom ? ` · ${formatUiText(text.fromDate, { date: appliedFilters.analysisDateFrom })}` : ''}
                    {appliedFilters.analysisDateTo ? ` · ${formatUiText(text.toDate, { date: appliedFilters.analysisDateTo })}` : ''}
                  </span>
                </div>
                <span className="backtest-table-scroll-hint">{text.scrollHint}</span>
              </div>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-surface-elevated/35 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="mr-1 text-[11px] text-muted-text">{qt.outcomeFilterLabel}:</span>
                  {(
                    [
                      ['all', qt.filterAll],
                      ['win', qt.filterWin],
                      ['loss', qt.filterLoss],
                      ['neutral', qt.filterNeutral],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setOutcomeFilter(key)}
                      aria-pressed={outcomeFilter === key}
                      className={`rounded-lg border px-2 py-1 text-xs transition-colors ${
                        outcomeFilter === key
                          ? 'border-primary/50 bg-primary/15 text-primary font-medium'
                          : 'border-white/10 bg-transparent text-secondary-text hover:border-white/25'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                  <span className="ml-1 font-mono text-[11px] text-muted-text">
                    ({outcomeCounts.win}/{outcomeCounts.loss}/{outcomeCounts.neutral})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-text">{qt.sortLabel}</span>
                  <select
                    aria-label={qt.sortLabel}
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                    className={`${BACKTEST_COMPACT_INPUT_CLASS} h-8 w-36 py-1 text-xs`}
                  >
                    <option value="default">{qt.sortDefault}</option>
                    <option value="sim_desc">{qt.sortSimDesc}</option>
                    <option value="sim_asc">{qt.sortSimAsc}</option>
                    <option value="stock_desc">{qt.sortStockDesc}</option>
                  </select>
                </div>
              </div>
              {filteredSortedResults.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/15 bg-surface-elevated/30 py-10 text-xs text-muted-text">
                  <span>{qt.noFilteredRows}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setOutcomeFilter('all');
                      setSortBy('default');
                    }}
                    className="btn-secondary px-3 py-1 text-xs"
                  >
                    {qt.resetLocalFilter}
                  </button>
                </div>
              ) : (
                <div className="backtest-table-wrapper">
                  <table className="backtest-table min-w-[900px] w-full text-sm">
                    <thead className="backtest-table-head">
                      <tr className="text-left">
                        <th className="backtest-table-head-cell">{text.stock}</th>
                        <th className="backtest-table-head-cell">{text.analysisDate}</th>
                        <th className="backtest-table-head-cell">{text.phase}</th>
                        <th className="backtest-table-head-cell">{text.aiPrediction}</th>
                        <th className="backtest-table-head-cell">
                          {showNextDayActualColumns ? text.actualPerformance : text.windowReturn}
                        </th>
                        <th className="backtest-table-head-cell">
                          {showNextDayActualColumns ? text.accuracy : text.directionMatch}
                        </th>
                        <th className="backtest-table-head-cell">{text.result}</th>
                        <th className="backtest-table-head-cell">{text.status}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSortedResults.map((row) => {
                        const actionLabel = getDecisionActionLabel(row.action, row.actionLabel, null, null, actionLabels);
                        const predictionParts = [actionLabel, row.trendPrediction, row.operationAdvice]
                          .filter((part): part is string => Boolean(part));
                        const isExpanded = Boolean(expandedIds[row.analysisHistoryId]);
                        const entryBasis = row.simulatedEntryPrice && row.simulatedEntryPrice > 0
                          ? row.simulatedEntryPrice
                          : row.startPrice;
                        const mfePct = entryBasis && entryBasis > 0 && row.maxHigh != null
                          ? ((row.maxHigh - entryBasis) / entryBasis) * 100
                          : null;
                        const maePct = entryBasis && entryBasis > 0 && row.minLow != null
                          ? ((row.minLow - entryBasis) / entryBasis) * 100
                          : null;
                        const exitReasonLabel = row.simulatedExitReason
                          ? (qt.exitReasons[row.simulatedExitReason] ?? row.simulatedExitReason)
                          : '--';
                        const hitDetailParts = [
                          row.firstHit ? (qt.exitReasons[row.firstHit] ?? row.firstHit) : null,
                          row.firstHitDate || null,
                          row.firstHitTradingDays != null
                            ? formatUiText(qt.daysUnit, { days: row.firstHitTradingDays })
                            : null,
                        ].filter(Boolean);

                        return (
                          <Fragment key={row.analysisHistoryId}>
                            <tr className="backtest-table-row">
                              <td className="backtest-table-cell backtest-table-code">
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => toggleRowExpand(row.analysisHistoryId)}
                                    aria-expanded={isExpanded}
                                    aria-label={isExpanded ? qt.collapseDetailAria : qt.expandDetailAria}
                                    className="rounded-md p-1 text-muted-text transition-colors hover:bg-white/10 hover:text-foreground"
                                  >
                                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                                  </button>
                                  <div className="flex flex-col">
                                    <span>{row.code}</span>
                                    <span className="text-xs text-muted-text">{row.stockName || '--'}</span>
                                  </div>
                                </div>
                              </td>
                              <td className="backtest-table-cell text-secondary-text">{row.analysisDate || '--'}</td>
                              <td className="backtest-table-cell text-secondary-text">{phaseLabel(row, language)}</td>
                              <td className="backtest-table-cell max-w-[220px] text-foreground">
                                {predictionParts.length ? (
                                  <Tooltip
                                    content={predictionParts.join(' / ')}
                                    focusable
                                  >
                                    <div className="flex flex-col gap-1">
                                      <span className="block truncate">{actionLabel || row.trendPrediction || '--'}</span>
                                      {actionLabel && row.trendPrediction && (
                                        <span className="block truncate text-xs text-secondary-text">{row.trendPrediction}</span>
                                      )}
                                      {row.operationAdvice && (
                                        <span className="block truncate text-xs text-secondary-text">{row.operationAdvice}</span>
                                      )}
                                    </div>
                                  </Tooltip>
                                ) : (
                                  '--'
                                )}
                              </td>
                              <td className="backtest-table-cell">
                                <div className="flex items-center gap-2">
                                  {actualMovementBadge(row.actualMovement, language)}
                                  <span className={
                                    row.actualReturnPct != null
                                      ? row.actualReturnPct > 0 ? 'text-success' : row.actualReturnPct < 0 ? 'text-danger' : 'text-secondary-text'
                                      : 'text-muted-text'
                                  }>
                                    {pct(row.actualReturnPct)}
                                  </span>
                                </div>
                              </td>
                              <td className="backtest-table-cell">
                                <span className="flex items-center gap-2">
                                  {boolIcon(row.directionCorrect, text)}
                                  <span className="text-muted-text">
                                    {row.directionExpected ? labelFromMap(row.directionExpected, BACKTEST_DIRECTION_EXPECTED_LABELS[language]) : ''}
                                  </span>
                                </span>
                              </td>
                              <td className="backtest-table-cell">{outcomeBadge(row.outcome, language)}</td>
                              <td className="backtest-table-cell">{statusBadge(row.evalStatus, language)}</td>
                            </tr>
                            {isExpanded && (
                              <tr className="bg-surface-elevated/45">
                                <td colSpan={8} className="border-b border-white/10 px-4 py-3 text-xs">
                                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <span className="font-semibold text-foreground">{qt.replayTitle}</span>
                                    <a
                                      href={`/?stock=${encodeURIComponent(row.code)}`}
                                      className="inline-flex items-center gap-1 rounded-lg border border-primary/35 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                                    >
                                      {qt.openReportAction}
                                      <ExternalLink className="h-3 w-3" />
                                    </a>
                                  </div>
                                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.simEntryExit}</div>
                                      <div className="mt-0.5 font-mono text-foreground">
                                        {row.simulatedEntryPrice == null && row.simulatedExitPrice == null
                                          ? '--'
                                          : `${fmtPrice(row.simulatedEntryPrice)} → ${fmtPrice(row.simulatedExitPrice)}`}
                                      </div>
                                    </div>
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.exitReason}</div>
                                      <div className="mt-0.5 text-foreground">{exitReasonLabel}</div>
                                    </div>
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.simReturn}</div>
                                      <div className={`mt-0.5 font-mono font-semibold ${
                                        (row.simulatedReturnPct ?? 0) > 0
                                          ? 'text-success'
                                          : (row.simulatedReturnPct ?? 0) < 0
                                            ? 'text-danger'
                                            : 'text-foreground'
                                      }`}>
                                        {fmtSignedPct(row.simulatedReturnPct)}
                                      </div>
                                    </div>
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.riskTargets}</div>
                                      <div className="mt-0.5 font-mono text-foreground">
                                        {fmtPrice(row.stopLoss)} / {fmtPrice(row.takeProfit)}
                                      </div>
                                    </div>
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.firstHitDetail}</div>
                                      <div className="mt-0.5 text-foreground">
                                        {hitDetailParts.length > 0 ? hitDetailParts.join(' · ') : '--'}
                                      </div>
                                    </div>
                                    <div>
                                      <div className="text-[11px] text-muted-text">{qt.excursionRange}</div>
                                      <div className="mt-0.5 font-mono text-foreground">
                                        {fmtPrice(row.maxHigh)} / {fmtPrice(row.minLow)}
                                        {(mfePct != null || maePct != null) && (
                                          <span className="ml-1 text-[11px] text-muted-text">
                                            ({fmtSignedPct(mfePct)} / {fmtSignedPct(maePct)})
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Pagination */}
              <div className="mt-4">
                <Pagination
                  currentPage={currentPage}
                  totalPages={totalPages}
                  onPageChange={handlePageChange}
                />
              </div>

              <p className="text-xs text-muted-text text-center mt-2">
                {formatUiText(text.totalPage, { total: totalResults, page: currentPage, pages: Math.max(totalPages, 1) })}
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default BacktestPage;
