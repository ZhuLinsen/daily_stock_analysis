import React, { useState } from 'react';
import { LineChart } from 'lucide-react';
import { getParsedApiError } from '../../api/error';
import { stocksApi, type StockKLineItem } from '../../api/stocks';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { ReportPriceLevelsChart } from './ReportPriceLevelsChart';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  language?: ReportLanguage;
  recordId?: number;
  stockCode?: string;
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
  const [showChart, setShowChart] = useState(false);
  const [isLoadingChart, setIsLoadingChart] = useState(false);
  const [chartBars, setChartBars] = useState<StockKLineItem[] | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  if (!strategy) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const isEnglish = reportLanguage === 'en';
  const canShowChart = Boolean(
    recordId && recordId > 0 && stockCode && typeof stocksApi?.getHistory === 'function',
  );

  const handleToggleChart = async () => {
    const nextOpen = !showChart;
    setShowChart(nextOpen);
    if (!nextOpen || chartBars !== null || !stockCode || !canShowChart || isLoadingChart) {
      return;
    }
    setIsLoadingChart(true);
    setChartError(null);
    try {
      const res = await stocksApi.getHistory(stockCode, 60, 'daily');
      setChartBars(res.data || []);
    } catch (err) {
      setChartError(getParsedApiError(err).message);
    } finally {
      setIsLoadingChart(false);
    }
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
            onClick={() => void handleToggleChart()}
            disabled={isLoadingChart}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-card/70 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-[hsl(var(--primary))/0.5] hover:bg-hover disabled:opacity-60"
          >
            <LineChart className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
            <span>
              {isLoadingChart
                ? (isEnglish ? 'Loading Chart...' : '加载行情...')
                : (isEnglish ? 'Levels Chart' : '价格点位图')}
            </span>
          </button>
        ) : undefined}
        className="mb-3"
      />
      {chartError ? <p className="mb-3 text-xs text-rose-500">{chartError}</p> : null}
      {showChart && chartBars ? (
        <ReportPriceLevelsChart bars={chartBars} strategy={strategy} language={reportLanguage} />
      ) : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>
    </Card>
  );
};
