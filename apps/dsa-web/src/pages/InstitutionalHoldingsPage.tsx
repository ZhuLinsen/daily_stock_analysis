import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  CalendarClock,
  Database,
  ExternalLink,
  FileSearch,
  Minus,
  PieChart,
  RefreshCw,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ParsedApiError } from '../api/error';
import {
  DEFAULT_INSTITUTIONAL_MANAGER_CIK,
  institutionalHoldingsApi,
  type InstitutionalHoldingAnalysis,
  type InstitutionalHoldingDelta,
  type InstitutionalHoldingImportResult,
  type InstitutionalHoldingStatus,
} from '../api/institutionalHoldings';
import { ApiErrorAlert, AppPage, Card, EmptyState, PageHeader, StatCard } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiLanguage } from '../i18n/uiText';
import { cn } from '../utils/cn';

const CHART_COLORS = ['#0891b2', '#2563eb', '#7c3aed', '#d97706', '#059669', '#475569', '#be123c', '#4f46e5'];

const COPY = {
  zh: {
    eyebrow: 'SEC 13F · Public disclosure',
    title: '段永平公开仓位观察',
    description: '以 H&H International Investment 的公开 13F 申报为代理，观察美股多头仓位、集中度与季度持股数量变化。',
    refresh: '更新 SEC 数据',
    refreshing: '正在同步 SEC',
    totalValue: '申报总市值',
    totalValueHint: '仅含 13F 可申报证券',
    top4: '前四大集中度',
    top4Hint: '组合高度集中时需关注单一公司风险',
    top6: '前六大集中度',
    top6Hint: '按当前申报市值计算',
    reportPeriod: '报告期',
    acceptedAt: 'SEC 接收时间',
    holdingsTitle: '当前仓位权重',
    holdingsDescription: '按最新季度申报市值排序；图表展示前八项。',
    changesTitle: '季度持股变化',
    changesDescription: '变化依据申报股数，不把价格上涨或下跌误判成买卖。',
    issuer: '标的',
    status: '变化',
    shares: '当前股数',
    delta: '环比股数',
    weight: '权重',
    value: '申报市值',
    source: 'SEC 原始申报',
    primaryFiling: '主申报文件',
    infoTable: '持仓明细 XML',
    filed: '提交日期',
    emptyTitle: '还没有导入 13F 数据',
    emptyDescription: '点击下方按钮导入 H&H 最近八个有效报告期，再生成仓位与季度变化分析。',
    importNow: '导入并生成分析',
    disclosureTitle: '如何理解这份数据',
    disclosureLead: '这是延迟披露的公开美股多头持仓代理，不等于段永平本人实时、完整的投资组合。',
    importSummary: '同步完成：处理 {processed} 期，新增 {created} 期，保存 {holdings} 条持仓。',
    importWarnings: '其中 {count} 个申报文件未能导入，已保留可用结果。',
    errorTitle: '公开仓位加载失败',
    errorMessage: '暂时无法读取公开仓位数据，请稍后重试。',
    noCurrentHoldings: '最新申报中没有可展示的当前持仓。',
    new: '新进',
    increased: '增持',
    decreased: '减持',
    unchanged: '不变',
    exited: '退出',
    secLinkLabel: '在新窗口打开 SEC 原始文件',
  },
  en: {
    eyebrow: 'SEC 13F · Public disclosure',
    title: 'Duan Yongping public holdings',
    description: 'Uses H&H International Investment filings as a proxy for disclosed US long positions, concentration, and quarter-over-quarter share changes.',
    refresh: 'Refresh SEC data',
    refreshing: 'Syncing SEC data',
    totalValue: 'Reported value',
    totalValueHint: 'Only 13F-reportable securities',
    top4: 'Top-four concentration',
    top4Hint: 'High concentration increases company-specific risk',
    top6: 'Top-six concentration',
    top6Hint: 'Based on current reported market value',
    reportPeriod: 'Report period',
    acceptedAt: 'SEC accepted',
    holdingsTitle: 'Current reported weights',
    holdingsDescription: 'Sorted by reported market value; the chart shows the top eight positions.',
    changesTitle: 'Quarterly share changes',
    changesDescription: 'Changes use reported share counts, so price movement is not misclassified as trading.',
    issuer: 'Issuer',
    status: 'Change',
    shares: 'Current shares',
    delta: 'QoQ shares',
    weight: 'Weight',
    value: 'Reported value',
    source: 'Original SEC filing',
    primaryFiling: 'Primary filing',
    infoTable: 'Holdings XML',
    filed: 'Filed',
    emptyTitle: 'No 13F data has been imported',
    emptyDescription: 'Import H&H’s latest eight effective report periods to generate holdings and quarter-over-quarter analysis.',
    importNow: 'Import and analyze',
    disclosureTitle: 'How to interpret this data',
    disclosureLead: 'This is a delayed proxy for disclosed US long positions, not Duan Yongping’s complete or real-time personal portfolio.',
    importSummary: 'Sync complete: {processed} periods processed, {created} created, {holdings} holdings saved.',
    importWarnings: '{count} filing files could not be imported; available results are still shown.',
    errorTitle: 'Could not load public holdings',
    errorMessage: 'Public holdings are temporarily unavailable. Please try again.',
    noCurrentHoldings: 'The latest filing has no current holdings to display.',
    new: 'New',
    increased: 'Increased',
    decreased: 'Decreased',
    unchanged: 'Unchanged',
    exited: 'Exited',
    secLinkLabel: 'Open the original SEC file in a new tab',
  },
} as const;

