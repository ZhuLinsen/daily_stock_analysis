import type React from 'react';
import { useMemo, useState } from 'react';
import { Activity, ChevronDown, ChevronUp, ShieldAlert, TrendingUp } from 'lucide-react';
import { Badge, Card } from '../common';
import { toCamelCase } from '../../api/utils';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import { BACKTEST_QUANT_TEXT } from '../../locales/backtestQuantText';
import type { BacktestEquityPoint, BacktestQuantMetrics, PerformanceMetrics } from '../../types/backtest';

interface BacktestQuantInsightsProps {
  overallPerf: PerformanceMetrics | null;
  stockPerf: PerformanceMetrics | null;
  language: UiLanguage;
}

function fmtSignedPct(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

function fmtUnsignedPct(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(decimals)}%`;
}

function fmtRatio(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(decimals);
}

interface ParsedAdviceRow {
  advice: string;
  total: number;
  win: number;
  loss: number;
  neutral: number;
  winRatePct: number | null;
}

function parseAdviceBreakdown(raw: Record<string, unknown> | undefined): ParsedAdviceRow[] {
  if (!raw || typeof raw !== 'object') return [];
  const rows: ParsedAdviceRow[] = [];
  for (const [advice, bucket] of Object.entries(raw)) {
    if (!bucket || typeof bucket !== 'object') continue;
    const item = bucket as Record<string, unknown>;
    const total = Number(item.total || 0);
    if (!Number.isFinite(total) || total <= 0) continue;
    const win = Number(item.win || 0);
    const loss = Number(item.loss || 0);
    const neutral = Number(item.neutral || 0);
    const wrRaw = item.win_rate_pct ?? item.winRatePct;
    const winRatePct = typeof wrRaw === 'number' && Number.isFinite(wrRaw) ? wrRaw : null;
    rows.push({ advice, total, win, loss, neutral, winRatePct });
  }
  return rows.sort((a, b) => b.total - a.total || a.advice.localeCompare(b.advice)).slice(0, 6);
}

const EquityCurveChart: React.FC<{
  points: BacktestEquityPoint[];
  language: UiLanguage;
}> = ({ points, language }) => {
  const qt = BACKTEST_QUANT_TEXT[language];
  const chartData = useMemo(() => {
    if (points.length < 2) return null;
    const firstIndex = points[0]?.index != null ? Number(points[0].index) : null;
    const lastIndex = points[points.length - 1]?.index != null
      ? Number(points[points.length - 1].index)
      : null;
    const startsAtOrigin = firstIndex == null || firstIndex <= 1;
    const numericValues: number[] = [];
    for (const pt of points) {
      if (typeof pt.equityPct !== 'number' || !Number.isFinite(pt.equityPct)) {
        return null;
      }
      numericValues.push(pt.equityPct);
    }
    const values = startsAtOrigin ? [0, ...numericValues] : numericValues;
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const span = Math.max(1e-3, maxVal - minVal);
    const pad = span * 0.14;
    const low = minVal - pad;
    const high = maxVal + pad;
    const range = Math.max(1e-3, high - low);

    const width = 360;
    const height = 84;
    const xPad = 8;
    const yPad = 8;
    const innerW = width - xPad * 2;
    const innerH = height - yPad * 2;

    const coords = values.map((v, idx) => {
      const x = xPad + (idx / Math.max(1, values.length - 1)) * innerW;
      const y = yPad + ((high - v) / range) * innerH;
      return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)), v };
    });

    const rawZeroY = yPad + ((high - 0) / range) * innerH;
    const showZeroLine = low <= 0 && high >= 0;
    const zeroY = Number(rawZeroY.toFixed(1));
    const baselineY = Number(Math.min(height - yPad, Math.max(yPad, rawZeroY)).toFixed(1));
    const polyPoints = coords.map((c) => `${c.x},${c.y}`).join(' ');
    const latestVal = values[values.length - 1] ?? 0;
    const areaPath = [
      `M ${coords[0].x},${baselineY}`,
      ...coords.map((c) => `L ${c.x},${c.y}`),
      `L ${coords[coords.length - 1].x},${baselineY}`,
      'Z',
    ].join(' ');

    return {
      width,
      height,
      zeroY,
      showZeroLine,
      startsAtOrigin,
      firstIndex,
      lastIndex,
      polyPoints,
      areaPath,
      latestVal,
      isPositive: latestVal >= 0,
      firstDate: points[0]?.date || '',
      lastDate: points[points.length - 1]?.date || '',
    };
  }, [points]);

  if (!chartData) return null;

  const strokeColor = chartData.isPositive ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))';
  const fillColor = chartData.isPositive ? 'hsl(var(--color-success) / 0.12)' : 'hsl(var(--color-danger) / 0.12)';

  return (
    <div className="rounded-xl border border-white/10 bg-surface-elevated/40 p-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1.5 font-medium text-secondary-text">
          <TrendingUp className="h-3.5 w-3.5 text-primary" />
          {qt.equityCurveTitle}
        </span>
        <span className={`font-mono font-semibold ${chartData.isPositive ? 'text-success' : 'text-danger'}`}>
          {qt.equityCurveLatest}: {fmtSignedPct(chartData.latestVal)}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${chartData.width} ${chartData.height}`}
        className="h-20 w-full overflow-visible"
        role="img"
        aria-label={qt.equityCurveTitle}
      >
        {chartData.showZeroLine && (
          <line
            x1={8}
            x2={chartData.width - 8}
            y1={chartData.zeroY}
            y2={chartData.zeroY}
            stroke="hsl(var(--border))"
            strokeDasharray="3 3"
            strokeWidth={1}
          />
        )}
        <path d={chartData.areaPath} fill={fillColor} />
        <polyline
          fill="none"
          stroke={strokeColor}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          points={chartData.polyPoints}
        />
      </svg>
      <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-text">
        <span>
          {!chartData.startsAtOrigin && chartData.firstIndex != null
            ? (chartData.firstDate ? `#${chartData.firstIndex} · ${chartData.firstDate}` : `#${chartData.firstIndex}`)
            : (chartData.firstDate || qt.equityCurveStart)}
        </span>
        {!chartData.startsAtOrigin && chartData.firstIndex != null && (
          <span className="truncate text-[10px] opacity-80">
            {qt.equityCurveWindowHint
              .replace('{count}', String(points.length))
              .replace('{start}', String(chartData.firstIndex))}
          </span>
        )}
        <span>
          {!chartData.startsAtOrigin && chartData.lastIndex != null
            ? (chartData.lastDate ? `#${chartData.lastIndex} · ${chartData.lastDate}` : `#${chartData.lastIndex}`)
            : chartData.lastDate}
        </span>
      </div>
    </div>
  );
};

