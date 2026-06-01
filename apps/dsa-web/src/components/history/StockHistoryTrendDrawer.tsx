import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import type { AnalysisReport, HistoryItem, StockHistoryFilters, StockHistoryRange } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { formatDateTime } from '../../utils/format';
import { Badge, Button, Card } from '../common';
import { DashboardStateBlock } from '../dashboard';

interface StockHistoryTrendDrawerProps {
  report: AnalysisReport;
  items: HistoryItem[];
  total: number;
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  error?: unknown;
  filters: StockHistoryFilters;
  onClose: () => void;
  onRangeChange: (range: StockHistoryRange) => void;
  onLoadMore: () => void;
  onSelectRecord: (recordId: number) => void;
  onRetry: () => void;
}

const RANGE_OPTIONS: Array<{ value: StockHistoryRange; label: string }> = [
  { value: 'all', label: '全部历史' },
  { value: '30d', label: '近30天' },
  { value: '90d', label: '近90天' },
];

const isPresent = <T,>(value: T | null | undefined): value is T =>
  value !== undefined && value !== null && value !== '';

const formatNumber = (value?: number, digits = 2): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--';

const formatChangePct = (value?: number): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '--';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

const formatHistoryTime = (value?: string | null): string => {
  const formatted = formatDateTime(value);
  return formatted.length > 11 ? formatted.slice(5) : formatted;
};

const getPriceChangeStyle = (value?: number): React.CSSProperties | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return undefined;
  }
  return { color: value > 0 ? 'var(--home-price-up)' : 'var(--home-price-down)' };
};

const formatModelName = (value?: string): string => {
  const model = value?.trim();
  if (!model) {
    return '未记录';
  }
  const parts = model.split('/').filter(Boolean);
  return parts[parts.length - 1] || model;
};

const formatAdviceParts = (item: Pick<HistoryItem, 'operationAdvice' | 'trendPrediction'>): string[] => {
  const parts = [item.operationAdvice?.trim(), item.trendPrediction?.trim()]
    .filter((part): part is string => Boolean(part));
  return parts.length ? parts : ['--'];
};

const formatAdvice = (item: Pick<HistoryItem, 'operationAdvice' | 'trendPrediction'>): string =>
  formatAdviceParts(item)[0];

const getAdviceVariant = (value: string): 'success' | 'warning' | 'danger' | 'default' => {
  if (value.includes('买') || value.includes('多') || value.includes('持有')) {
    return 'success';
  }
  if (value.includes('卖') || value.includes('减') || value.includes('空')) {
    return 'danger';
  }
  if (value.includes('观望') || value.includes('震荡')) {
    return 'warning';
  }
  return 'default';
};

const summarizeView = (items: HistoryItem[], report: AnalysisReport, currentId?: number) => {
  const scores = items
    .map((item) => item.sentimentScore)
    .filter((score): score is number => typeof score === 'number' && Number.isFinite(score));
  const current = items.find((item) => item.id === currentId) || items[0];
  const models = new Map<string, number>();
  items.forEach((item) => {
    const model = formatModelName(item.modelUsed);
    models.set(model, (models.get(model) || 0) + 1);
  });

  const averageScore = scores.length
    ? scores.reduce((sum, score) => sum + score, 0) / scores.length
    : undefined;
  const modelEntries = Array.from(models.entries()).sort((a, b) => b[1] - a[1]);
  const currentModel = formatModelName(current?.modelUsed || report.meta.modelUsed);

  return {
    currentScore: current?.sentimentScore ?? report.summary.sentimentScore,
    currentAdvice: current
      ? formatAdvice(current)
      : formatAdvice({
          operationAdvice: report.summary.operationAdvice,
          trendPrediction: report.summary.trendPrediction,
        }),
    averageScore,
    latestTime: formatDateTime(items[0]?.createdAt || report.meta.createdAt),
    modelSummary: modelEntries
      .map(([model, count]) => `${model} ${count}次`)
      .join(' / ') || '未记录',
    currentModel,
    modelCount: modelEntries.length,
  };
};

const MetricCard: React.FC<{ label: string; value: React.ReactNode; hint?: string; title?: string }> = ({
  label,
  value,
  hint,
  title,
}) => (
  <div className="rounded-xl border border-border/70 bg-background/45 px-4 py-3">
    <p className="text-xs text-secondary-text">{label}</p>
    <p className="mt-1 truncate text-lg font-semibold text-foreground" title={title}>
      {value}
    </p>
    {hint ? <p className="mt-1 text-xs text-muted-text">{hint}</p> : null}
  </div>
);

