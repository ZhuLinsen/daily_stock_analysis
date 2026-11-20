import React, { useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { StockKLineItem } from '../../api/stocks';
import type { ReportLanguage, ReportStrategy } from '../../types/analysis';
import {
  enrichBarsWithMovingAverages,
  parseStrategyPriceLevel,
  type PriceChartDatum,
} from '../../utils/priceChart';
import { normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportPriceLevelsChartProps {
  bars: StockKLineItem[];
  strategy?: ReportStrategy;
  language?: ReportLanguage;
  onRetry?: () => void;
}

const LevelsTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ payload?: PriceChartDatum }>;
  isEnglish: boolean;
}> = ({ active, payload, isEnglish }) => {
  if (!active || !payload?.[0]?.payload) {
    return null;
  }
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-border/70 bg-card/95 px-2.5 py-1.5 text-[11px] shadow-card">
      <div className="font-mono font-semibold text-foreground">{d.date}</div>
      <div className="mt-1 space-y-0.5 text-secondary-text">
        <div>{isEnglish ? 'Close' : '收盘'}: <span className="font-mono text-foreground">{d.close.toFixed(2)}</span></div>
        {d.ma5 != null ? <div>MA5: <span className="font-mono text-amber-500">{d.ma5.toFixed(2)}</span></div> : null}
        {d.ma20 != null ? <div>MA20: <span className="font-mono text-violet-400">{d.ma20.toFixed(2)}</span></div> : null}
      </div>
    </div>
  );
};

export const ReportPriceLevelsChart: React.FC<ReportPriceLevelsChartProps> = ({
  bars,
  strategy,
  language = 'zh',
  onRetry,
}) => {
  const isEnglish = normalizeReportLanguage(language) === 'en';
  const data = useMemo(() => enrichBarsWithMovingAverages(bars, 60), [bars]);

  const idealBuy = parseStrategyPriceLevel(strategy?.idealBuy);
  const secondaryBuy = parseStrategyPriceLevel(strategy?.secondaryBuy);
  const stopLoss = parseStrategyPriceLevel(strategy?.stopLoss);
  const takeProfit = parseStrategyPriceLevel(strategy?.takeProfit);

  const yDomain = useMemo<[number, number]>(() => {
    const vals: number[] = [];
    for (const d of data) {
      vals.push(d.low, d.high, d.close);
    }
    for (const lvl of [idealBuy, secondaryBuy, stopLoss, takeProfit]) {
      if (lvl != null) vals.push(lvl);
    }
    if (vals.length === 0) return [0, 100];
    const minVal = Math.min(...vals);
    const maxVal = Math.max(...vals);
    const pad = Math.max((maxVal - minVal) * 0.06, minVal * 0.01);
    return [Number((minVal - pad).toFixed(2)), Number((maxVal + pad).toFixed(2))];
  }, [data, idealBuy, secondaryBuy, stopLoss, takeProfit]);

  if (data.length === 0) {
    return (
      <div className="mb-3 flex flex-wrap items-center justify-center gap-2 rounded-xl border border-border/60 bg-background/40 px-3 py-4 text-center text-xs text-muted-text">
        <span>{isEnglish ? 'No daily K-line history available for price overlay.' : '暂无可用的日线历史行情数据。'}</span>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-border/70 px-2 py-0.5 text-[11px] font-medium text-foreground hover:bg-hover"
          >
            {isEnglish ? 'Retry' : '重新加载'}
          </button>
        ) : null}
      </div>
    );
  }

  const latest = data[data.length - 1];

  return (
    <div className="mb-3 rounded-xl border border-border/70 bg-card/60 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <div className="flex flex-wrap items-center gap-3 text-secondary-text">
          <span>
            {isEnglish ? 'Close' : '最新收盘'}: <strong className="font-mono text-foreground">{latest.close.toFixed(2)}</strong>
          </span>
          {idealBuy != null ? (
            <span className="text-sky-500">
              {isEnglish ? 'Ideal Buy' : '理想买点'}: <strong className="font-mono">{idealBuy}</strong>
            </span>
          ) : null}
          {secondaryBuy != null ? (
            <span className="text-amber-500">
              {isEnglish ? 'Secondary Buy' : '次优买点'}: <strong className="font-mono">{secondaryBuy}</strong>
            </span>
          ) : null}
          {stopLoss != null ? (
            <span className="text-rose-500">
              {isEnglish ? 'Stop Loss' : '止损位'}: <strong className="font-mono">{stopLoss}</strong>
            </span>
          ) : null}
          {takeProfit != null ? (
            <span className="text-emerald-500">
              {isEnglish ? 'Target' : '止盈目标'}: <strong className="font-mono">{takeProfit}</strong>
            </span>
          ) : null}
        </div>
        <span className="font-mono text-[10px] text-muted-text">
          {data[0].date} ~ {latest.date} ({data.length}D)
        </span>
      </div>

      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.18} />
            <XAxis dataKey="shortDate" tick={{ fontSize: 10 }} minTickGap={18} />
            <YAxis domain={yDomain} tick={{ fontSize: 10 }} width={52} />
            <Tooltip content={<LevelsTooltip isEnglish={isEnglish} />} />
            <Area
              type="monotone"
              dataKey="close"
              stroke="#38bdf8"
              strokeWidth={2}
              fill="#38bdf8"
              fillOpacity={0.14}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="ma5"
              stroke="#f59e0b"
              strokeWidth={1.3}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="ma20"
              stroke="#a78bfa"
              strokeWidth={1.3}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            {takeProfit != null ? (
              <ReferenceLine
                y={takeProfit}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{ value: `${isEnglish ? 'TP' : '盈'} ${takeProfit}`, position: 'insideTopRight', fill: '#10b981', fontSize: 10 }}
              />
            ) : null}
            {idealBuy != null ? (
              <ReferenceLine
                y={idealBuy}
                stroke="#0ea5e9"
                strokeDasharray="4 4"
                label={{ value: `${isEnglish ? 'Buy' : '买'} ${idealBuy}`, position: 'insideBottomRight', fill: '#0ea5e9', fontSize: 10 }}
              />
            ) : null}
            {secondaryBuy != null ? (
              <ReferenceLine
                y={secondaryBuy}
                stroke="#f59e0b"
                strokeDasharray="3 3"
                label={{ value: `${isEnglish ? '2nd' : '次'} ${secondaryBuy}`, position: 'insideTopLeft', fill: '#f59e0b', fontSize: 10 }}
              />
            ) : null}
            {stopLoss != null ? (
              <ReferenceLine
                y={stopLoss}
                stroke="#f43f5e"
                strokeDasharray="5 3"
                label={{ value: `${isEnglish ? 'SL' : '损'} ${stopLoss}`, position: 'insideBottomRight', fill: '#f43f5e', fontSize: 10 }}
              />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