export const BacktestQuantInsights: React.FC<BacktestQuantInsightsProps> = ({
  overallPerf,
  stockPerf,
  language,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const qt = BACKTEST_QUANT_TEXT[language];
  const activePerf = stockPerf ?? overallPerf;

  const quant: BacktestQuantMetrics | null = useMemo(() => {
    if (!activePerf) return null;
    if (activePerf.quantMetrics && typeof activePerf.quantMetrics === 'object') {
      return activePerf.quantMetrics;
    }
    const diag = activePerf.diagnostics as Record<string, unknown> | undefined;
    const rawDiag = diag?.quantMetrics ?? diag?.quant_metrics;
    if (rawDiag && typeof rawDiag === 'object') {
      return toCamelCase<BacktestQuantMetrics>(rawDiag);
    }
    return null;
  }, [activePerf]);

  const adviceRows = useMemo(
    () => parseAdviceBreakdown(activePerf?.adviceBreakdown),
    [activePerf?.adviceBreakdown],
  );

  if (!activePerf) return null;

  const hasQuantSamples = Boolean(quant && (quant.sampleCount ?? 0) > 0);
  const hasRenderableCurve =
    (quant?.equityCurve?.length ?? 0) >= 2 &&
    (quant?.equityCurve ?? []).every((pt) => typeof pt.equityPct === 'number' && Number.isFinite(pt.equityPct));
  const exitEntries = Object.entries(quant?.exitReasonBreakdown ?? {}).filter(([, count]) => count > 0);
  const scopeLabel = stockPerf?.code ? `${qt.stockScopePrefix}: ${stockPerf.code}` : qt.portfolioScope;
  const profitFactorDisplay = !quant
    ? '--'
    : quant.profitFactor != null
      ? fmtRatio(quant.profitFactor)
      : quant.avgWinPct != null && quant.avgLossPct == null
        ? '∞'
        : '--';

  return (
    <Card variant="gradient" padding="sm" className="mb-3 border border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <span className="text-xs font-semibold tracking-wide text-foreground">
            {qt.panelTitle}
          </span>
          <Badge variant="info">{scopeLabel}</Badge>
          {hasQuantSamples && (
            <span className="text-[11px] font-mono text-muted-text">
              {qt.sampleTrades}:{' '}
              {formatUiText(qt.tradesCountUnit, {
                count: quant?.sampleCount ?? 0,
                active: quant?.activeTradeCount ?? 0,
              })}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((prev) => !prev)}
          aria-expanded={!collapsed}
          className="btn-secondary flex items-center gap-1 px-2.5 py-1 text-xs"
        >
          {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
          {collapsed ? qt.expandPanel : qt.collapsePanel}
        </button>
      </div>

      {!collapsed && (
        <div className="mt-3 space-y-3">
          {hasQuantSamples && quant ? (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.cumulativeReturn}</div>
                  <div
                    className={`mt-0.5 font-mono text-sm font-semibold ${
                      (quant.cumulativeReturnPct ?? 0) > 0
                        ? 'text-success'
                        : (quant.cumulativeReturnPct ?? 0) < 0
                          ? 'text-danger'
                          : 'text-foreground'
                    }`}
                  >
                    {fmtSignedPct(quant.cumulativeReturnPct)}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.profitFactor}</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-primary">
                    {profitFactorDisplay}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.expectancyPerTrade}</div>
                  <div
                    className={`mt-0.5 font-mono text-sm font-semibold ${
                      (quant.expectancyPct ?? 0) > 0
                        ? 'text-success'
                        : (quant.expectancyPct ?? 0) < 0
                          ? 'text-danger'
                          : 'text-foreground'
                    }`}
                  >
                    {fmtSignedPct(quant.expectancyPct)}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.sharpeAndSortino}</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-foreground">
                    {fmtRatio(quant.sharpeRatio)} / {fmtRatio(quant.sortinoRatio)}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.maxDrawdownAndCalmar}</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-danger">
                    {fmtUnsignedPct(quant.maxDrawdownPct)}
                    <span className="text-muted-text"> / </span>
                    <span className="text-foreground">{fmtRatio(quant.calmarRatio)}</span>
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-surface-elevated/45 px-3 py-2">
                  <div className="text-[11px] text-muted-text">{qt.payoffRatio}</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-foreground">
                    {fmtRatio(quant.payoffRatio)}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
                {hasRenderableCurve && (
                  <div className="lg:col-span-7">
                    <EquityCurveChart points={quant.equityCurve ?? []} language={language} />
                  </div>
                )}

                <div className={`${hasRenderableCurve ? 'lg:col-span-5' : 'lg:col-span-12'} flex flex-col justify-between gap-2 rounded-xl border border-white/10 bg-surface-elevated/40 p-2.5 text-xs`}>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <div className="text-[11px] text-muted-text">{qt.avgWinLoss}</div>
                      <div className="mt-0.5 font-mono font-semibold text-foreground">
                        <span className="text-success">{fmtSignedPct(quant.avgWinPct)}</span>
                        {' / '}
                        <span className="text-danger">{fmtSignedPct(quant.avgLossPct)}</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-muted-text">{qt.bestWorstTrade}</div>
                      <div className="mt-0.5 font-mono font-semibold text-foreground">
                        <span className="text-success">{fmtSignedPct(quant.bestTradePct)}</span>
                        {' / '}
                        <span className="text-danger">{fmtSignedPct(quant.worstTradePct)}</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] text-muted-text">{qt.streakRecord}</div>
                      <div className="mt-0.5 font-mono font-semibold text-foreground">
                        {formatUiText(qt.streakUnit, {
                          wins: quant.maxConsecutiveWins ?? 0,
                          losses: quant.maxConsecutiveLosses ?? 0,
                        })}
                      </div>
                    </div>
                  </div>

                  {exitEntries.length > 0 && (
                    <div className="border-t border-white/10 pt-2">
                      <div className="mb-1 text-[11px] text-muted-text">{qt.exitBreakdownTitle}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {exitEntries.map(([reason, count]) => (
                          <span
                            key={reason}
                            className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-background/40 px-2 py-0.5 text-[11px] text-secondary-text"
                          >
                            <span>{qt.exitReasons[reason] ?? reason}</span>
                            <span className="font-mono font-semibold text-foreground">{count}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 rounded-xl border border-dashed border-white/15 bg-surface-elevated/30 px-3 py-2 text-xs text-muted-text">
              <ShieldAlert className="h-4 w-4 flex-shrink-0 text-warning" />
              <span>{qt.legacyMetricsHint}</span>
            </div>
          )}

          {adviceRows.length > 0 && (
            <div className="rounded-xl border border-white/10 bg-surface-elevated/35 p-2.5">
              <div className="mb-2 text-[11px] font-medium text-muted-text">{qt.adviceBreakdownTitle}</div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {adviceRows.map((row) => (
                  <div
                    key={row.advice}
                    className="flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-background/35 px-2.5 py-1.5 text-xs"
                  >
                    <span className="truncate font-medium text-foreground">
                      {qt.adviceLabels[row.advice] ?? row.advice}
                    </span>
                    <div className="flex items-center gap-2 font-mono">
                      <span className="text-primary">
                        {row.winRatePct != null ? `${row.winRatePct.toFixed(1)}%` : '--'}
                      </span>
                      <span className="text-[11px] text-muted-text">
                        {row.win}/{row.loss}/{row.neutral}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
