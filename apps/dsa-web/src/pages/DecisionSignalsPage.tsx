import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, BarChart3, RefreshCw, Search } from 'lucide-react';
import { decisionSignalsApi } from '../api/decisionSignals';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Card,
  ConfirmDialog,
  Drawer,
  EmptyState,
  InlineAlert,
  PageHeader,
  Pagination,
} from '../components/common';
import {
  DecisionSignalCard,
  DecisionSignalDetails,
} from '../components/decision-signals/DecisionSignalDisplay';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiTextKey } from '../i18n/uiText';
import type { DecisionAction, MarketPhaseValue } from '../types/analysis';
import type {
  DecisionSignalItem,
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackValue,
  DecisionSignalListParams,
  DecisionSignalMarket,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeStatsResponse,
  DecisionSignalSourceType,
  DecisionSignalStatus,
} from '../types/decisionSignals';
import { cn } from '../utils/cn';
import { buildDecisionActionLabelMap } from '../utils/decisionAction';
import {
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalSourceTypeLabel,
} from '../utils/decisionSignalLabels';

const PAGE_SIZE = 20;

type ListFilters = {
  market: '' | DecisionSignalMarket;
  stockCode: string;
  action: '' | DecisionAction;
  marketPhase: '' | MarketPhaseValue;
  sourceType: '' | DecisionSignalSourceType;
  sourceReportId: string;
  status: '' | DecisionSignalStatus;
};

type PendingStatusChange = {
  item: DecisionSignalItem;
  status: Extract<DecisionSignalStatus, 'closed' | 'invalidated' | 'archived'>;
  message: string;
};

type SelectedSignal = {
  item: DecisionSignalItem;
  source: 'list' | 'latest';
};

const MARKET_OPTIONS: DecisionSignalMarket[] = ['cn', 'hk', 'us', 'jp', 'kr', 'tw'];
const ACTION_OPTIONS: DecisionAction[] = ['buy', 'add', 'hold', 'reduce', 'sell', 'watch', 'avoid', 'alert'];
const PHASE_OPTIONS: MarketPhaseValue[] = ['premarket', 'intraday', 'lunch_break', 'closing_auction', 'postmarket', 'non_trading', 'unknown'];
const SOURCE_OPTIONS: DecisionSignalSourceType[] = ['analysis', 'agent', 'alert', 'market_review', 'manual'];
const STATUS_OPTIONS: DecisionSignalStatus[] = ['active', 'expired', 'invalidated', 'closed', 'archived'];

const STATUS_ACTIONS: Array<PendingStatusChange['status']> = ['closed', 'invalidated', 'archived'];

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const STATUS_ACTION_LABEL_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.close',
  invalidated: 'decisionSignals.invalidate',
  archived: 'decisionSignals.archive',
};

const STATUS_ACTION_CONFIRM_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.closeConfirm',
  invalidated: 'decisionSignals.invalidateConfirm',
  archived: 'decisionSignals.archiveConfirm',
};

const DEFAULT_LIST_FILTERS: ListFilters = {
  market: '',
  stockCode: '',
  action: '',
  marketPhase: '',
  sourceType: '',
  sourceReportId: '',
  status: 'active',
};

function parseSourceReportId(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function getInitialFilters(search = typeof window === 'undefined' ? '' : window.location.search): ListFilters {
  const params = new URLSearchParams(search);
  const sourceReportId = parseSourceReportId(params.get('sourceReportId') ?? params.get('source_report_id') ?? '');
  if (sourceReportId === undefined) return DEFAULT_LIST_FILTERS;
  return {
    ...DEFAULT_LIST_FILTERS,
    sourceReportId: String(sourceReportId),
  };
}

function toListParams(filters: ListFilters, page: number): DecisionSignalListParams {
  const sourceReportId = parseSourceReportId(filters.sourceReportId);
  if (sourceReportId !== undefined) {
    return {
      sourceReportId,
      sourceType: 'analysis',
      page,
      pageSize: PAGE_SIZE,
    };
  }

  return {
    market: filters.market || undefined,
    stockCode: filters.stockCode.trim() || undefined,
    action: filters.action || undefined,
    marketPhase: filters.marketPhase || undefined,
    sourceType: filters.sourceType || undefined,
    status: filters.status || undefined,
    page,
    pageSize: PAGE_SIZE,
  };
}

function refreshLatestSelection(
  current: SelectedSignal | null,
  latestItems: DecisionSignalItem[],
): SelectedSignal | null {
  if (!current || current.source !== 'latest') return current;
  const refreshed = latestItems.find((item) => item.id === current.item.id);
  return refreshed ? { source: 'latest', item: refreshed } : null;
}

function formatStatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toFixed(2).replace(/\.?0+$/, '');
}