function getLocale(language: UiLanguage): string {
  return language === 'en' ? 'en-US' : 'zh-CN';
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatCurrency(value: number | null | undefined, language: UiLanguage): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return new Intl.NumberFormat(getLocale(language), {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatNumber(value: number | string | null | undefined, language: UiLanguage): string {
  const parsed = toNumber(value);
  if (parsed === null) {
    return '—';
  }
  return new Intl.NumberFormat(getLocale(language), { maximumFractionDigits: 0 }).format(parsed);
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(2)}%`;
}

function formatDate(value: string | null | undefined, language: UiLanguage, withTime = false): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(getLocale(language), withTime
    ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }
    : { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

function interpolate(template: string, params: Record<string, number>): string {
  return Object.entries(params).reduce(
    (result, [key, value]) => result.replace(`{${key}}`, String(value)),
    template,
  );
}

function getHttpStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') {
    return undefined;
  }
  const response = (error as { response?: { status?: number } }).response;
  return response?.status;
}

function buildParsedError(error: unknown, title: string, fallbackMessage: string): ParsedApiError {
  if (error && typeof error === 'object' && 'parsedError' in error) {
    const parsed = (error as { parsedError?: ParsedApiError }).parsedError;
    if (parsed) {
      return parsed;
    }
  }
  const rawMessage = error instanceof Error ? error.message : fallbackMessage;
  return { title, message: fallbackMessage, rawMessage, status: getHttpStatus(error), category: 'http_error' };
}

function StatusBadge({ status, language }: { status: InstitutionalHoldingStatus; language: UiLanguage }) {
  const copy = COPY[language];
  const styles: Record<InstitutionalHoldingStatus, string> = {
    new: 'border-cyan/30 bg-cyan/10 text-cyan',
    increased: 'border-success/30 bg-success/10 text-success',
    decreased: 'border-warning/30 bg-warning/10 text-warning',
    unchanged: 'border-border bg-surface-2 text-secondary-text',
    exited: 'border-danger/30 bg-danger/10 text-danger',
  };
  const Icon = status === 'new' || status === 'increased'
    ? ArrowUpRight
    : status === 'decreased' || status === 'exited'
      ? ArrowDownRight
      : Minus;

  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', styles[status])}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {copy[status]}
    </span>
  );
}

function SourceLink({ href, children, label }: { href: string; children: React.ReactNode; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border/70 bg-card/70 px-3 py-2 text-sm font-medium text-cyan transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan"
      aria-label={`${children}，${label}`}
    >
      {children}
      <ExternalLink className="h-4 w-4" aria-hidden="true" />
    </a>
  );
}

const InstitutionalHoldingsPage: React.FC = () => {
  const { language } = useUiLanguage();
  const copy = COPY[language];
  const [analysis, setAnalysis] = useState<InstitutionalHoldingAnalysis | null>(null);
  const [importResult, setImportResult] = useState<InstitutionalHoldingImportResult | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const requestSequence = useRef(0);

  const loadAnalysis = useCallback(async () => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setLoading(true);
    setError(null);
    try {
      const data = await institutionalHoldingsApi.getLatest();
      if (requestSequence.current !== sequence) {
        return;
      }
      setAnalysis(data);
      setNotFound(false);
    } catch (caught) {
      if (requestSequence.current !== sequence) {
        return;
      }
      if (getHttpStatus(caught) === 404) {
        setAnalysis(null);
        setNotFound(true);
      } else {
        setError(buildParsedError(caught, copy.errorTitle, copy.errorMessage));
      }
    } finally {
      if (requestSequence.current === sequence) {
        setLoading(false);
      }
    }
  }, [copy.errorMessage, copy.errorTitle]);

  useEffect(() => {
    void loadAnalysis();
    return () => {
      requestSequence.current += 1;
    };
  }, [loadAnalysis]);

  const refreshFromSec = useCallback(async () => {
    setImporting(true);
    setError(null);
    setImportResult(null);
    try {
      const result = await institutionalHoldingsApi.importRecent();
      setImportResult(result);
      await loadAnalysis();
    } catch (caught) {
      setError(buildParsedError(caught, copy.errorTitle, copy.errorMessage));
    } finally {
      setImporting(false);
    }
  }, [copy.errorMessage, copy.errorTitle, loadAnalysis]);

  const currentHoldings = useMemo(
    () => (analysis?.holdings ?? [])
      .filter((holding) => holding.currentValueUsd !== null && holding.currentWeightPct !== null)
      .sort((left, right) => (right.currentValueUsd ?? 0) - (left.currentValueUsd ?? 0)),
    [analysis],
  );

  const chartData = useMemo(
    () => currentHoldings.slice(0, 8).map((holding) => ({
      name: holding.issuerName,
      weight: holding.currentWeightPct ?? 0,
    })),
    [currentHoldings],
  );

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow={copy.eyebrow}
          title={copy.title}
          description={copy.description}
          actions={(
            <button
              type="button"
              className="btn-primary inline-flex min-h-11 items-center gap-2"
              onClick={() => void refreshFromSec()}
              disabled={importing || loading}
            >
              <RefreshCw className={cn('h-4 w-4', importing ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
              {importing ? copy.refreshing : copy.refresh}
            </button>
          )}
        />

        {error ? <ApiErrorAlert error={error} actionLabel={copy.refresh} onAction={() => void refreshFromSec()} /> : null}

        {importResult ? (
          <div className="rounded-2xl border border-success/25 bg-success/10 px-4 py-3 text-sm text-foreground" role="status">
            <p className="font-medium">
              {interpolate(copy.importSummary, {
                processed: importResult.processed,
                created: importResult.created,
                holdings: importResult.holdingsSaved,
              })}
            </p>
            {importResult.errors.length ? (
              <p className="mt-1 flex items-center gap-2 text-warning">
                <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                {interpolate(copy.importWarnings, { count: importResult.errors.length })}
              </p>
            ) : null}
          </div>
        ) : null}

        {loading && !analysis ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label={language === 'zh' ? '正在加载公开仓位' : 'Loading public holdings'}>
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-28 animate-pulse rounded-2xl border border-border/70 bg-card/60 motion-reduce:animate-none" />
            ))}
          </div>
        ) : null}

        {!loading && notFound ? (
          <EmptyState
            icon={<FileSearch className="h-9 w-9" aria-hidden="true" />}
            title={copy.emptyTitle}
            description={copy.emptyDescription}
            action={(
              <button type="button" className="btn-primary min-h-11" onClick={() => void refreshFromSec()} disabled={importing}>
                {importing ? copy.refreshing : copy.importNow}
              </button>
            )}
          />
        ) : null}

        {analysis ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label={copy.totalValue}
                value={formatCurrency(analysis.current.totalValueUsd, language)}
                hint={copy.totalValueHint}
                icon={<Database className="h-5 w-5" aria-hidden="true" />}
                tone="primary"
              />
              <StatCard
                label={copy.top4}
                value={formatPercent(analysis.top4ConcentrationPct)}
                hint={copy.top4Hint}
                icon={<PieChart className="h-5 w-5" aria-hidden="true" />}
                tone={analysis.top4ConcentrationPct >= 75 ? 'warning' : 'default'}
              />
              <StatCard
                label={copy.top6}
                value={formatPercent(analysis.top6ConcentrationPct)}
                hint={copy.top6Hint}
                icon={<Building2 className="h-5 w-5" aria-hidden="true" />}
              />
              <StatCard
                label={copy.reportPeriod}
                value={formatDate(analysis.current.reportPeriod, language)}
                hint={`${copy.acceptedAt}: ${formatDate(analysis.current.acceptedAt, language, true)}`}
                icon={<CalendarClock className="h-5 w-5" aria-hidden="true" />}
              />
            </div>

            <section className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
              <Card padding="lg" className="min-w-0">
                <div className="mb-4">
                  <h2 className="text-lg font-semibold text-foreground">{copy.holdingsTitle}</h2>
                  <p className="mt-1 text-sm text-secondary-text">{copy.holdingsDescription}</p>
                </div>
                {chartData.length ? (
                  <div className="h-[360px] w-full" role="img" aria-label={`${copy.holdingsTitle}: ${chartData.map((item) => `${item.name} ${formatPercent(item.weight)}`).join(', ')}`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} layout="vertical" margin={{ top: 8, right: 18, bottom: 8, left: 16 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.2} />
                        <XAxis type="number" tickFormatter={(value: number) => `${value}%`} tick={{ fontSize: 12 }} />
                        <YAxis
                          type="category"
                          dataKey="name"
                          width={108}
                          tick={{ fontSize: 12 }}
                          tickFormatter={(value: string) => value.length > 16 ? `${value.slice(0, 15)}…` : value}
                        />
                        <Tooltip formatter={(value) => formatPercent(Number(value))} />
                        <Bar dataKey="weight" name={copy.weight} radius={[0, 7, 7, 0]} maxBarSize={26}>
                          {chartData.map((item, index) => (
                            <Cell key={item.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="py-16 text-center text-sm text-secondary-text">{copy.noCurrentHoldings}</p>
                )}
              </Card>

              <Card padding="lg" className="h-fit">
                <h2 className="text-lg font-semibold text-foreground">{copy.source}</h2>
                <dl className="mt-4 space-y-3 text-sm">
                  <div>
                    <dt className="text-secondary-text">{analysis.managerName}</dt>
                    <dd className="mt-1 font-mono text-foreground">CIK {analysis.managerCik}</dd>
                  </div>
                  <div>
                    <dt className="text-secondary-text">{copy.filed}</dt>
                    <dd className="mt-1 text-foreground">{formatDate(analysis.current.filedDate, language)}</dd>
                  </div>
                  <div>
                    <dt className="text-secondary-text">Accession</dt>
                    <dd className="mt-1 break-all font-mono text-xs text-foreground">{analysis.current.accessionNumber}</dd>
                  </div>
                </dl>
                <div className="mt-5 flex flex-col gap-2">
                  <SourceLink href={analysis.current.primaryDocumentUrl} label={copy.secLinkLabel}>{copy.primaryFiling}</SourceLink>
                  <SourceLink href={analysis.current.informationTableUrl} label={copy.secLinkLabel}>{copy.infoTable}</SourceLink>
                </div>
              </Card>
            </section>

            <section className="space-y-3">
              <div>
                <h2 className="text-lg font-semibold text-foreground">{copy.changesTitle}</h2>
                <p className="mt-1 text-sm text-secondary-text">{copy.changesDescription}</p>
              </div>
              <div className="overflow-hidden rounded-2xl border border-border/70 bg-card/75 shadow-soft-card">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-border/70 text-sm">
                    <thead className="bg-surface-2/70 text-left text-xs uppercase tracking-[0.12em] text-secondary-text">
                      <tr>
                        <th className="px-4 py-3 font-medium">{copy.issuer}</th>
                        <th className="px-4 py-3 font-medium">{copy.status}</th>
                        <th className="px-4 py-3 text-right font-medium">{copy.shares}</th>
                        <th className="px-4 py-3 text-right font-medium">{copy.delta}</th>
                        <th className="px-4 py-3 text-right font-medium">{copy.weight}</th>
                        <th className="px-4 py-3 text-right font-medium">{copy.value}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {analysis.holdings.map((holding: InstitutionalHoldingDelta) => {
                        const delta = toNumber(holding.shareDelta);
                        return (
                          <tr key={`${holding.cusip}-${holding.putCall}`} className="transition-colors hover:bg-hover/60">
                            <td className="min-w-60 px-4 py-3">
                              <p className="font-medium text-foreground">{holding.issuerName}</p>
                              <p className="mt-0.5 text-xs text-secondary-text">{holding.titleOfClass} · {holding.cusip}</p>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3"><StatusBadge status={holding.status} language={language} /></td>
                            <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-foreground">{formatNumber(holding.currentShares, language)}</td>
                            <td className={cn(
                              'whitespace-nowrap px-4 py-3 text-right tabular-nums',
                              delta !== null && delta > 0 ? 'text-success' : delta !== null && delta < 0 ? 'text-danger' : 'text-secondary-text',
                            )}>
                              {delta !== null && delta > 0 ? '+' : ''}{formatNumber(delta, language)}
                              {holding.shareDeltaPct !== null ? <span className="ml-1 text-xs">({formatPercent(holding.shareDeltaPct)})</span> : null}
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-foreground">{formatPercent(holding.currentWeightPct)}</td>
                            <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-foreground">{formatCurrency(holding.currentValueUsd, language)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-warning/25 bg-warning/10 px-5 py-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                <div>
                  <h2 className="font-semibold text-foreground">{copy.disclosureTitle}</h2>
                  <p className="mt-1 text-sm leading-6 text-secondary-text">{copy.disclosureLead}</p>
                  <p className="mt-2 text-sm leading-6 text-secondary-text">{analysis.disclosureNote}</p>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </AppPage>
  );
};

export default InstitutionalHoldingsPage;
