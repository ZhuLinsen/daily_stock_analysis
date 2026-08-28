import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge, RefreshCw, ThermometerSun } from 'lucide-react';
import { marketTemperatureApi } from '../api/marketTemperature';
import type {
  MarketDashboardCandidate,
  MarketDashboardData,
  MarketDashboardFlowItem,
  MarketDashboardSectorItem,
  MarketTemperatureComputeResponse,
  MarketTemperatureDimension,
  MarketTemperatureSnapshotItem,
} from '../types/marketTemperature';
import type { ParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Select,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { MARKET_OPTIONS, toParsedError } from '../utils/masterKit';
import { cn } from '../utils/cn';

type TempView = {
  score: number;
  label: string;
  labelKey: string;
  guidance?: string | null;
  dimensions: MarketTemperatureDimension[];
  reasons: string[];
  source?: string | null;
};

function labelKeyFromLabel(label: string): string {
  if (label === '极度贪婪') return 'extreme_greed';
  if (label === '贪婪') return 'greed';
  if (label === '恐惧') return 'fear';
  if (label === '极度恐惧') return 'extreme_fear';
  return 'neutral';
}

function toView(item: MarketTemperatureComputeResponse | MarketTemperatureSnapshotItem): TempView {
  return {
    score: item.score,
    label: item.label,
    labelKey: 'labelKey' in item && item.labelKey ? item.labelKey : labelKeyFromLabel(item.label),
    guidance: item.guidance,
    dimensions: item.dimensions,
    reasons: item.reasons,
    source: (item as MarketTemperatureComputeResponse).source ?? undefined,
  };
}

function toneForLabel(labelKey: string): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  if (labelKey === 'extreme_greed') return 'danger';
  if (labelKey === 'greed') return 'warning';
  if (labelKey === 'fear') return 'info';
  if (labelKey === 'extreme_fear') return 'success';
  return 'default';
}

function priceStyle(value?: number | null): React.CSSProperties | undefined {
  if (value == null) return undefined;
  if (value > 0) return { color: 'var(--home-price-up)' };
  if (value < 0) return { color: 'var(--home-price-down)' };
  return undefined;
}

function pctText(value?: number | null): string {
  if (value == null) return '--';
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%';
}

function flowText(value?: number | null): string {
  if (value == null) return '--';
  return (value > 0 ? '+' : '') + value.toFixed(2);
}