function formatStatPercent(value: number | null | undefined): string {
  const formatted = formatStatNumber(value);
  return formatted === '-' ? formatted : `${formatted}%`;
}

const DecisionSignalsPage: React.FC = () => {
  const { t } = useUiLanguage();
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);
  const [filters, setFilters] = useState<ListFilters>(() => getInitialFilters());
  const [appliedFilters, setAppliedFilters] = useState<ListFilters>(() => getInitialFilters());
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<DecisionSignalItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [selected, setSelected] = useState<SelectedSignal | null>(null);
  const [pendingStatus, setPendingStatus] = useState<PendingStatusChange | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [outcomeStats, setOutcomeStats] = useState<DecisionSignalOutcomeStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<ParsedApiError | null>(null);
  const [latestStockCode, setLatestStockCode] = useState('');
  const [latestItems, setLatestItems] = useState<DecisionSignalItem[]>([]);
  const [latestSearched, setLatestSearched] = useState(false);
  const [latestLoading, setLatestLoading] = useState(false);
  const [latestError, setLatestError] = useState<ParsedApiError | null>(null);
  const [selectedOutcomes, setSelectedOutcomes] = useState<DecisionSignalOutcomeItem[]>([]);
  const [selectedOutcomesLoading, setSelectedOutcomesLoading] = useState(false);
  const [selectedOutcomesError, setSelectedOutcomesError] = useState<ParsedApiError | null>(null);
  const [selectedFeedback, setSelectedFeedback] = useState<DecisionSignalFeedbackItem | null>(null);
  const [selectedFeedbackLoading, setSelectedFeedbackLoading] = useState(false);
  const [selectedFeedbackError, setSelectedFeedbackError] = useState<ParsedApiError | null>(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const requestIdRef = useRef(0);
  const statsRequestIdRef = useRef(0);
  const latestRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const selectedSignalIdRef = useRef<number | null>(null);
  const statusUpdateInFlightRef = useRef(false);

  useEffect(() => {
    document.title = t('decisionSignals.pageTitle');
  }, [t]);

  const loadSignalsForPage = useCallback(async (nextPage: number) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    try {
      const response = await decisionSignalsApi.list(toListParams(appliedFilters, nextPage));
      if (requestIdRef.current !== requestId) return;
      const lastPage = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
      if (response.total > 0 && nextPage > lastPage) {
        setPage(lastPage);
        return;
      }
      setItems(response.items);
      setTotal(response.total);
      setError(null);
      setSelected((current) => {
        if (!current) return current;
        if (current.source !== 'list') return current;
        const refreshed = response.items.find((item) => item.id === current.item.id);
        return refreshed ? { source: 'list', item: refreshed } : null;
      });
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setError(getParsedApiError(err));
      setItems([]);
      setTotal(0);
      setSelected((current) => (current?.source === 'list' ? null : current));
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [appliedFilters]);

  const loadSignals = useCallback(async () => {
    await loadSignalsForPage(page);
  }, [loadSignalsForPage, page]);

  const loadOutcomeStats = useCallback(async () => {
    const requestId = statsRequestIdRef.current + 1;
    statsRequestIdRef.current = requestId;
    setStatsLoading(true);
    try {
      const response = await decisionSignalsApi.getOutcomeStats();
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(response);
      setStatsError(null);
    } catch (err) {
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(null);
      setStatsError(getParsedApiError(err));
    } finally {
      if (statsRequestIdRef.current === requestId) {
        setStatsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadSignals();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadSignals]);

  useEffect(() => {
    void loadOutcomeStats();
    return () => {
      statsRequestIdRef.current += 1;
    };
  }, [loadOutcomeStats]);

  useEffect(() => () => {
    latestRequestIdRef.current += 1;
  }, []);

  useEffect(() => {
    selectedSignalIdRef.current = selected?.item.id ?? null;
    if (!selected) {
      detailRequestIdRef.current += 1;
      setSelectedOutcomes([]);
      setSelectedOutcomesError(null);
      setSelectedFeedback(null);
      setSelectedFeedbackError(null);
      setSelectedOutcomesLoading(false);
      setSelectedFeedbackLoading(false);
      return;
    }

    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setSelectedOutcomesLoading(true);
    setSelectedFeedbackLoading(true);
    setSelectedOutcomesError(null);
    setSelectedFeedbackError(null);

    void decisionSignalsApi.getSignalOutcomes(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes(response.items);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes([]);
        setSelectedOutcomesError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedOutcomesLoading(false);
        }
      });

    void decisionSignalsApi.getFeedback(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(response);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(null);
        setSelectedFeedbackError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedFeedbackLoading(false);
        }
      });
  }, [selected]);

  const handleApplyFilters = (event: React.FormEvent) => {
    event.preventDefault();
    setAppliedFilters(filters);
    setPage(1);
  };

  const handleLatestSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    const stockCode = latestStockCode.trim();
    if (!stockCode) return;
    const requestId = latestRequestIdRef.current + 1;
    latestRequestIdRef.current = requestId;
    setLatestLoading(true);
    setLatestError(null);
    setLatestSearched(true);
    try {
      const response = await decisionSignalsApi.getLatest(stockCode, {
        market: appliedFilters.market || undefined,
        limit: 5,
      });
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems(response.items);
      setSelected((current) => refreshLatestSelection(current, response.items));
    } catch (err) {
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems([]);
      setSelected((current) => refreshLatestSelection(current, []));
      setLatestError(getParsedApiError(err));
    } finally {
      if (latestRequestIdRef.current === requestId) {
        setLatestLoading(false);
      }
    }
  };

  const handleStatusUpdate = async () => {
    if (!pendingStatus || statusUpdateInFlightRef.current) return;
    statusUpdateInFlightRef.current = true;
    setStatusUpdating(true);
    try {
      const updated = await decisionSignalsApi.updateStatus(pendingStatus.item.id, {
        status: pendingStatus.status,
      });
      setPendingStatus(null);
      setLatestItems((current) => current.flatMap((item) => {
        if (item.id !== updated.id) return [item];
        return updated.status === 'active' ? [updated] : [];
      }));
      setSelected((current) => {
        if (!current || current.item.id !== updated.id) return current;
        if (current.source === 'latest') {
          return updated.status === 'active' ? { source: 'latest', item: updated } : null;
        }
        if (!parseSourceReportId(appliedFilters.sourceReportId) && appliedFilters.status && updated.status !== appliedFilters.status) return null;
        return { source: 'list', item: updated };
      });
      setError(null);
      await loadSignalsForPage(page);
      await loadOutcomeStats();
    } catch (err) {
      setError(getParsedApiError(err));
      setPendingStatus(null);
    } finally {
      setStatusUpdating(false);
      statusUpdateInFlightRef.current = false;
    }
  };

  const handleFeedbackSubmit = useCallback(async (feedbackValue: DecisionSignalFeedbackValue) => {
    if (!selected || feedbackSaving) return;
    const signalId = selected.item.id;
    setFeedbackSaving(true);
    try {
      const updated = await decisionSignalsApi.putFeedback(signalId, {
        feedbackValue,
        source: 'web',
      });
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedback(updated);
      setSelectedFeedbackError(null);
    } catch (err) {
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedbackError(getParsedApiError(err));
    } finally {
      setFeedbackSaving(false);
    }
  }, [feedbackSaving, selected]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow={t('decisionSignals.activeOnly')}
          title={t('decisionSignals.title')}
          description={t('decisionSignals.description')}
          actions={(
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={() => {
                void loadSignals();
                void loadOutcomeStats();
              }}
              disabled={loading}
            >
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
              {t('decisionSignals.refresh')}
            </button>
          )}
        />

        <Card padding="md">
          <form className="grid gap-3 md:grid-cols-3 xl:grid-cols-7" onSubmit={handleApplyFilters}>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.market}
              onChange={(event) => setFilters((current) => ({ ...current, market: event.target.value as ListFilters['market'] }))}
              aria-label={t('decisionSignals.market')}
            >
              <option value="">{t('decisionSignals.allMarkets')}</option>
              {MARKET_OPTIONS.map((market) => (
                <option key={market} value={market}>{getDecisionSignalMarketLabel(market, t)}</option>
              ))}
            </select>
            <input
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.stockCode}
              onChange={(event) => setFilters((current) => ({ ...current, stockCode: event.target.value }))}
              placeholder={t('decisionSignals.stockCode')}
              aria-label={t('decisionSignals.stockCode')}
            />
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.action}
              onChange={(event) => setFilters((current) => ({ ...current, action: event.target.value as ListFilters['action'] }))}
              aria-label={t('decisionSignals.action')}
            >
              <option value="">{t('decisionSignals.allActions')}</option>
              {ACTION_OPTIONS.map((action) => (
                <option key={action} value={action}>{actionLabels[action]}</option>
              ))}
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.marketPhase}
              onChange={(event) => setFilters((current) => ({ ...current, marketPhase: event.target.value as ListFilters['marketPhase'] }))}
              aria-label={t('decisionSignals.marketPhase')}
            >
              <option value="">{t('decisionSignals.allPhases')}</option>
              {PHASE_OPTIONS.map((phase) => (
                <option key={phase} value={phase}>{getDecisionSignalMarketPhaseLabel(phase, t)}</option>
              ))}
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.sourceType}
              onChange={(event) => setFilters((current) => ({ ...current, sourceType: event.target.value as ListFilters['sourceType'] }))}
              aria-label={t('decisionSignals.source')}
            >
              <option value="">{t('decisionSignals.allSources')}</option>
              {SOURCE_OPTIONS.map((source) => (
                <option key={source} value={source}>{getDecisionSignalSourceTypeLabel(source, t)}</option>
              ))}
            </select>
            <input
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.sourceReportId}
              onChange={(event) => setFilters((current) => ({ ...current, sourceReportId: event.target.value }))}
              placeholder={t('decisionSignals.sourceReportId')}
              aria-label={t('decisionSignals.sourceReportId')}
              inputMode="numeric"
              min={1}
              step={1}
              type="number"
            />
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as ListFilters['status'] }))}
              aria-label={t('decisionSignals.status')}
            >
              <option value="">{t('decisionSignals.allStatuses')}</option>
              {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{t(STATUS_LABEL_KEYS[status])}</option>)}
            </select>
            <button type="submit" className="btn-primary inline-flex h-11 items-center justify-center gap-2">
              <Search className="h-4 w-4" />
              {t('decisionSignals.filter')}
            </button>
          </form>
        </Card>

        <Card title={t('decisionSignals.statsTitle')} subtitle={t('decisionSignals.statsDescription')} padding="md">
          {statsError ? (
            <ApiErrorAlert
              error={{ ...statsError, title: t('decisionSignals.statsErrorTitle') }}
              actionLabel={t('common.retry')}
              onAction={() => void loadOutcomeStats()}
            />
          ) : statsLoading ? (
            <p className="text-sm text-secondary-text">{t('common.loading')}...</p>
          ) : outcomeStats ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.statsTotal')}</p>
                <p className="mt-1 text-2xl font-semibold text-foreground">{outcomeStats.total}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.statsHitRate')}</p>
                <p className="mt-1 text-2xl font-semibold text-success">{formatStatPercent(outcomeStats.hitRatePct)}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.hit')}</p>
                <p className="mt-1 text-2xl font-semibold text-success">{outcomeStats.hit}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.miss')}</p>
                <p className="mt-1 text-2xl font-semibold text-danger">{outcomeStats.miss}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.unable')}</p>
                <p className="mt-1 text-2xl font-semibold text-warning">{outcomeStats.unable}</p>
              </div>
            </div>
          ) : (
            <EmptyState
              className="border-none bg-transparent py-6 shadow-none"
              title={t('decisionSignals.noStatsTitle')}
              description={t('decisionSignals.noStatsDescription')}
              icon={<BarChart3 className="h-6 w-6" />}
            />
          )}
        </Card>

        <Card title={t('decisionSignals.latestTitle')} subtitle={t('decisionSignals.latestDescription')} padding="md">
          <form className="flex flex-col gap-3 md:flex-row" onSubmit={handleLatestSearch}>
            <input
              className="input-surface input-focus-glow h-11 flex-1 rounded-xl border bg-transparent px-3 text-sm"
              value={latestStockCode}
              onChange={(event) => setLatestStockCode(event.target.value)}
              placeholder={t('decisionSignals.latestPlaceholder')}
              aria-label={t('decisionSignals.latestInput')}
            />
            <button type="submit" className="btn-secondary inline-flex h-11 items-center justify-center gap-2" disabled={latestLoading || !latestStockCode.trim()}>
              <Search className="h-4 w-4" />
              {t('decisionSignals.latestButton')}
            </button>
          </form>
          {latestError ? <ApiErrorAlert className="mt-3" error={latestError} /> : null}
          {latestSearched && !latestLoading && !latestError && latestItems.length === 0 ? (
            <EmptyState
              className="mt-4 border-none bg-transparent py-6 shadow-none"
              title={t('decisionSignals.noLatestTitle')}
              description={t('decisionSignals.noLatestDescription')}
              icon={<Activity className="h-6 w-6" />}
            />
          ) : null}
          {latestItems.length > 0 ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {latestItems.map((item) => (
                <DecisionSignalCard
                  key={item.id}
                  item={item}
                  onSelect={(selectedItem) => setSelected({ source: 'latest', item: selectedItem })}
                  selected={selected?.item.id === item.id}
                />
              ))}
            </div>
          ) : null}
        </Card>

        {error ? (
          <ApiErrorAlert
            error={{ ...error, title: t('decisionSignals.errorTitle') }}
            actionLabel={t('common.retry')}
            onAction={() => void loadSignals()}
          />
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-secondary-text">{t('decisionSignals.total', { total })}</p>
          {loading ? <span className="text-xs text-secondary-text">{t('common.loading')}...</span> : null}
        </div>

        {!loading && items.length === 0 ? (
          <EmptyState
            title={t('decisionSignals.emptyTitle')}
            description={t('decisionSignals.emptyDescription')}
            icon={<Activity className="h-7 w-7" />}
          />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {items.map((item) => (
              <DecisionSignalCard
                key={item.id}
                item={item}
                onSelect={(selectedItem) => setSelected({ source: 'list', item: selectedItem })}
                selected={selected?.item.id === item.id}
              />
            ))}
          </div>
        )}

        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      </div>

      <Drawer
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={t('decisionSignals.detailTitle')}
        width="max-w-3xl"
      >
        {selected ? (
          <DecisionSignalDetails
            item={selected.item}
            outcomes={selectedOutcomes}
            outcomesLoading={selectedOutcomesLoading}
            outcomesError={selectedOutcomesError?.message ?? null}
            feedback={selectedFeedback}
            feedbackLoading={selectedFeedbackLoading}
            feedbackSaving={feedbackSaving}
            feedbackError={selectedFeedbackError?.message ?? null}
            onFeedbackSubmit={handleFeedbackSubmit}
            actions={STATUS_ACTIONS.map((status) => (
              <button
                key={status}
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                onClick={() => setPendingStatus({
                  item: selected.item,
                  status,
                  message: t(STATUS_ACTION_CONFIRM_KEYS[status]),
                })}
                disabled={statusUpdating || selected.item.status === status}
              >
                {t(STATUS_ACTION_LABEL_KEYS[status])}
              </button>
            ))}
          />
        ) : null}
      </Drawer>

      {statusUpdating ? (
        <InlineAlert
          className="fixed bottom-5 right-5 z-[60] max-w-sm"
          variant="info"
          title={t('common.processing')}
          message={t('decisionSignals.confirmStatusTitle')}
        />
      ) : null}

      <ConfirmDialog
        isOpen={Boolean(pendingStatus)}
        title={t('decisionSignals.confirmStatusTitle')}
        message={pendingStatus?.message ?? ''}
        confirmText={t('common.confirm')}
        confirmDisabled={statusUpdating}
        cancelDisabled={statusUpdating}
        onConfirm={() => void handleStatusUpdate()}
        onCancel={() => setPendingStatus(null)}
      />
    </AppPage>
  );
};

export default DecisionSignalsPage;
