import { Component, lazy, Suspense, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { LineChart } from 'lucide-react';
import { stocksApi, type StockKLineItem } from '../../api/stocks';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { computeStrategyPriceMetrics } from '../../utils/reportDashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

const ReportPriceLevelsChart = lazy(() => import('./ReportPriceLevelsChart').then(
  ({ ReportPriceLevelsChart }) => ({ default: ReportPriceLevelsChart }),
));

interface ChartErrorBoundaryProps {
  children: React.ReactNode;
  fallback: React.ReactNode;
}

interface ChartErrorBoundaryState {
  hasError: boolean;
}

class ChartErrorBoundary extends Component<ChartErrorBoundaryProps, ChartErrorBoundaryState> {
  state: ChartErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ChartErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  language?: ReportLanguage;
  recordId?: number;
  stockCode?: string;
  currentPrice?: number;
  action?: string;
  historical?: boolean;
  reportDate?: string;
}

interface ChartState {
  key: string;
  requestSeq: number;
  open: boolean;
  loading: boolean;
  bars: StockKLineItem[] | null;
  failed: boolean;
}

interface StrategyItemProps {
  label: string;
  value?: string;
  tone: string;
  deltaPct?: number;
}

const formatDeltaPct = (delta?: number): string | null => {
  if (delta === undefined || !Number.isFinite(delta)) {
    return null;
  }
  const rounded = Math.round(delta * 10) / 10;
  const sign = rounded > 0 ? '+' : '';
  return `${sign}${rounded.toFixed(1)}%`;
};

const StrategyItem: React.FC<StrategyItemProps> = ({
  label,
  value,
  tone,
  deltaPct,
}) => {
  const deltaText = formatDeltaPct(deltaPct);
  return (
    <div className="home-subpanel home-strategy-card p-3" style={{ ['--home-strategy-tone' as string]: `var(${tone})` }}>
      <div className="flex flex-col">
        <div className="mb-0.5 flex items-baseline justify-between gap-2">
          <span className="home-strategy-label text-xs">{label}</span>
          {deltaText ? (
            <span className="num font-mono text-[11px] font-medium text-muted-text">
              {deltaText}
            </span>
          ) : null}
        </div>
        <span className="home-strategy-value text-lg font-bold font-mono" style={!value ? { color: 'var(--text-muted-text)' } : undefined}>
          {value || '—'}
        </span>
      </div>
      <div
        className="absolute bottom-0 left-0 right-0 h-0.5"
        style={{ background: `linear-gradient(90deg, transparent, var(${tone}), transparent)` }}
      />
    </div>
  );
};

/**
 * 策略点位区组件 - 终端风格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({
  strategy,
  language = 'zh',
  recordId,
  stockCode,
  currentPrice,
  action,
  historical = false,
  reportDate,
}) => {
  const symbol = stockCode?.trim();
  const reportKey = `${recordId ?? 0}:${symbol?.toUpperCase() ?? ''}`;
  const activeReportKeyRef = useRef(reportKey);
  const requestSeqRef = useRef(0);
  const [activeRequestSeq, setActiveRequestSeq] = useState(0);
  useEffect(() => {
    if (activeReportKeyRef.current !== reportKey) {
      activeReportKeyRef.current = reportKey;
      requestSeqRef.current += 1;
      setActiveRequestSeq(requestSeqRef.current);
    }
  }, [reportKey]);
  const [chartState, setChartState] = useState<ChartState>({
    key: '',
    requestSeq: 0,
    open: false,
    loading: false,
    bars: null,
    failed: false,
  });

  if (!strategy) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const canShowChart = Boolean(recordId && recordId > 0 && symbol);

  const isSameReport = chartState.key === reportKey && chartState.requestSeq === activeRequestSeq;
  const showChart = isSameReport ? chartState.open : false;
  const isLoadingChart = isSameReport ? chartState.loading : false;
  const chartBars = isSameReport ? chartState.bars : null;
  const chartFailed = isSameReport && chartState.failed;

  const fetchChartBars = async () => {
    if (!symbol || !canShowChart || isLoadingChart) {
      return;
    }
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setActiveRequestSeq(requestSeq);
    const pendingState: ChartState = {
      key: reportKey,
      requestSeq,
      open: true,
      loading: true,
      bars: null,
      failed: false,
    };
    setChartState(pendingState);
    try {
      const res = await stocksApi.getHistory(symbol, 60, 'daily');
      setChartState(current => activeReportKeyRef.current === reportKey
        && requestSeqRef.current === requestSeq
        && current.requestSeq === requestSeq
        ? { ...pendingState, loading: false, bars: res.data }
        : current);
    } catch {
      setChartState(current => activeReportKeyRef.current === reportKey
        && requestSeqRef.current === requestSeq
        && current.requestSeq === requestSeq
        ? { ...pendingState, loading: false, failed: true }
        : current);
    }
  };

  const handleToggleChart = () => {
    if (showChart || chartBars?.length) {
      setChartState({ ...chartState, open: !showChart });
      return;
    }
    void fetchChartBars();
  };

  const metrics = computeStrategyPriceMetrics(strategy, currentPrice, action);
  const rrDiffersFromCurrent = Boolean(
    metrics.refBasis === 'idealBuy'
    && metrics.range?.idealBuy
    && currentPrice !== undefined
    && currentPrice > 0
    && Math.abs(currentPrice - metrics.range.idealBuy) / metrics.range.idealBuy > 0.01,
  );

  const strategyItems = [
    {
      label: text.idealBuy,
      value: strategy.idealBuy,
      tone: '--home-strategy-buy',
      deltaPct: metrics.idealBuyDeltaPct,
    },
    {
      label: text.secondaryBuy,
      value: strategy.secondaryBuy,
      tone: '--home-strategy-secondary',
      deltaPct: metrics.secondaryBuyDeltaPct,
    },
    {
      label: text.stopLoss,
      value: strategy.stopLoss,
      tone: '--home-strategy-stop',
      deltaPct: metrics.stopLossDeltaPct,
    },
    {
      label: text.takeProfit,
      value: strategy.takeProfit,
      tone: '--home-strategy-take',
      deltaPct: metrics.takeProfitDeltaPct,
    },
  ];

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        eyebrow={text.strategyPoints}
        title={text.sniperLevels}
        actions={canShowChart ? (
          <button
            type="button"
            onClick={handleToggleChart}
            aria-expanded={showChart}
            disabled={isLoadingChart}
            className="print:hidden inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-card/70 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-[hsl(var(--primary))/0.5] hover:bg-hover disabled:opacity-60"
          >
            <LineChart className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
            <span>
              {isLoadingChart
                ? text.priceLevelsChart.loading
                : text.priceLevelsChart.toggle}
            </span>
          </button>
        ) : undefined}
        className="mb-3"
      />
      {showChart && (chartBars || chartFailed) ? (
        <ChartErrorBoundary
          key={reportKey}
          fallback={(
            <div role="alert" className="mb-3 rounded-xl border border-border/60 bg-background/40 px-3 py-4 text-center text-xs text-muted-text">
              {text.priceLevelsChart.failed}
            </div>
          )}
        >
          <Suspense fallback={<p role="status" className="mb-3 text-xs text-muted-text">{text.priceLevelsChart.loading}</p>}>
            <ReportPriceLevelsChart
              bars={chartBars ?? []}
              failed={chartFailed}
              strategy={strategy}
              language={reportLanguage}
              reportCurrentPrice={currentPrice}
              historical={historical}
              reportDate={reportDate}
              onRetry={() => void fetchChartBars()}
            />
          </Suspense>
        </ChartErrorBoundary>
      ) : null}
      {metrics.range ? (
        <div
          role="img"
          aria-label={text.priceRangeRuler}
          className="home-subpanel mb-3 space-y-2 px-3.5 py-2.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              {metrics.riskRewardRatio !== undefined ? (
                <span className="home-accent-chip px-2 py-0.5 font-mono font-semibold text-foreground">
                  {text.riskRewardRatio} 1:{metrics.riskRewardRatio.toFixed(2)}
                  {rrDiffersFromCurrent ? ` (${text.rrAtEntry})` : ''}
                </span>
              ) : null}
              {metrics.priceZone === 'belowStop' ? (
                <span className="rounded-full border border-danger/35 bg-danger/10 px-2 py-0.5 text-[11px] font-semibold text-danger">
                  {text.priceBelowStop}
                </span>
              ) : null}
              {metrics.priceZone === 'aboveTarget' ? (
                <span className="rounded-full border border-success/35 bg-success/10 px-2 py-0.5 text-[11px] font-semibold text-success">
                  {text.priceAboveTarget}
                </span>
              ) : null}
              {metrics.upsidePct !== undefined ? (
                <span className="num font-mono font-medium text-success">
                  {text.upsideSpace} +{metrics.upsidePct.toFixed(1)}%
                </span>
              ) : null}
              {metrics.downsidePct !== undefined ? (
                <span className="num font-mono font-medium text-danger">
                  {text.downsideRisk} -{metrics.downsidePct.toFixed(1)}%
                </span>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-text">
              {metrics.range.currentPrice !== undefined ? (
                <span className="num font-semibold text-foreground">
                  {text.currentPriceShort}: {metrics.range.currentPrice.toFixed(2)}
                </span>
              ) : null}
              <span className="num">
                {metrics.range.stopLoss.toFixed(2)} — {metrics.range.takeProfit.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="relative h-2 w-full rounded-full bg-border/60">
            <div
              className="absolute left-0 top-0 h-2 rounded-l-full bg-danger/55"
              style={{ width: `${(metrics.range.idealBuyPct ?? 50).toFixed(1)}%` }}
            />
            <div
              className="absolute top-0 h-2 rounded-r-full bg-success/65"
              style={{
                left: `${(metrics.range.idealBuyPct ?? 50).toFixed(1)}%`,
                width: `${Math.max(0, 100 - (metrics.range.idealBuyPct ?? 50)).toFixed(1)}%`,
              }}
            />
            {metrics.range.currentPct !== undefined ? (
              <div
                aria-label={`${text.currentPriceShort}: ${metrics.range.currentPrice}`}
                className="absolute -top-0.5 h-3 w-1.5 -translate-x-1/2 rounded-full bg-foreground ring-2 ring-card"
                style={{ left: `${metrics.range.currentPct.toFixed(1)}%` }}
              />
            ) : null}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-text">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-danger/70" />
              {text.stopLoss} {metrics.range.stopLoss.toFixed(2)}
            </span>
            {metrics.range.idealBuy !== undefined ? (
              <span className="inline-flex items-center gap-1">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-[hsl(var(--primary))]" />
                {text.idealBuy} {metrics.range.idealBuy.toFixed(2)}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-success/80" />
              {text.takeProfit} {metrics.range.takeProfit.toFixed(2)}
            </span>
          </div>
        </div>
      ) : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>
    </Card>
  );
};