function SectorRankRows({ items }: { items: MarketDashboardSectorItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-secondary-text">--</p>;
  }
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item.name} className="flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-foreground">{item.name}</span>
          <span className="shrink-0 font-medium" style={priceStyle(item.changePct)}>
            {pctText(item.changePct)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function FlowRankRows({ items }: { items: MarketDashboardFlowItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-secondary-text">--</p>;
  }
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item.name} className="flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-foreground">{item.name}</span>
          <span className="shrink-0 font-medium" style={priceStyle(item.netInflow)}>
            {flowText(item.netInflow)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function CandidateRows({ items }: { items: MarketDashboardCandidate[] }) {
  if (items.length === 0) return null;
  return (
    <div className="divide-y divide-border/60">
      {items.map((item) => (
        <div key={item.code} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5">
          <div className="min-w-0">
            <span className="font-medium text-foreground">{item.name}</span>
            <span className="ml-2 text-xs text-secondary-text">{item.code}</span>
            <span className="ml-2 text-xs text-secondary-text">{item.sector}</span>
            <p className="mt-0.5 text-xs text-secondary-text">{item.reason}</p>
          </div>
          <div className="flex shrink-0 items-center gap-4 text-sm">
            <span style={priceStyle(item.changePct)}>{pctText(item.changePct)}</span>
            <span className="text-secondary-text">{item.price != null ? item.price.toFixed(2) : '--'}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

const MarketTemperaturePage: React.FC = () => {
  const { t } = useUiLanguage();
  const [market, setMarket] = useState('cn');
  const [latest, setLatest] = useState<TempView | null>(null);
  const [dashboard, setDashboard] = useState<MarketDashboardData | null>(null);
  const [history, setHistory] = useState<MarketTemperatureSnapshotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [computingLive, setComputingLive] = useState(false);
  const [computingLocal, setComputingLocal] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const requestSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    setLoading(true);
    setError(null);
    try {
      const [latestData, historyData] = await Promise.all([
        marketTemperatureApi.latest(market),
        marketTemperatureApi.history(market, 1, 20),
      ]);
      if (seq !== requestSeqRef.current) return;
      setLatest(latestData ? toView(latestData) : null);
      setHistory(historyData.items);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      setLatest(null);
      setError(toParsedError(err, t('temperature.title'), t('temperature.title')));
    } finally {
      if (seq === requestSeqRef.current) setLoading(false);
    }
  }, [market, t]);

  useEffect(() => {
    void load();
    return () => {
      requestSeqRef.current += 1;
    };
  }, [load]);

  const refreshHistoryQuietly = async () => {
    try {
      const historyData = await marketTemperatureApi.history(market, 1, 20);
      setHistory(historyData.items);
    } catch {
      // 主数据已更新，历史刷新失败不打断主流程
    }
  };

  const handleComputeLive = async () => {
    setComputingLive(true);
    setError(null);
    try {
      const data = await marketTemperatureApi.dashboard(market);
      setDashboard(data);
      if (data.temperature) setLatest(toView(data.temperature));
      await refreshHistoryQuietly();
    } catch (err) {
      setError(toParsedError(err, t('temperature.title'), t('temperature.title')));
    } finally {
      setComputingLive(false);
    }
  };

  const handleComputeFromDb = async () => {
    setComputingLocal(true);
    setError(null);
    try {
      const data = await marketTemperatureApi.fromDatabase(market);
      setLatest(toView(data));
      await refreshHistoryQuietly();
    } catch (err) {
      setError(toParsedError(err, t('temperature.title'), t('temperature.title')));
    } finally {
      setComputingLocal(false);
    }
  };

  const breadth = dashboard?.breadth;

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow="Master Toolkit"
          title={t('temperature.title')}
          description={t('temperature.description')}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Select value={market} onChange={setMarket} options={MARKET_OPTIONS} className="w-32" />
              <Button
                variant="secondary"
                onClick={() => void load()}
                disabled={loading || computingLive || computingLocal}
              >
                <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
                {t('temperature.refresh')}
              </Button>
              <Button
                variant="primary"
                onClick={() => void handleComputeLive()}
                isLoading={computingLive}
                disabled={market !== 'cn'}
              >
                <Gauge className="h-4 w-4" />
                {t('temperature.computeLive')}
              </Button>
              <Button
                variant="secondary"
                onClick={() => void handleComputeFromDb()}
                isLoading={computingLocal}
                disabled={computingLive}
              >
                <ThermometerSun className="h-4 w-4" />
                {t('temperature.computeFromDb')}
              </Button>
              {market !== 'cn' ? (
                <span className="text-xs text-secondary-text">{t('temperature.computeLiveDisabled')}</span>
              ) : null}
            </div>
          }
        />

        {error ? (
          <ApiErrorAlert error={error} actionLabel={t('common.retry')} onAction={() => void load()} />
        ) : null}

        {loading && !latest ? (
          <div className="h-40 animate-pulse rounded-2xl border border-border/60 bg-card/60" />
        ) : latest ? (
          <Card padding="lg" variant="gradient">
            <p className="label-uppercase">{t('temperature.score')}</p>
            <div className="mt-2 flex items-end gap-3">
              <span className="text-6xl font-semibold leading-none text-foreground">{latest.score}</span>
              <Badge variant={toneForLabel(latest.labelKey)} size="md">
                {t(('temperature.label.' + latest.labelKey) as 'temperature.label.neutral')}
              </Badge>
              {latest.source ? (
                <Badge variant="default" size="sm">
                  {latest.source === 'market_stats'
                    ? t('temperature.sourceMarketStats')
                    : t('temperature.sourceTrackedUniverse')}
                </Badge>
              ) : null}
            </div>
            <p className="mt-3 max-w-2xl text-sm text-secondary-text">{latest.guidance}</p>
          </Card>
        ) : (
          <EmptyState
            title={t('temperature.empty')}
            description={t('temperature.emptyHint')}
            icon={<ThermometerSun className="h-6 w-6" />}
            action={
              market === 'cn' ? (
                <Button variant="primary" onClick={() => void handleComputeLive()} isLoading={computingLive}>
                  <Gauge className="h-4 w-4" />
                  {t('temperature.computeLive')}
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => void handleComputeFromDb()} isLoading={computingLocal}>
                  <ThermometerSun className="h-4 w-4" />
                  {t('temperature.computeFromDb')}
                </Button>
              )
            }
          />
        )}

        {computingLive && !dashboard ? (
          <div className="h-56 animate-pulse rounded-2xl border border-border/60 bg-card/60" />
        ) : null}

        {dashboard ? (
          <>
            {dashboard.indices.length > 0 ? (
              <Card padding="md" variant="bordered">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.indices')}</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  {dashboard.indices.map((index) => (
                    <span
                      key={index.code || index.name}
                      className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-3 py-1 text-sm"
                    >
                      <span className="text-secondary-text">{index.name}</span>
                      <span className="font-medium" style={priceStyle(index.changePct)}>
                        {pctText(index.changePct)}
                      </span>
                    </span>
                  ))}
                </div>
              </Card>
            ) : null}

            {breadth ? (
              <Card padding="md" variant="bordered">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.breadth')}</h2>
                <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.up')}</p>
                    <p className="mt-1 text-lg font-semibold" style={priceStyle(1)}>{breadth.upCount}</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.down')}</p>
                    <p className="mt-1 text-lg font-semibold" style={priceStyle(-1)}>{breadth.downCount}</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.flat')}</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">{breadth.flatCount}</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.limitUp')}</p>
                    <p className="mt-1 text-lg font-semibold" style={priceStyle(1)}>{breadth.limitUpCount}</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.limitDown')}</p>
                    <p className="mt-1 text-lg font-semibold" style={priceStyle(-1)}>{breadth.limitDownCount}</p>
                  </div>
                  <div className="rounded-xl border border-border/60 bg-card/60 p-3">
                    <p className="text-xs text-secondary-text">{t('temperature.db.amount')}</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">
                      {breadth.totalAmount != null ? breadth.totalAmount.toLocaleString() : '--'}
                    </p>
                  </div>
                </div>
              </Card>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <Card padding="md" variant="bordered">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.hotSectors')}</h2>
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="label-uppercase">{t('temperature.db.topGain')}</p>
                    <div className="mt-2"><SectorRankRows items={dashboard.hotSectors.top} /></div>
                  </div>
                  <div>
                    <p className="label-uppercase">{t('temperature.db.topLoss')}</p>
                    <div className="mt-2"><SectorRankRows items={dashboard.hotSectors.bottom} /></div>
                  </div>
                </div>
              </Card>
              <Card padding="md" variant="bordered">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.hotConcepts')}</h2>
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="label-uppercase">{t('temperature.db.topGain')}</p>
                    <div className="mt-2"><SectorRankRows items={dashboard.hotConcepts.top} /></div>
                  </div>
                  <div>
                    <p className="label-uppercase">{t('temperature.db.topLoss')}</p>
                    <div className="mt-2"><SectorRankRows items={dashboard.hotConcepts.bottom} /></div>
                  </div>
                </div>
              </Card>
            </div>

            <Card padding="md" variant="bordered">
              <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.capitalFlow')}</h2>
              {dashboard.capitalFlow.status !== 'ok' ? (
                <p className="mt-3 text-sm text-secondary-text">{t('temperature.db.flowUnavailable')}</p>
              ) : (
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="label-uppercase">{t('temperature.db.inflow')}</p>
                    <div className="mt-2"><FlowRankRows items={dashboard.capitalFlow.sectorRankings.top} /></div>
                  </div>
                  <div>
                    <p className="label-uppercase">{t('temperature.db.outflow')}</p>
                    <div className="mt-2"><FlowRankRows items={dashboard.capitalFlow.sectorRankings.bottom} /></div>
                  </div>
                </div>
              )}
            </Card>

            <Card padding="md" variant="bordered">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.candidates')}</h2>
                {dashboard.generatedAt ? (
                  <span className="text-xs text-secondary-text">
                    {t('temperature.db.generatedAt')} {dashboard.generatedAt}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-secondary-text">{t('temperature.db.candidateHint')}</p>
              <div className="mt-3">
                {dashboard.candidates.length === 0 ? (
                  <p className="text-sm text-secondary-text">{t('temperature.db.noCandidates')}</p>
                ) : (
                  <CandidateRows items={dashboard.candidates} />
                )}
              </div>
            </Card>

            {dashboard.notes.length > 0 ? (
              <Card padding="md" variant="bordered">
                <h2 className="text-lg font-semibold text-foreground">{t('temperature.db.notes')}</h2>
                <ul className="mt-2 space-y-1 text-sm text-secondary-text">
                  {dashboard.notes.map((note, i) => (
                    <li key={i}>· {note}</li>
                  ))}
                </ul>
              </Card>
            ) : null}
          </>
        ) : null}

        {latest && latest.dimensions.length > 0 ? (
          <Card padding="md" variant="bordered">
            <h2 className="text-lg font-semibold text-foreground">{t('temperature.dimensions')}</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {latest.dimensions.map((dim) => (
                <div key={dim.key} className="rounded-xl border border-border/60 bg-card/60 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-secondary-text">{t(('temperature.dim.' + dim.key) as 'temperature.dim.breadth')}</span>
                    <span className="text-sm font-semibold text-foreground">{dim.score}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated">
                    <div className="h-full rounded-full bg-cyan" style={{ width: dim.score + '%' }} />
                  </div>
                </div>
              ))}
            </div>
            {latest.reasons.length > 0 ? (
              <div className="mt-4">
                <p className="label-uppercase">{t('temperature.reasons')}</p>
                <ul className="mt-2 space-y-1 text-sm text-secondary-text">
                  {latest.reasons.map((reason, i) => (
                    <li key={i}>· {reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>
        ) : null}

        <Card padding="md" variant="bordered">
          <h2 className="text-lg font-semibold text-foreground">{t('temperature.history')}</h2>
          {history.length === 0 ? (
            <div className="mt-4">
              <EmptyState title={t('temperature.empty')} />
            </div>
          ) : (
            <div className="mt-4 divide-y divide-border/60">
              {history.map((item) => {
                const labelKey = labelKeyFromLabel(item.label);
                return (
                  <div key={item.id} className="flex items-center justify-between py-3">
                    <span className="text-sm text-secondary-text">{item.tradeDate}</span>
                    <div className="flex items-center gap-2">
                      <Badge variant={toneForLabel(labelKey)}>{t(('temperature.label.' + labelKey) as 'temperature.label.neutral')}</Badge>
                      <span className="text-sm font-semibold text-foreground">{item.score}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </AppPage>
  );
};

export default MarketTemperaturePage;
