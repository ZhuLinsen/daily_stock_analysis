import { lazy, Suspense, useState } from 'react';
import type React from 'react';
import { LineChart } from 'lucide-react';
import { stocksApi, type StockKLineItem } from '../../api/stocks';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

const ReportPriceLevelsChart = lazy(() => import('./ReportPriceLevelsChart').then(
  ({ ReportPriceLevelsChart }) => ({ default: ReportPriceLevelsChart }),
));

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  language?: ReportLanguage;
  recordId?: number;
  stockCode?: string;
}

interface ChartState {
  key: string;
  open: boolean;
  loading: boolean;
  bars: StockKLineItem[] | null;
  failed: boolean;
}

interface StrategyItemProps {
  label: string;
  value?: string;
  tone: string;
}

const StrategyItem: React.FC<StrategyItemProps> = ({
  label,
  value,
  tone,
}) => (
  <div className="home-subpanel home-strategy-card p-3" style={{ ['--home-strategy-tone' as string]: `var(${tone})` }}>
    <div className="flex flex-col">
      <span className="home-strategy-label mb-0.5 text-xs">{label}</span>
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

/**
 * 策略点位区组件 - 终端风格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({
  strategy,
  language = 'zh',
  recordId,
  stockCode,
}) => {
  const symbol = stockCode?.trim();
  const reportKey = `${recordId ?? 0}:${symbol?.toUpperCase() ?? ''}`;
  const [previousReportKey, setPreviousReportKey] = useState(reportKey);
  const [chartState, setChartState] = useState<ChartState>({
    key: '',
    open: false,
    loading: false,
    bars: null,
    failed: false,
  });
  if (previousReportKey !== reportKey) {
    setPreviousReportKey(reportKey);
    if (chartState.loading) {
      // Returning to this report must never restore an invalidated loading state.
      setChartState({ ...chartState, open: false, loading: false });
    }
  }

  if (!strategy) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const canShowChart = Boolean(recordId && recordId > 0 && symbol);

  const isSameReport = chartState.key === reportKey;
  const showChart = isSameReport ? chartState.open : false;
  const isLoadingChart = isSameReport ? chartState.loading : false;
  const chartBars = isSameReport ? chartState.bars : null;
  const chartFailed = isSameReport && chartState.failed;

  const fetchChartBars = async () => {
    if (!symbol || !canShowChart || isLoadingChart) {
      return;
    }
    const pendingState: ChartState = {
      key: reportKey,
      open: true,
      loading: true,
      bars: null,
      failed: false,
    };
    setChartState(pendingState);
    try {
      const res = await stocksApi.getHistory(symbol, 60, 'daily');
      // Only the state installed by this request may receive its result.
      setChartState(current => current === pendingState
        ? { ...pendingState, loading: false, bars: res.data }
        : current);
    } catch {
      setChartState(current => current === pendingState
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

  const strategyItems = [
    {
      label: text.idealBuy,
      value: strategy.idealBuy,
      tone: '--home-strategy-buy',
    },
    {
      label: text.secondaryBuy,
      value: strategy.secondaryBuy,
      tone: '--home-strategy-secondary',
    },
    {
      label: text.stopLoss,
      value: strategy.stopLoss,
      tone: '--home-strategy-stop',
    },
    {
      label: text.takeProfit,
      value: strategy.takeProfit,
      tone: '--home-strategy-take',
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
            className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-card/70 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-[hsl(var(--primary))/0.5] hover:bg-hover disabled:opacity-60"
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
        <Suspense fallback={<p role="status" className="mb-3 text-xs text-muted-text">{text.priceLevelsChart.loading}</p>}>
          <ReportPriceLevelsChart
            bars={chartBars ?? []}
            failed={chartFailed}
            strategy={strategy}
            language={reportLanguage}
            onRetry={() => void fetchChartBars()}
          />
        </Suspense>
      ) : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>
    </Card>
  );
};
