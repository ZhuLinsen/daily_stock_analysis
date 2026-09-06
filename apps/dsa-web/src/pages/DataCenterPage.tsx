import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Database, RefreshCw, Settings2, TriangleAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { dataCapabilityApi } from '../api/dataCapability';
import { AppPage, Badge, Button, Card, EmptyState, InlineAlert, Loading, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { DataCapabilityOverview, DatasetQualityStatus, ProviderCapabilityStatus } from '../types/dataCapability';
import { formatDateTime } from '../utils/format';

type Status = DatasetQualityStatus | ProviderCapabilityStatus;

function statusVariant(status: Status): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'ok') return 'success';
  if (status === 'partial' || status === 'degraded' || status === 'stale' || status === 'unknown') return 'warning';
  if (status === 'unavailable') return 'danger';
  return 'default';
}

function formatDatasetMarkets(datasetMarkets: Record<string, string[]>): string {
  return Object.entries(datasetMarkets)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([dataset, markets]) => `${dataset} [${markets.join(', ') || '--'}]`)
    .join(' · ');
}

function formatDatasetSources(dataset: DataCapabilityOverview['datasets'][number]): string {
  const markets = dataset.coverage?.markets;
  if (markets && typeof markets === 'object' && !Array.isArray(markets)) {
    const sources = Object.entries(markets)
      .sort(([left], [right]) => left.localeCompare(right))
      .flatMap(([market, value]) => {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
        const source = (value as Record<string, unknown>).source;
        return typeof source === 'string' && source.trim() ? [`${market}: ${source.trim()}`] : [];
      });
    if (sources.length) return sources.join(' / ');
  }
  return dataset.source || '--';
}

function SummaryTile({ label, value, note }: { label: string; value: number; note: string }) {
  return (
    <div className="rounded-xl border border-border/75 bg-card/85 px-4 py-3">
      <div className="text-xs text-secondary-text">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
      <div className="mt-1 text-xs text-muted-text">{note}</div>
    </div>
  );
}

const DataCenterPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [overview, setOverview] = useState<DataCapabilityOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestGeneration = useRef(0);

  useEffect(() => {
    document.title = `${t('dataCenter.title')} - DSA`;
  }, [t]);

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setError('');
    try {
      const nextOverview = await dataCapabilityApi.getOverview();
      if (generation !== requestGeneration.current) return;
      setOverview(nextOverview);
    } catch {
      if (generation !== requestGeneration.current) return;
      setOverview(null);
      setError(t('dataCenter.loadError'));
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    return () => {
      requestGeneration.current += 1;
    };
  }, [load]);

  const summary = useMemo(() => {
    const providers = overview?.providers ?? [];
    const datasets = overview?.datasets ?? [];
    return {
      configured: providers.filter((item) => item.configured).length,
      healthy: datasets.filter((item) => item.status === 'ok').length,
      attention: datasets.filter((item) => item.status !== 'ok').length,
    };
  }, [overview]);

  return (
    <AppPage className="space-y-5">
      <PageHeader eyebrow="Data Center" title={t('dataCenter.title')} description={t('dataCenter.description')} />

      <div className="flex justify-end gap-2">
        <Link
          to="/settings"
          className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-transparent px-3 text-sm font-medium text-secondary-text transition-all hover:bg-hover hover:text-foreground"
        >
          <Settings2 className="h-4 w-4" />{t('dataCenter.openSettings')}
        </Link>
        <Button size="sm" variant="secondary" isLoading={loading} loadingText={t('dataCenter.refreshing')} onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" />{t('dataCenter.refresh')}
        </Button>
      </div>

      {error ? (
        <InlineAlert
          variant="danger"
          title={t('dataCenter.loadErrorTitle')}
          message={error}
          action={<Button size="sm" variant="secondary" onClick={() => void load()}>{t('common.retry')}</Button>}
        />
      ) : null}

      {loading && !overview ? <Loading label={t('dataCenter.loading')} /> : null}

      {!loading && !error && overview && overview.providers.length === 0 && overview.datasets.length === 0 ? (
        <EmptyState icon={<Database className="h-6 w-6" />} title={t('dataCenter.emptyTitle')} description={t('dataCenter.emptyDescription')} />
      ) : null}

      {overview ? (
        <>
          {overview.warnings.length > 0 ? (
            <InlineAlert variant="warning" title={t('dataCenter.partialTitle')} message={overview.warnings.join(' · ')} />
          ) : null}

          <div className="grid gap-3 md:grid-cols-3">
            <SummaryTile label={t('dataCenter.configuredProviders')} value={summary.configured} note={`${overview.providers.length} ${t('dataCenter.totalProviders')}`} />
            <SummaryTile label={t('dataCenter.healthyDatasets')} value={summary.healthy} note={`${overview.datasets.length} ${t('dataCenter.totalDatasets')}`} />
            <SummaryTile label={t('dataCenter.attentionDatasets')} value={summary.attention} note={t('dataCenter.attentionNote')} />
          </div>

          <Card title={t('dataCenter.providers')} subtitle={formatDateTime(overview.asOf)} variant="bordered" padding="md">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {overview.providers.map((provider) => (
                <div key={provider.name} className="rounded-xl border border-border/70 bg-surface/60 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-foreground">{provider.label || provider.name}</div>
                      <div className="mt-1 font-mono text-xs text-muted-text">{provider.name}</div>
                    </div>
                    <Badge variant={statusVariant(provider.status)}>{provider.status}</Badge>
                  </div>
                  <div className="mt-3 text-xs leading-5 text-secondary-text">
                    <div>{t('dataCenter.markets')}: {provider.markets.join(', ') || '--'}</div>
                    <div>{t('dataCenter.datasets')}: {formatDatasetMarkets(provider.datasetMarkets) || '--'}</div>
                  </div>
                  {provider.warnings.length > 0 ? <div className="mt-2 text-xs text-warning">{provider.warnings.join(' · ')}</div> : null}
                </div>
              ))}
            </div>
          </Card>

          <Card title={t('dataCenter.datasetQuality')} subtitle="Quality" variant="bordered" padding="md">
            {overview.datasets.length === 0 ? (
              <EmptyState title={t('dataCenter.noDatasetQuality')} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t('dataCenter.dataset')}</th>
                      <th className="px-3 py-2 font-medium">{t('dataCenter.status')}</th>
                      <th className="px-3 py-2 font-medium">{t('dataCenter.source')}</th>
                      <th className="px-3 py-2 font-medium">{t('dataCenter.lastSuccess')}</th>
                      <th className="px-3 py-2 font-medium">{t('dataCenter.notes')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {overview.datasets.map((dataset) => (
                      <tr key={dataset.dataset}>
                        <td className="px-3 py-3 font-mono text-foreground">{dataset.dataset}</td>
                        <td className="px-3 py-3"><Badge variant={statusVariant(dataset.status)}>{dataset.status}</Badge></td>
                        <td className="px-3 py-3 text-secondary-text">{formatDatasetSources(dataset)}</td>
                        <td className="px-3 py-3 text-secondary-text">{dataset.lastSuccess ? formatDateTime(dataset.lastSuccess) : '--'}</td>
                        <td className="px-3 py-3 text-secondary-text">{[dataset.lastError, ...dataset.warnings].filter(Boolean).join(' · ') || '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title={t('dataCenter.priorities')} subtitle="Routing" variant="bordered" padding="md">
            {overview.priorities.length === 0 ? (
              <EmptyState icon={<TriangleAlert className="h-6 w-6" />} title={t('dataCenter.noPriorities')} />
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {overview.priorities.map((priority) => (
                  <div key={priority.scenario} className="rounded-xl border border-border/70 bg-surface/60 p-3">
                    <div className="font-mono text-sm font-semibold text-foreground">{priority.scenario}</div>
                    <div className="mt-2 text-sm text-secondary-text">{priority.providers.join(' → ') || '--'}</div>
                    <div className="mt-1 text-xs text-muted-text">{priority.source}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      ) : null}
    </AppPage>
  );
};

export default DataCenterPage;
