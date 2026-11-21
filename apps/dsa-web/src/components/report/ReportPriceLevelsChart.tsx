import React, { useId, useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  Legend,
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
  formatChartAxisPrice,
  parseStrategyPriceLevel,
  type PriceChartDatum,
} from '../../utils/priceChart';
import { getReportText } from '../../utils/reportLanguage';

interface ReportPriceLevelsChartProps {
  bars: StockKLineItem[];
  failed?: boolean;
  strategy?: ReportStrategy;
  language?: ReportLanguage;
  reportCurrentPrice?: number;
  historical?: boolean;
  reportDate?: string;
  onRetry?: () => void;
}

interface MergedReferenceLine {
  y: number;
  stroke: string;
  strokeDasharray: string;
  label: string;
  position: 'insideTopRight' | 'insideBottomRight' | 'insideTopLeft';
}

function extractIsoDate(value?: string): string | null {
  if (!value) {
    return null;
  }
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value.trim());
  return match ? match[1] : null;
}

const LevelsTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ payload?: PriceChartDatum }>;
  closeLabel: string;
  highLowLabel: string;
}> = ({ active, payload, closeLabel, highLowLabel }) => {
  if (!active || !payload?.[0]?.payload) {
    return null;
  }
  const d = payload[0].payload;
  const hasRange = Number.isFinite(d.high) && Number.isFinite(d.low) && d.high > 0 && d.low > 0;
  return (
    <div className="min-w-[144px] rounded-xl border border-border/80 bg-card/95 px-3 py-2 text-[11px] shadow-lg backdrop-blur-sm">
      <div className="border-b border-border/50 pb-1 font-mono font-semibold text-foreground">{d.date}</div>
      <div className="mt-1.5 space-y-1 text-secondary-text">
        <div className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
            {closeLabel}:
          </span>
          <span className="font-mono font-semibold text-foreground">{d.close.toFixed(2)}</span>
        </div>
        {hasRange ? (
          <div className="flex items-center justify-between gap-4">
            <span className="text-muted-text">{highLowLabel}:</span>
            <span className="font-mono text-secondary-text">
              {d.high.toFixed(2)} / {d.low.toFixed(2)}
            </span>
          </div>
        ) : null}
        {d.ma5 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              MA5:
            </span>
            <span className="font-mono text-amber-400">{d.ma5.toFixed(2)}</span>
          </div>
        ) : null}
        {d.ma20 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
              MA20:
            </span>
            <span className="font-mono text-violet-400">{d.ma20.toFixed(2)}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export const ReportPriceLevelsChart: React.FC<ReportPriceLevelsChartProps> = ({
  bars,
  failed = false,
  strategy,
  language = 'zh',
  reportCurrentPrice,
  historical = false,
  reportDate,
  onRetry,
}) => {
  const gradientId = useId().replace(/:/g, '');
  const text = getReportText(language).priceLevelsChart;
  const data = useMemo(() => enrichBarsWithMovingAverages(bars, 60), [bars]);

  const rawLevels = [
    parseStrategyPriceLevel(strategy?.idealBuy),
    parseStrategyPriceLevel(strategy?.secondaryBuy),
    parseStrategyPriceLevel(strategy?.stopLoss),
    parseStrategyPriceLevel(strategy?.takeProfit),
  ];
  const priceScaleMismatch = useMemo(() => {
    if (data.length === 0) return false;
    if (historical && (reportCurrentPrice == null || !Number.isFinite(reportCurrentPrice) || reportCurrentPrice <= 0)) {
      return true;
    }
    if (reportCurrentPrice == null || !Number.isFinite(reportCurrentPrice) || reportCurrentPrice <= 0) {
      return false;
    }
    const latestClose = data[data.length - 1].close;
    const scaleRatio = reportCurrentPrice / latestClose;
    return scaleRatio >= 2 || scaleRatio <= 0.5;
  }, [data, historical, reportCurrentPrice]);
  const [idealBuy, secondaryBuy, stopLoss, takeProfit] = priceScaleMismatch
    ? [null, null, null, null]
    : rawLevels;

  const referenceLines = useMemo<MergedReferenceLine[]>(() => {
    const candidates: Array<{
      y: number;
      tag: string;
      stroke: string;
      strokeDasharray: string;
      position: 'insideTopRight' | 'insideBottomRight' | 'insideTopLeft';
      priority: number;
    }> = [];
    if (takeProfit != null) {
      candidates.push({
        y: takeProfit,
        tag: text.takeProfitLine,
        stroke: '#10b981',
        strokeDasharray: '4 4',
        position: 'insideTopRight',
        priority: 3,
      });
    }
    if (idealBuy != null) {
      candidates.push({
        y: idealBuy,
        tag: text.idealBuyLine,
        stroke: '#0ea5e9',
        strokeDasharray: '4 4',
        position: 'insideBottomRight',
        priority: 2,
      });
    }
    if (secondaryBuy != null) {
      candidates.push({
        y: secondaryBuy,
        tag: text.secondaryBuyLine,
        stroke: '#f59e0b',
        strokeDasharray: '3 3',
        position: 'insideTopLeft',
        priority: 1,
      });
    }
    if (stopLoss != null) {
      candidates.push({
        y: stopLoss,
        tag: text.stopLossLine,
        stroke: '#f43f5e',
        strokeDasharray: '5 3',
        position: 'insideBottomRight',
        priority: 4,
      });
    }

    const groups: Array<{
      y: number;
      tags: string[];
      stroke: string;
      strokeDasharray: string;
      position: 'insideTopRight' | 'insideBottomRight' | 'insideTopLeft';
      priority: number;
    }> = [];

    for (const item of candidates) {
      const existing = groups.find((g) => Math.abs(g.y - item.y) < 1e-6);
      if (existing) {
        existing.tags.push(item.tag);
        if (item.priority > existing.priority) {
          existing.stroke = item.stroke;
          existing.strokeDasharray = item.strokeDasharray;
          existing.position = item.position;
          existing.priority = item.priority;
        }
      } else {
        groups.push({
          y: item.y,
          tags: [item.tag],
          stroke: item.stroke,
          strokeDasharray: item.strokeDasharray,
          position: item.position,
          priority: item.priority,
        });
      }
    }

    return groups.map((g) => ({
      y: g.y,
      stroke: g.stroke,
      strokeDasharray: g.strokeDasharray,
      position: g.position,
      label: `${g.tags.join('/')} ${g.y}`,
    }));
  }, [idealBuy, secondaryBuy, stopLoss, takeProfit, text]);

  const yDomain = useMemo<[number, number]>(() => {
    const vals: number[] = [];
    for (const d of data) {
      vals.push(d.low, d.high, d.close);
      if (d.ma5 != null) vals.push(d.ma5);
      if (d.ma20 != null) vals.push(d.ma20);
    }
    for (const lvl of [idealBuy, secondaryBuy, stopLoss, takeProfit]) {
      if (lvl != null) vals.push(lvl);
    }
    if (vals.length === 0) return [0, 100];
    const minVal = Math.min(...vals);
    const maxVal = Math.max(...vals);
    const pad = Math.max((maxVal - minVal) * 0.08, minVal * 0.015);
    return [
      Math.max(0, Number((minVal - pad).toFixed(2))),
      Number((maxVal + pad).toFixed(2)),
    ];
  }, [data, idealBuy, secondaryBuy, stopLoss, takeProfit]);

  const reportDay = useMemo(() => extractIsoDate(reportDate), [reportDate]);
  const { isHistoricalBeforeWindow, reportMarkerShortDate } = useMemo(() => {
    if (!reportDay || data.length === 0) {
      return { isHistoricalBeforeWindow: false, reportMarkerShortDate: null as string | null };
    }
    const firstDate = data[0].date;
    const lastDate = data[data.length - 1].date;
    if (reportDay < firstDate) {
      return { isHistoricalBeforeWindow: true, reportMarkerShortDate: null };
    }
    if (reportDay < lastDate) {
      let matched: PriceChartDatum | null = null;
      for (const item of data) {
        if (item.date <= reportDay) {
          matched = item;
        } else {
          break;
        }
      }
      return {
        isHistoricalBeforeWindow: false,
        reportMarkerShortDate: matched?.shortDate ?? null,
      };
    }
    return { isHistoricalBeforeWindow: false, reportMarkerShortDate: null };
  }, [data, reportDay]);

  if (failed || data.length === 0) {
    return (
      <div className="mb-3 flex flex-wrap items-center justify-center gap-2 rounded-xl border border-border/60 bg-background/40 px-3 py-4 text-center text-xs text-muted-text">
        <span role={failed ? 'alert' : 'status'}>{failed ? text.failed : text.empty}</span>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded border border-border/70 px-2 py-0.5 text-[11px] font-medium text-foreground hover:bg-hover"
          >
            {text.retry}
          </button>
        ) : null}
      </div>
    );
  }

  const latest = data[data.length - 1];
  const historicalHint = isHistoricalBeforeWindow && !priceScaleMismatch && referenceLines.length > 0 && reportDay
    ? text.historicalOverlayHint
      .replace('{date}', reportDay)
      .replace('{days}', String(data.length))
    : null;

  return (
    <div className="mb-3 rounded-xl border border-border/70 bg-card/60 p-3.5 shadow-sm">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <div className="flex flex-wrap items-center gap-1.5 text-secondary-text">
          <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/50 px-2 py-0.5">
            <span>{text.latestClose}:</span>
            <strong className="font-mono text-foreground">{latest.close.toFixed(2)}</strong>
          </span>
          {idealBuy != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-sky-500/25 bg-sky-500/10 px-2 py-0.5 text-sky-400">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
              <span>{text.idealBuy}:</span>
              <strong className="font-mono">{idealBuy}</strong>
            </span>
          ) : null}
          {secondaryBuy != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              <span>{text.secondaryBuy}:</span>
              <strong className="font-mono">{secondaryBuy}</strong>
            </span>
          ) : null}
          {stopLoss != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/25 bg-rose-500/10 px-2 py-0.5 text-rose-400">
              <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
              <span>{text.stopLoss}:</span>
              <strong className="font-mono">{stopLoss}</strong>
            </span>
          ) : null}
          {takeProfit != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>{text.takeProfit}:</span>
              <strong className="font-mono">{takeProfit}</strong>
            </span>
          ) : null}
        </div>
        <span className="font-mono text-[10px] text-muted-text">
          {data[0].date} ~ {latest.date} ({data.length}D)
        </span>
      </div>
      {priceScaleMismatch ? (
        <p role="status" className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-400">
          {text.priceScaleMismatch}
        </p>
      ) : null}
      {historicalHint ? (
        <p role="status" className="mb-2 rounded-lg border border-sky-500/25 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-300">
          {historicalHint}
        </p>
      ) : null}

      <div className="h-[232px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 16, bottom: 4, left: 2 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.28} />
                <stop offset="85%" stopColor="#38bdf8" stopOpacity={0.04} />
                <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="rgba(148, 163, 184, 0.14)" strokeDasharray="3 3" />
            <XAxis
              dataKey="shortDate"
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
              minTickGap={20}
            />
            <YAxis
              domain={yDomain}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickFormatter={formatChartAxisPrice}
              axisLine={false}
              tickLine={false}
              width={54}
            />
            <Tooltip content={<LevelsTooltip closeLabel={text.close} highLowLabel={text.highLow} />} />
            <Legend iconSize={9} iconType="plainline" wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
            {reportMarkerShortDate ? (
              <ReferenceLine
                x={reportMarkerShortDate}
                stroke="rgba(148, 163, 184, 0.45)"
                strokeDasharray="3 3"
                label={{ value: text.reportDateLine, position: 'insideTop', fill: '#94a3b8', fontSize: 10 }}
              />
            ) : null}
            <Area
              type="monotone"
              dataKey="close"
              name={text.close}
              stroke="#38bdf8"
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="ma5"
              name="MA5"
              stroke="#f59e0b"
              strokeWidth={1.35}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="ma20"
              name="MA20"
              stroke="#a78bfa"
              strokeWidth={1.35}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            {referenceLines.map((line) => (
              <ReferenceLine
                key={`${line.y}-${line.label}`}
                y={line.y}
                stroke={line.stroke}
                strokeWidth={1.25}
                strokeDasharray={line.strokeDasharray}
                label={{
                  value: line.label,
                  position: line.position,
                  fill: line.stroke,
                  fontSize: 10,
                }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
