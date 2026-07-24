import { useCallback, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { CheckCircle2, CircleAlert, CircleDashed, RefreshCw } from 'lucide-react';
import { systemConfigApi } from '../../api/systemConfig';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { DataSourceStatus, DataSourceStatusResponse } from '../../types/systemConfig';
import { ApiErrorAlert, Badge, Button } from '../common';

type Translate = ReturnType<typeof useUiLanguage>['t'];

interface DataSourceStatusPanelProps {
  disabled?: boolean;
}

function getStatusIcon(source: DataSourceStatus) {
  if (source.circuit.length > 0) {
    return <CircleAlert className="h-4 w-4 text-warning" aria-hidden="true" />;
  }
  if (source.status === 'active') {
    return <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />;
  }
  return <CircleDashed className="h-4 w-4 text-muted-text" aria-hidden="true" />;
}

function getDetailText(source: DataSourceStatus, t: Translate): string | null {
  if (source.detail === 'public_instance_auto_discovery') {
    return t('settings.dataSourceDetailPublicInstances');
  }
  return source.detail ?? null;
}

const DataSourceRow: React.FC<{ source: DataSourceStatus; t: Translate }> = ({ source, t }) => {
  const detailText = getDetailText(source, t);
  return (
    <div className="rounded-xl border settings-border bg-background/35 px-4 py-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {getStatusIcon(source)}
            <span className="text-sm font-semibold text-foreground">{source.name}</span>
            <Badge variant={source.status === 'active' ? 'success' : 'warning'} size="sm">
              {source.status === 'active' ? t('settings.dataSourceActive') : t('settings.dataSourceNotConfigured')}
            </Badge>
            {source.circuit.map((entry) => (
              <Badge key={`${entry.market}:${entry.state}`} variant="warning" size="sm">
                {entry.state === 'half_open'
                  ? t('settings.dataSourceCircuitHalfOpen', { market: entry.market.toUpperCase() })
                  : t('settings.dataSourceCircuitOpen', { market: entry.market.toUpperCase() })}
              </Badge>
            ))}
          </div>
          {source.status !== 'active' && source.configKeys.length > 0 ? (
            <p className="mt-2 text-xs leading-5 text-muted-text">
              {t('settings.dataSourceMissingKeys', { keys: source.configKeys.join(' / ') })}
            </p>
          ) : null}
          {detailText ? <p className="mt-2 text-xs leading-5 text-muted-text">{detailText}</p> : null}
        </div>
        {source.markets.length > 0 ? (
          <div className="flex shrink-0 flex-wrap gap-2">
            {source.markets.map((market) => (
              <Badge key={market} variant="history" size="sm">
                {market.toUpperCase()}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
};

export const DataSourceStatusPanel: React.FC<DataSourceStatusPanelProps> = ({ disabled = false }) => {
  const { t } = useUiLanguage();
  const [status, setStatus] = useState<DataSourceStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const refreshRequestIdRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    setIsLoading(true);
    setError(null);
    try {
      const next = await systemConfigApi.getDataSourceStatus();
      if (refreshRequestIdRef.current !== requestId) {
        return;
      }
      setStatus(next);
    } catch (err: unknown) {
      if (refreshRequestIdRef.current !== requestId) {
        return;
      }
      setStatus(null);
      setError(getParsedApiError(err));
    } finally {
      if (refreshRequestIdRef.current === requestId) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div data-testid="data-source-status-panel" className="space-y-3 rounded-xl border settings-border bg-card/70 p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">{t('settings.dataSourceStatus')}</p>
          <p className="mt-1 text-xs leading-5 text-muted-text">{t('settings.dataSourceStatusDescription')}</p>
          {status ? (
            <p className="mt-1 text-xs leading-5 text-muted-text">
              {t('settings.dataSourceSummary', {
                marketActive: status.summary.marketDataActive,
                marketTotal: status.summary.marketDataTotal,
                searchActive: status.summary.searchActive,
                searchTotal: status.summary.searchTotal,
              })}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="settings-secondary"
            size="sm"
            disabled={disabled || isLoading}
            isLoading={isLoading}
            loadingText={t('settings.dataSourceRefreshing')}
            onClick={() => void refresh()}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t('settings.dataSourceRefresh')}
          </Button>
        </div>
      </div>
      {error ? <ApiErrorAlert error={error} /> : null}
      {status ? (
        <>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-text">
            {t('settings.dataSourceMarketData')}
          </p>
          <div className="space-y-2">
            {status.marketData.map((source) => (
              <DataSourceRow key={source.sourceId} source={source} t={t} />
            ))}
          </div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-text">
            {t('settings.dataSourceSearch')}
          </p>
          <div className="space-y-2">
            {status.search.map((source) => (
              <DataSourceRow key={source.sourceId} source={source} t={t} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
};