const RangeControls: React.FC<{
  filters: StockHistoryFilters;
  onRangeChange: (range: StockHistoryRange) => void;
}> = ({ filters, onRangeChange }) => (
  <div className="flex flex-wrap items-center gap-2">
    {RANGE_OPTIONS.map((option) => (
      <button
        key={option.value}
        type="button"
        onClick={() => onRangeChange(option.value)}
        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
          filters.range === option.value
            ? 'border-primary/50 bg-primary/10 text-primary'
            : 'border-border/70 bg-background/50 text-secondary-text hover:bg-hover hover:text-foreground'
        }`}
      >
        {option.label}
      </button>
    ))}
  </div>
);

export const StockHistoryTrendDrawer: React.FC<StockHistoryTrendDrawerProps> = ({
  report,
  items,
  total,
  hasMore,
  isLoading,
  isLoadingMore,
  error,
  filters,
  onClose,
  onRangeChange,
  onLoadMore,
  onSelectRecord,
  onRetry,
}) => {
  const currentRecordId = report.meta.id;
  const [selectedRecordId, setSelectedRecordId] = useState(currentRecordId);
  const summary = useMemo(
    () => summarizeView(items, report, currentRecordId),
    [currentRecordId, items, report],
  );

  useEffect(() => {
    setSelectedRecordId(currentRecordId);
  }, [currentRecordId]);

  return (
    <div className="space-y-4 animate-fade-in">
      <Card variant="gradient" padding="md" className="home-panel-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 19V5m0 14h16M8 17V9m4 8V7m4 10v-5" />
              </svg>
            </div>
            <div>
              <h2 className="text-2xl font-bold text-foreground">历史趋势</h2>
              <p className="mt-1 text-sm text-secondary-text">
                {report.meta.stockName || report.meta.stockCode} · {report.meta.stockCode}
              </p>
            </div>
          </div>
          <Button variant="secondary" size="sm" onClick={onClose}>
            返回当前报告
          </Button>
        </div>
      </Card>

      {isLoading ? (
        <DashboardStateBlock loading title="加载同股历史中..." />
      ) : error ? (
        <DashboardStateBlock
          title="历史趋势加载失败"
          description="请稍后重试"
          action={(
            <Button variant="secondary" size="sm" onClick={onRetry}>
              重新加载
            </Button>
          )}
        />
      ) : items.length === 0 ? (
        <Card variant="bordered" padding="md" className="home-panel-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-foreground">暂无更多同股历史分析</h3>
              <p className="mt-1 text-sm text-secondary-text">
                完成多次分析后，这里会展示观点变化、评分走势和模型记录。
              </p>
            </div>
            <RangeControls filters={filters} onRangeChange={onRangeChange} />
          </div>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="分析次数"
              value={`${total || items.length} 次`}
              hint={`最近一次 ${summary.latestTime}`}
            />
            <MetricCard label="当前观点" value={summary.currentAdvice} />
            <MetricCard
              label="当前分数"
              value={formatNumber(summary.currentScore, 0)}
              hint={`平均分 ${formatNumber(summary.averageScore, 1)}`}
            />
            <MetricCard
              label="最近模型"
              value={summary.currentModel}
              hint={`历史模型 ${summary.modelCount} 种`}
              title={summary.modelSummary}
            />
          </div>

          <Card variant="bordered" padding="md" className="home-panel-card">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-foreground">历史分析记录</h3>
                <p className="mt-1 text-sm text-secondary-text">
                  已加载 {items.length} / {total || items.length} 条 · 排序：最新优先 · 模型：全部
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <RangeControls filters={filters} onRangeChange={onRangeChange} />
                {hasMore ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={onLoadMore}
                    isLoading={isLoadingMore}
                    loadingText="加载中..."
                  >
                    加载更多
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="mt-4 overflow-hidden rounded-xl border border-border/60 bg-card/30">
              <table className="w-full table-fixed text-left text-sm">
                <colgroup>
                  <col className="w-[15%]" />
                  <col className="w-[11%]" />
                  <col className="w-[7%]" />
                  <col className="w-[9%]" />
                  <col className="w-[9%]" />
                  <col className="w-[7%]" />
                  <col className="w-[9%]" />
                  <col className="w-[22%]" />
                  <col className="w-[11%]" />
                </colgroup>
                <thead className="border-b border-border/60 bg-background/35 text-xs text-secondary-text">
                  <tr>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">时间</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">分析结果</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">分数</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">股价</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">涨跌幅</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">量比</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">换手率</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">模型</th>
                    <th className="whitespace-nowrap px-4 py-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/55">
                  {items.map((item) => {
                    const isSelected = item.id === selectedRecordId;
                    const sentimentColor = isPresent(item.sentimentScore)
                      ? getSentimentColor(item.sentimentScore)
                      : undefined;
                    return (
                      <tr
                        key={item.id}
                        className={`cursor-pointer transition-colors ${
                          isSelected ? 'bg-primary/10 ring-1 ring-inset ring-primary/35' : 'hover:bg-hover/35'
                        }`}
                        onClick={() => setSelectedRecordId(item.id)}
                      >
                        <td className="whitespace-nowrap px-3 py-3 font-mono text-sm text-secondary-text">
                          {formatHistoryTime(item.createdAt)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-3">
                          <Badge
                            variant={getAdviceVariant(formatAdvice(item))}
                            size="sm"
                            className="shadow-none"
                          >
                            {formatAdvice(item)}
                          </Badge>
                        </td>
                        <td
                          className="px-3 py-3 font-mono text-lg font-semibold"
                          style={sentimentColor ? { color: sentimentColor } : undefined}
                        >
                          {formatNumber(item.sentimentScore, 0)}
                        </td>
                        <td className="px-3 py-3 font-mono text-secondary-text">
                          {formatNumber(item.currentPrice, 2)}
                        </td>
                        <td className="px-3 py-3 font-mono font-semibold" style={getPriceChangeStyle(item.changePct)}>
                          {formatChangePct(item.changePct)}
                        </td>
                        <td className="px-3 py-3 font-mono text-secondary-text">
                          {formatNumber(item.volumeRatio, 2)}
                        </td>
                        <td className="px-3 py-3 font-mono text-secondary-text">
                          {formatNumber(item.turnoverRate, 2)}{isPresent(item.turnoverRate) ? '%' : ''}
                        </td>
                        <td className="truncate px-3 py-3 text-secondary-text" title={item.modelUsed || '未记录模型'}>
                          {formatModelName(item.modelUsed)}
                        </td>
                        <td className="px-3 py-3">
                          <button
                            type="button"
                            className="rounded-lg border border-primary/35 bg-primary/8 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/14"
                            onClick={(event) => {
                              event.stopPropagation();
                              onSelectRecord(item.id);
                              onClose();
                            }}
                          >
                            查看报告
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
};
