import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { CheckCircle2, CircleAlert, CircleDashed, FlaskConical, RefreshCw } from 'lucide-react';
import { systemConfigApi } from '../../api/systemConfig';
import { getParsedApiError, type ParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { GenerationBackendStatus, GenerationBackendStatusResponse, SystemConfigUpdateItem, TestGenerationBackendResponse } from '../../types/systemConfig';
import { ApiErrorAlert, Badge, Button } from '../common';
import { SettingsAlert } from './SettingsAlert';

type Translate = ReturnType<typeof useUiLanguage>['t'];

interface GenerationBackendStatusPanelProps {
  items: SystemConfigUpdateItem[];
  maskToken: string;
  disabled?: boolean;
}

function getHealthLabel(status: GenerationBackendStatus, t: Translate) {
  if (status.healthStatus === 'passed') return t('settings.generationBackendHealthPassed');
  if (status.healthStatus === 'failed') return t('settings.generationBackendHealthFailed');
  if (status.healthStatus === 'skipped') return t('settings.generationBackendHealthSkipped');
  return status.available ? t('settings.generationBackendRunnable') : t('settings.generationBackendNeedsAction');
}

function getHealthIcon(status: GenerationBackendStatus) {
  if (status.healthStatus === 'passed') {
    return <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />;
  }
  if (!status.available || status.healthStatus === 'failed') {
    return <CircleAlert className="h-4 w-4 text-warning" aria-hidden="true" />;
  }
  return <CircleDashed className="h-4 w-4 text-muted-text" aria-hidden="true" />;
}

const BackendStatusRow: React.FC<{ title: string; status: GenerationBackendStatus | null | undefined; t: Translate }> = ({
  title,
  status,
  t,
}) => {
  if (!status) {
    return null;
  }

  return (
    <div className="rounded-xl border settings-border bg-background/35 px-4 py-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {getHealthIcon(status)}
            <span className="text-sm font-semibold text-foreground">{title}</span>
            <Badge variant={status.available ? 'success' : 'warning'} size="sm">
              {getHealthLabel(status, t)}
            </Badge>
            <Badge variant="history" size="sm">
              {status.backendId}
            </Badge>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-text">
            {status.backendType === 'local_cli'
              ? t('settings.generationBackendLocalCliDescription')
              : t('settings.generationBackendLiteLLMDescription')}
          </p>
          {status.lastErrorMessage ? (
            <p className="mt-2 text-xs leading-5 text-warning">
              {status.lastErrorCode ? `${status.lastErrorCode}: ` : ''}
              {status.lastErrorMessage}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Badge variant={status.supportsJson ? 'success' : 'history'} size="sm">JSON</Badge>
          <Badge variant={status.supportsStream ? 'success' : 'history'} size="sm">Stream</Badge>
          <Badge variant={status.supportsTools ? 'success' : 'warning'} size="sm">
            {status.supportsTools ? t('settings.generationBackendToolsSupported') : t('settings.generationBackendGenerationOnly')}
          </Badge>
          <Badge variant="history" size="sm">{t('settings.generationBackendConcurrency', { count: status.maxConcurrency })}</Badge>
        </div>
      </div>
    </div>
  );
};

export const GenerationBackendStatusPanel: React.FC<GenerationBackendStatusPanelProps> = ({
  items,
  maskToken,
  disabled = false,
}) => {
  const { t } = useUiLanguage();
  const [status, setStatus] = useState<GenerationBackendStatusResponse | null>(null);
  const [smokeResult, setSmokeResult] = useState<TestGenerationBackendResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSmoking, setIsSmoking] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const refreshRequestIdRef = useRef(0);
  const smokeRequestIdRef = useRef(0);
  const hasDraft = items.length > 0;
  const requestItems = useMemo(() => items.map((item) => ({ key: item.key, value: item.value })), [items]);
  const requestItemsFingerprint = useMemo(() => JSON.stringify(requestItems), [requestItems]);

  useEffect(() => {
    smokeRequestIdRef.current += 1;
    setSmokeResult(null);
    setIsSmoking(false);
  }, [requestItemsFingerprint]);

  const refresh = useCallback(async () => {
    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;
    smokeRequestIdRef.current += 1;
    setIsLoading(true);
    setIsSmoking(false);
    setError(null);
    setSmokeResult(null);
    try {
      const next = hasDraft
        ? await systemConfigApi.previewGenerationBackendStatus({ items: requestItems, maskToken })
        : await systemConfigApi.getGenerationBackendStatus();
      if (refreshRequestIdRef.current !== requestId) {
        return;
      }
      setStatus(next);
    } catch (err: unknown) {
      if (refreshRequestIdRef.current !== requestId) {
        return;
      }
      setStatus(null);
      setSmokeResult(null);
      setError(getParsedApiError(err));
    } finally {
      if (refreshRequestIdRef.current === requestId) {
        setIsLoading(false);
      }
    }
  }, [hasDraft, maskToken, requestItems]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runSmoke = useCallback(async () => {
    const requestId = smokeRequestIdRef.current + 1;
    smokeRequestIdRef.current = requestId;
    refreshRequestIdRef.current += 1;
    setIsLoading(false);
    setIsSmoking(true);
    setError(null);
    setSmokeResult(null);
    try {
      const result = await systemConfigApi.testGenerationBackend({
        mode: 'json',
        items: requestItems,
        maskToken,
      });
      if (smokeRequestIdRef.current !== requestId) {
        return;
      }
      setSmokeResult(result);
      setStatus((prev) => ({
        primaryBackendId: result.status.backendId,
        fallbackBackendId: prev?.fallbackBackendId ?? null,
        primary: result.status,
        fallback: prev?.fallback ?? null,
        backends: prev?.backends?.length
          ? [result.status, ...prev.backends.filter((backend) => backend.backendId !== result.status.backendId)]
          : [result.status],
      }));
    } catch (err: unknown) {
      if (smokeRequestIdRef.current !== requestId) {
        return;
      }
      setStatus(null);
      setSmokeResult(null);
      setError(getParsedApiError(err));
    } finally {
      if (smokeRequestIdRef.current === requestId) {
        setIsSmoking(false);
      }
    }
  }, [maskToken, requestItems]);

  return (
    <div data-testid="generation-backend-status-panel" className="space-y-3 rounded-xl border settings-border bg-card/70 p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">{t('settings.generationBackendStatus')}</p>
          <p className="mt-1 text-xs leading-5 text-muted-text">
            {t('settings.generationBackendStatusDescription')}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button type="button" variant="settings-secondary" size="sm" disabled={disabled || isLoading} isLoading={isLoading} loadingText={t('settings.generationBackendRefreshing')} onClick={() => void refresh()}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t('settings.generationBackendRefresh')}
          </Button>
          <Button type="button" variant="settings-secondary" size="sm" disabled={disabled || isSmoking} isLoading={isSmoking} loadingText={t('settings.generationBackendSmokeTesting')} onClick={() => void runSmoke()}>
            <FlaskConical className="h-4 w-4" aria-hidden="true" />
            {t('settings.generationBackendSmokeTest')}
          </Button>
        </div>
      </div>
      {error ? <ApiErrorAlert error={error} /> : null}
      {smokeResult ? (
        <SettingsAlert
          title={smokeResult.success ? t('settings.generationBackendSmokePassed') : t('settings.generationBackendSmokeFailed')}
          message={smokeResult.success ? t('settings.generationBackendSmokePassedMessage') : smokeResult.message}
          variant={smokeResult.success ? 'success' : 'warning'}
        />
      ) : null}
      <BackendStatusRow title={t('settings.generationBackendPrimary')} status={status?.primary} t={t} />
      <BackendStatusRow title={t('settings.generationBackendFallback')} status={status?.fallback} t={t} />
    </div>
  );
};
