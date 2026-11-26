import React, { useId, useMemo, useState } from 'react';
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { StockHistoryResponse, StockKLineItem } from '../../api/stocks';
import type { ReportLanguage, ReportStrategy } from '../../types/analysis';
import {
  computeQuantTelemetry,
  enrichBarsWithMovingAverages,
  formatChartAxisPrice,
  formatChartDisplayPrice,
  parseStrategyPriceLevel,
  type PriceChartDatum,
} from '../../utils/priceChart';
import { getQuantChartText, type QuantChartText } from '../../utils/quantChartText';
import { getReportText } from '../../utils/reportLanguage';

interface ReportPriceLevelsChartProps {
  bars: StockKLineItem[];
  failed?: boolean;
  ohlcSynthesized?: boolean | null;
  priceAdjustment?: StockHistoryResponse['priceAdjustment'];
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

type WindowLimit = 20 | 40 | 60 | 0;
type SubPanelMode = 'none' | 'rsi' | 'macd' | 'kdj';

function extractIsoDate(value?: string): string | null {
  if (!value) {
    return null;
  }
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value.trim());
  return match ? match[1] : null;
}

function formatSignedPct(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
}

const toolbarBtnClass = (active: boolean): string =>
  `rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
    active
      ? 'border-[hsl(var(--primary))/0.65] bg-[hsl(var(--primary))/0.15] text-[hsl(var(--primary))]'
      : 'border-border/60 bg-background/40 text-muted-text hover:bg-hover hover:text-foreground'
  }`;

const LevelsTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ payload?: PriceChartDatum }>;
  closeLabel: string;
  highLowLabel: string;
  qText: QuantChartText;
  isUnadjusted?: boolean;
}> = ({ active, payload, closeLabel, highLowLabel, qText, isUnadjusted = false }) => {
  if (!active || !payload?.[0]?.payload) {
    return null;
  }
  const d = payload[0].payload;
  const hasRange =
    d.hasValidRange !== false
    && Number.isFinite(d.high)
    && Number.isFinite(d.low)
    && d.high > 0
    && d.low > 0;
  return (
    <div className="min-w-[152px] rounded-xl border border-border/80 bg-card/95 px-3 py-2 text-[11px] shadow-lg backdrop-blur-sm">
      <div className="border-b border-border/50 pb-1 font-mono font-semibold text-foreground">{d.date}</div>
      <div className="mt-1.5 space-y-1 text-secondary-text">
        <div className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
            {closeLabel}:
          </span>
          <span className="font-mono font-semibold text-foreground">{formatChartDisplayPrice(d.close)}</span>
        </div>
        {d.open != null && Number.isFinite(d.open) ? (
          <div className="flex items-center justify-between gap-4">
            <span className="text-muted-text">{qText.open}:</span>
            <span className="font-mono text-secondary-text">{formatChartDisplayPrice(d.open)}</span>
          </div>
        ) : null}
        {hasRange ? (
          <div className="flex items-center justify-between gap-4">
            <span className="text-muted-text">{highLowLabel}:</span>
            <span className="font-mono text-secondary-text">
              {formatChartDisplayPrice(d.high)} / {formatChartDisplayPrice(d.low)}
            </span>
          </div>
        ) : null}
        {!isUnadjusted && d.ma5 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              MA5:
            </span>
            <span className="font-mono text-amber-400">{formatChartDisplayPrice(d.ma5)}</span>
          </div>
        ) : null}
        {!isUnadjusted && d.ma20 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
              MA20:
            </span>
            <span className="font-mono text-violet-400">{formatChartDisplayPrice(d.ma20)}</span>
          </div>
        ) : null}
        {!isUnadjusted && d.ma60 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-pink-400" />
              MA60:
            </span>
            <span className="font-mono text-pink-400">{formatChartDisplayPrice(d.ma60)}</span>
          </div>
        ) : null}
        {!isUnadjusted && d.bollUpper != null && d.bollLower != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
              BOLL:
            </span>
            <span className="font-mono text-cyan-400">
              {formatChartDisplayPrice(d.bollUpper)} / {formatChartDisplayPrice(d.bollLower)}
            </span>
          </div>
        ) : null}
        {!isUnadjusted && d.rsi14 != null ? (
          <div className="flex items-center justify-between gap-4">
            <span className="text-muted-text">RSI(14):</span>
            <span className="font-mono text-sky-300">{d.rsi14.toFixed(1)}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
};

const QuantSubPanelTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ payload?: PriceChartDatum }>;
  subPanel: Exclude<SubPanelMode, 'none'>;
}> = ({ active, payload, subPanel }) => {
  if (!active || !payload?.[0]?.payload) {
    return null;
  }
  const d = payload[0].payload;
  const hasActiveValues =
    (subPanel === 'rsi' && d.rsi14 != null)
    || (subPanel === 'macd' && (d.macdDif != null || d.macdDea != null || d.macdHist != null))
    || (subPanel === 'kdj' && (d.kdjK != null || d.kdjD != null || d.kdjJ != null));
  if (!hasActiveValues) {
    return null;
  }
  return (
    <div className="min-w-[128px] rounded-lg border border-border/80 bg-card/95 px-2.5 py-1.5 text-[10px] shadow-md">
      <div className="border-b border-border/50 pb-0.5 font-mono font-semibold text-foreground">{d.date}</div>
      <div className="mt-1 space-y-0.5 font-mono text-secondary-text">
        {subPanel === 'rsi' && d.rsi14 != null ? (
          <div className="flex justify-between gap-3">
            <span>RSI(14)</span>
            <span className="text-sky-300">{d.rsi14.toFixed(1)}</span>
          </div>
        ) : null}
        {subPanel === 'macd' ? (
          <>
            {d.macdDif != null ? (
              <div className="flex justify-between gap-3">
                <span>DIF</span>
                <span className="text-amber-400">{d.macdDif.toFixed(3)}</span>
              </div>
            ) : null}
            {d.macdDea != null ? (
              <div className="flex justify-between gap-3">
                <span>DEA</span>
                <span className="text-violet-400">{d.macdDea.toFixed(3)}</span>
              </div>
            ) : null}
            {d.macdHist != null ? (
              <div className="flex justify-between gap-3">
                <span>HIST</span>
                <span className={d.macdHist >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {d.macdHist.toFixed(3)}
                </span>
              </div>
            ) : null}
          </>
        ) : null}
        {subPanel === 'kdj' ? (
          <>
            {d.kdjK != null ? (
              <div className="flex justify-between gap-3">
                <span>K</span>
                <span className="text-sky-400">{d.kdjK.toFixed(1)}</span>
              </div>
            ) : null}
            {d.kdjD != null ? (
              <div className="flex justify-between gap-3">
                <span>D</span>
                <span className="text-amber-400">{d.kdjD.toFixed(1)}</span>
              </div>
            ) : null}
            {d.kdjJ != null ? (
              <div className="flex justify-between gap-3">
                <span>J</span>
                <span className="text-fuchsia-400">{d.kdjJ.toFixed(1)}</span>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
};

export const ReportPriceLevelsChart: React.FC<ReportPriceLevelsChartProps> = ({
  bars,
  failed = false,
  ohlcSynthesized = false,
  priceAdjustment = null,
  strategy,
  language = 'zh',
  reportCurrentPrice,
  historical = false,
  reportDate,
  onRetry,
}) => {
  const gradientId = useId().replace(/:/g, '');
  const [windowLimit, setWindowLimit] = useState<WindowLimit>(60);
  const [showMa60, setShowMa60] = useState<boolean>(false);
  const [showBoll, setShowBoll] = useState<boolean>(false);
  const [subPanel, setSubPanel] = useState<SubPanelMode>('none');

  const text = getReportText(language).priceLevelsChart;
  const qText = getQuantChartText(language);
  const isUnadjusted = priceAdjustment === 'unadjusted';

  const allData = useMemo(
    () => enrichBarsWithMovingAverages(bars, 0, { ohlcSynthesized: Boolean(ohlcSynthesized) }),
    [bars, ohlcSynthesized],
  );
  const data = useMemo(
    () => (windowLimit > 0 && allData.length > windowLimit ? allData.slice(-windowLimit) : allData),
    [allData, windowLimit],
  );

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

  const telemetry = useMemo(
    () => computeQuantTelemetry(data, { idealBuy, secondaryBuy, stopLoss, takeProfit }, { priceAdjustment }),
    [data, idealBuy, secondaryBuy, stopLoss, takeProfit, priceAdjustment],
  );

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
      if (!isUnadjusted) {
        if (d.ma5 != null) vals.push(d.ma5);
        if (d.ma20 != null) vals.push(d.ma20);
        if (showMa60 && d.ma60 != null) vals.push(d.ma60);
        if (showBoll) {
          if (d.bollUpper != null) vals.push(d.bollUpper);
          if (d.bollLower != null) vals.push(d.bollLower);
        }
      }
    }
    for (const lvl of [idealBuy, secondaryBuy, stopLoss, takeProfit]) {
      if (lvl != null) vals.push(lvl);
    }
    if (vals.length === 0) return [0, 100];
    const minVal = Math.min(...vals);
    const maxVal = Math.max(...vals);
    const decimals = maxVal < 1 ? 4 : 2;
    const pad = Math.max(
      (maxVal - minVal) * 0.08,
      Math.max(minVal, maxVal) * 0.015,
      maxVal < 1 ? 0.0002 : 0.01,
    );
    const lower = Math.max(0, Number((minVal - pad).toFixed(decimals)));
    const upper = Number((maxVal + pad).toFixed(decimals));
    return [lower, upper > lower ? upper : Number((lower + (maxVal < 1 ? 0.0004 : 0.02)).toFixed(decimals))];
  }, [data, idealBuy, secondaryBuy, stopLoss, takeProfit, showMa60, showBoll, isUnadjusted]);

  const reportDay = useMemo(() => extractIsoDate(reportDate), [reportDate]);
  const { isHistoricalBeforeWindow, reportMarkerDate } = useMemo(() => {
    if (!reportDay || data.length === 0) {
      return { isHistoricalBeforeWindow: false, reportMarkerDate: null as string | null };
    }
    const firstDate = data[0].date;
    const lastDate = data[data.length - 1].date;
    if (reportDay < firstDate) {
      return { isHistoricalBeforeWindow: true, reportMarkerDate: null };
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
        reportMarkerDate: matched?.date ?? null,
      };
    }
    return { isHistoricalBeforeWindow: false, reportMarkerDate: null };
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

  const hasTelemetry =
    telemetry.riskRewardRatio != null
    || telemetry.rsi14 != null
    || telemetry.bollBandwidthPct != null
    || telemetry.ma20BiasPct != null
    || telemetry.annualizedVolPct != null
    || telemetry.maxDrawdownPct != null
    || telemetry.macdSignal != null
    || telemetry.atrPct != null;

  const rsiToneClass =
    telemetry.rsiRegime === 'oversold'
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
      : telemetry.rsiRegime === 'overbought'
        ? 'border-rose-500/30 bg-rose-500/10 text-rose-400'
        : 'border-border/60 bg-background/40 text-secondary-text';

  const rsiRegimeText =
    telemetry.rsiRegime === 'oversold'
      ? qText.oversold
      : telemetry.rsiRegime === 'overbought'
        ? qText.overbought
        : qText.neutral;

  const macdText =
    telemetry.macdSignal === 'bullish_cross'
      ? qText.goldenCross
      : telemetry.macdSignal === 'bearish_cross'
        ? qText.deathCross
        : telemetry.macdSignal === 'bullish'
          ? qText.bullish
          : telemetry.macdSignal === 'bearish'
            ? qText.bearish
            : telemetry.macdSignal === 'neutral'
              ? qText.neutral
              : '';

  const macdToneClass =
    telemetry.macdSignal === 'bullish_cross' || telemetry.macdSignal === 'bullish'
      ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-400'
      : telemetry.macdSignal === 'bearish_cross' || telemetry.macdSignal === 'bearish'
        ? 'border-rose-500/25 bg-rose-500/10 text-rose-400'
        : 'border-border/60 bg-background/40 text-secondary-text';

  const syncId = `quant-${gradientId}`;
  const spansMultipleYears =
    data.length >= 2 && data[0].date.slice(0, 4) !== data[data.length - 1].date.slice(0, 4);
  const formatXAxisTick = (val: string): string =>
    typeof val === 'string' && val.length >= 10
      ? (spansMultipleYears ? val.slice(2, 10) : val.slice(5, 10))
      : String(val ?? '');
  const subPanelMeta = subPanel === 'none'
    ? null
    : subPanel === 'rsi'
      ? { hasData: data.some((d) => d.rsi14 != null), minBars: 15, label: qText.subRsi }
      : subPanel === 'macd'
        ? { hasData: data.some((d) => d.macdDif != null), minBars: 26, label: qText.subMacd }
        : { hasData: data.some((d) => d.kdjK != null), minBars: 9, label: qText.subKdj };

  return (
    <div className="mb-3 rounded-xl border border-border/70 bg-card/60 p-3.5 shadow-sm">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <div className="flex flex-wrap items-center gap-1.5 text-secondary-text">
          <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/50 px-2 py-0.5">
            <span>{text.latestClose}:</span>
            <strong className="font-mono text-foreground">{formatChartDisplayPrice(latest.close)}</strong>
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

      {/* Interactive Quant Controls & Telemetry Strip */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[10px]">
        <div className="flex flex-wrap items-center gap-1.5">
          {allData.length >= 2 ? (
            <div role="group" aria-label={qText.windowGroupLabel} className="inline-flex items-center gap-1">
              {(
                [
                  { value: 20 as const, label: qText.window20D },
                  { value: 40 as const, label: qText.window40D },
                  { value: 60 as const, label: qText.window60D },
                  { value: 0 as const, label: qText.windowAll },
                ] as const
              ).map((item) => (
                <button
                  key={item.label}
                  type="button"
                  aria-pressed={windowLimit === item.value}
                  onClick={() => setWindowLimit(item.value)}
                  className={toolbarBtnClass(windowLimit === item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}
          <div role="group" aria-label={qText.overlayGroupLabel} className="inline-flex items-center gap-1">
            <button
              type="button"
              aria-pressed={showMa60}
              onClick={() => setShowMa60((prev) => !prev)}
              className={toolbarBtnClass(showMa60)}
            >
              {qText.ma60}
            </button>
            <button
              type="button"
              aria-pressed={showBoll}
              onClick={() => setShowBoll((prev) => !prev)}
              className={toolbarBtnClass(showBoll)}
            >
              {qText.boll}
            </button>
          </div>
        </div>
        <div role="group" aria-label={qText.subPanelGroupLabel} className="inline-flex items-center gap-1">
          {(
            [
              { value: 'none' as const, label: qText.subOff },
              { value: 'rsi' as const, label: qText.subRsi },
              { value: 'macd' as const, label: qText.subMacd },
              { value: 'kdj' as const, label: qText.subKdj },
            ] as const
          ).map((tab) => (
            <button
              key={tab.value}
              type="button"
              aria-pressed={subPanel === tab.value}
              onClick={() => setSubPanel(tab.value)}
              className={toolbarBtnClass(subPanel === tab.value)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {hasTelemetry ? (
        <div
          data-testid="quant-telemetry-strip"
          className="mb-2.5 flex flex-wrap items-center gap-1.5 text-[10px]"
        >
          {telemetry.riskRewardRatio != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-emerald-400">
              <span>{qText.riskReward}:</span>
              <strong>1:{telemetry.riskRewardRatio.toFixed(1)}</strong>
              {telemetry.upsidePct != null && telemetry.downsidePct != null ? (
                <span className="text-[9px] opacity-85">
                  (+{telemetry.upsidePct.toFixed(1)}% / -{telemetry.downsidePct.toFixed(1)}%)
                </span>
              ) : null}
            </span>
          ) : null}
          {telemetry.rsi14 != null ? (
            <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono ${rsiToneClass}`}>
              <span>RSI(14):</span>
              <strong>{telemetry.rsi14.toFixed(1)}</strong>
              <span>· {rsiRegimeText}</span>
            </span>
          ) : null}
          {telemetry.bollBandwidthPct != null ? (
            <span
              className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono ${
                telemetry.bollSqueeze
                  ? 'border-cyan-500/35 bg-cyan-500/10 text-cyan-300'
                  : 'border-border/60 bg-background/40 text-secondary-text'
              }`}
            >
              <span>{qText.bollBandwidth}:</span>
              <strong>{telemetry.bollBandwidthPct.toFixed(1)}%</strong>
              {telemetry.bollSqueeze ? <span>· {qText.squeeze}</span> : null}
            </span>
          ) : null}
          {telemetry.macdSignal != null ? (
            <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono ${macdToneClass}`}>
              <span>MACD:</span>
              <strong>{macdText}</strong>
            </span>
          ) : null}
          {telemetry.ma20BiasPct != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 font-mono text-secondary-text">
              <span>{qText.ma20Bias}:</span>
              <strong className={telemetry.ma20BiasPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                {formatSignedPct(telemetry.ma20BiasPct)}
              </strong>
            </span>
          ) : null}
          {telemetry.annualizedVolPct != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 font-mono text-secondary-text">
              <span>{qText.annualizedVol}:</span>
              <strong className="text-foreground">{telemetry.annualizedVolPct.toFixed(1)}%</strong>
            </span>
          ) : null}
          {telemetry.maxDrawdownPct != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 font-mono text-secondary-text">
              <span>{qText.maxDrawdown}:</span>
              <strong className="text-rose-400">{telemetry.maxDrawdownPct.toFixed(1)}%</strong>
            </span>
          ) : null}
          {telemetry.atrPct != null ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/40 px-1.5 py-0.5 font-mono text-secondary-text">
              <span>{qText.atrPct}:</span>
              <strong className="text-foreground">{telemetry.atrPct.toFixed(2)}%</strong>
            </span>
          ) : null}
        </div>
      ) : null}

      {isUnadjusted ? (
        <p role="status" className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-400">
          {qText.unadjustedNotice}
        </p>
      ) : null}
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
          <ComposedChart
            data={data}
            syncId={subPanel !== 'none' ? syncId : undefined}
            margin={{ top: 10, right: 16, bottom: 4, left: 2 }}
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.28} />
                <stop offset="85%" stopColor="#38bdf8" stopOpacity={0.04} />
                <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="rgba(148, 163, 184, 0.14)" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickFormatter={formatXAxisTick}
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
            <Tooltip
              content={<LevelsTooltip closeLabel={text.close} highLowLabel={text.highLow} qText={qText} isUnadjusted={isUnadjusted} />}
            />
            <Legend iconSize={9} iconType="plainline" wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
            {reportMarkerDate ? (
              <ReferenceLine
                x={reportMarkerDate}
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
            {!isUnadjusted ? (
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
            ) : null}
            {!isUnadjusted ? (
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
            ) : null}
            {!isUnadjusted && showMa60 ? (
              <Line
                type="monotone"
                dataKey="ma60"
                name="MA60"
                stroke="#f472b6"
                strokeWidth={1.35}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ) : null}
            {!isUnadjusted && showBoll ? (
              <Line
                type="monotone"
                dataKey="bollUpper"
                name={qText.bollUpper}
                stroke="#22d3ee"
                strokeDasharray="3 3"
                strokeWidth={1.1}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ) : null}
            {!isUnadjusted && showBoll ? (
              <Line
                type="monotone"
                dataKey="bollLower"
                name={qText.bollLower}
                stroke="#22d3ee"
                strokeDasharray="3 3"
                strokeWidth={1.1}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ) : null}
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

      {subPanel !== 'none' && subPanelMeta ? (
        <div
          data-testid={`quant-subpanel-${subPanel}`}
          className="mt-2 h-[126px] w-full border-t border-border/50 pt-2"
        >
          {isUnadjusted ? (
            <p
              role="status"
              className="flex h-full items-center justify-center px-3 text-center text-[11px] text-muted-text"
            >
              {qText.unadjustedNotice}
            </p>
          ) : !subPanelMeta.hasData ? (
            <p
              role="status"
              className="flex h-full items-center justify-center text-[11px] text-muted-text"
            >
              {(data.length < subPanelMeta.minBars
                ? qText.subPanelInsufficientData.replace('{minBars}', String(subPanelMeta.minBars))
                : qText.subPanelMissingHighLow
              ).replace('{indicator}', subPanelMeta.label)}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data} syncId={syncId} margin={{ top: 6, right: 16, bottom: 2, left: 2 }}>
                <CartesianGrid vertical={false} stroke="rgba(148, 163, 184, 0.12)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tickFormatter={formatXAxisTick}
                  tick={{ fontSize: 9, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={24}
                />
                <YAxis
                  domain={subPanel === 'rsi' ? [0, 100] : ['auto', 'auto']}
                  tickFormatter={(v: number) => (subPanel === 'macd' ? v.toFixed(2) : String(Math.round(v)))}
                  tick={{ fontSize: 9, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  width={54}
                />
                <Tooltip content={<QuantSubPanelTooltip subPanel={subPanel} />} />
                {subPanel === 'rsi' ? (
                  <>
                    <ReferenceLine y={70} stroke="rgba(244, 63, 94, 0.45)" strokeDasharray="3 3" />
                    <ReferenceLine y={50} stroke="rgba(148, 163, 184, 0.3)" strokeDasharray="2 2" />
                    <ReferenceLine y={30} stroke="rgba(16, 185, 129, 0.45)" strokeDasharray="3 3" />
                    <Area
                      type="monotone"
                      dataKey="rsi14"
                      name="RSI(14)"
                      stroke="#38bdf8"
                      strokeWidth={1.5}
                      fill="rgba(56, 189, 248, 0.14)"
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </>
                ) : null}
                {subPanel === 'macd' ? (
                  <>
                    <ReferenceLine y={0} stroke="rgba(148, 163, 184, 0.45)" />
                    <Bar dataKey="macdHist" name="HIST" barSize={4} isAnimationActive={false}>
                      {data.map((entry) => (
                        <Cell
                          key={entry.date}
                          fill={(entry.macdHist ?? 0) >= 0 ? 'rgba(16, 185, 129, 0.65)' : 'rgba(244, 63, 94, 0.65)'}
                        />
                      ))}
                    </Bar>
                    <Line
                      type="monotone"
                      dataKey="macdDif"
                      name="DIF"
                      stroke="#f59e0b"
                      strokeWidth={1.4}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="macdDea"
                      name="DEA"
                      stroke="#a78bfa"
                      strokeWidth={1.4}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </>
                ) : null}
                {subPanel === 'kdj' ? (
                  <>
                    <ReferenceLine y={80} stroke="rgba(244, 63, 94, 0.4)" strokeDasharray="3 3" />
                    <ReferenceLine y={20} stroke="rgba(16, 185, 129, 0.4)" strokeDasharray="3 3" />
                    <Line
                      type="monotone"
                      dataKey="kdjK"
                      name="K"
                      stroke="#38bdf8"
                      strokeWidth={1.35}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="kdjD"
                      name="D"
                      stroke="#f59e0b"
                      strokeWidth={1.35}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="kdjJ"
                      name="J"
                      stroke="#e879f9"
                      strokeWidth={1.25}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </>
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      ) : null}
    </div>
  );
};
