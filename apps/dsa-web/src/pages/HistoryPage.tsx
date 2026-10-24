import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { History as HistoryIcon } from 'lucide-react';
import { historyApi } from '../api/history';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Card,
  EmptyState,
  Loading,
  PageHeader,
  Pagination,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../utils/decisionAction';
import type { DailyHistoryItem, DailyHistoryListResponse } from '../types/analysis';
import { formatDateTime, toDateInputValue } from '../utils/format';

const PAGE_SIZE = 20;

function formatPrice(value: number | null): string {
  return value == null ? '—' : String(value);
}

function renderStockCell(item: DailyHistoryItem): React.ReactNode {
  return (
    <div className="min-w-0">
      <div className="truncate font-medium text-foreground">{item.name}</div>
      <div className="font-mono text-xs text-secondary-text">{item.code}</div>
    </div>
  );
}

function renderSentimentCell(item: DailyHistoryItem): React.ReactNode {
  return (
    <div className="min-w-0">
      <div className="text-foreground">{item.sentimentScore == null ? '—' : item.sentimentScore}</div>
      {item.sentimentLabel == null ? null : (
        <div className="text-xs text-secondary-text">{item.sentimentLabel}</div>
      )}
    </div>
  );
}

const HistoryPage: React.FC = () => {
  const { t, language } = useUiLanguage();
  const actionLabels = buildDecisionActionLabelMap(t);
  const [date, setDate] = useState<string>(() => toDateInputValue(new Date()));
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<DailyHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const requestIdRef = useRef(0);

  useEffect(() => {
    document.title = t('history.pageTitle');
  }, [t]);

  const loadDaily = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const isLatestRequest = () => requestIdRef.current === requestId;
    setLoading(true);
    try {
      const response: DailyHistoryListResponse = await historyApi.getDaily({
        date,
        language,
        page,
        limit: PAGE_SIZE,
      });
      if (!isLatestRequest()) return;
      setItems(response.items);
      setTotal(response.total);
      setError(null);
      setLoaded(true);
    } catch (err) {
      if (!isLatestRequest()) return;
      setItems([]);
      setTotal(0);
      setError(getParsedApiError(err));
    } finally {
      if (isLatestRequest()) {
        setLoading(false);
      }
    }
  }, [date, language, page]);

  useEffect(() => {
    void loadDaily();
  }, [loadDaily]);

  const handleDateChange = (nextDate: string) => {
    if (!nextDate) return; // <input type="date"> 清空产生 ""，直接发请求注定 422
    setDate(nextDate);
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasItems = !error && items.length > 0;

  return (
    <AppPage className="space-y-5">
      <PageHeader
        title={t('history.pageTitle')}
        description={t('history.pageSubtitle')}
      />

      <Card padding="md">
        <label className="flex flex-wrap items-center gap-3 text-sm text-secondary-text">
          <span>{t('history.dateLabel')}</span>
          <input
            type="date"
            className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm text-foreground"
            value={date}
            aria-label={t('history.dateLabel')}
            onChange={(event) => handleDateChange(event.target.value)}
          />
        </label>
      </Card>

      {error ? (
        <ApiErrorAlert
          error={{ ...error, title: t('history.loadFailed') }}
          onDismiss={() => setError(null)}
        />
      ) : null}

      {loading ? <Loading label={t('history.loading')} /> : null}

      {!loading && !error && loaded && items.length === 0 ? (
        <EmptyState
          icon={<HistoryIcon className="h-6 w-6" />}
          title={t('history.emptyTitle')}
          description={t('history.emptyHint')}
        />
      ) : null}

      {hasItems ? (
        <Card padding="md">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-sm">
              <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('history.stockColumn')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.sentiment')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.operationAdvice')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.trendPrediction')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.validity')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.idealBuy')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.secondaryBuy')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.stopLoss')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.takeProfit')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.reportType')}</th>
                  <th className="px-3 py-2 font-medium">{t('history.time')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-3 py-3">{renderStockCell(item)}</td>
                    <td className="px-3 py-3">{renderSentimentCell(item)}</td>
                    <td className="px-3 py-3">
                      {getDecisionActionLabel(
                        item.action,
                        item.actionLabel,
                        item.operationAdvice,
                        item.operationAdvice ?? '—',
                        actionLabels,
                      )}
                    </td>
                    <td className="px-3 py-3">{item.trendPrediction ?? '—'}</td>
                    <td className="px-3 py-3">
                      {item.isLatest ? (
                        <Badge variant="success">{t('history.valid')}</Badge>
                      ) : (
                        <Badge variant="warning">{t('history.expired')}</Badge>
                      )}
                    </td>
                    <td className="px-3 py-3">{formatPrice(item.idealBuy)}</td>
                    <td className="px-3 py-3">{formatPrice(item.secondaryBuy)}</td>
                    <td className="px-3 py-3">{formatPrice(item.stopLoss)}</td>
                    <td className="px-3 py-3">{formatPrice(item.takeProfit)}</td>
                    <td className="px-3 py-3">{item.reportType || '—'}</td>
                    <td className="px-3 py-3">{formatDateTime(item.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        </Card>
      ) : null}
    </AppPage>
  );
};

export default HistoryPage;
