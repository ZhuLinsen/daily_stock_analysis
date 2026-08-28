import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, Scale, SlidersHorizontal, Sparkles } from 'lucide-react';
import { masterDebateApi } from '../api/masterDebate';
import type { MasterDebateRecordItem, MasterDebateResponse } from '../types/masterDebate';
import type { ParsedApiError } from '../api/error';
import { StockAutocomplete } from '../components/StockAutocomplete';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Select,
  StatCard,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useStockIndex } from '../hooks/useStockIndex';
import { searchStocks } from '../utils/searchStocks';
import { MARKET_OPTIONS, toParsedError } from '../utils/masterKit';
import type { Market, StockIndexItem } from '../types/stockIndex';

const EMPTY_FORM = { code: '', name: '', market: 'cn', context: '' };

function toDebateMarket(market?: Market): string {
  if (market === 'HK') return 'hk';
  if (market === 'US') return 'us';
  if (market === 'JP') return 'jp';
  if (market === 'KR') return 'kr';
  return 'cn';
}

function inferMarketFromCode(code: string, fallback: string): string {
  const normalized = code.trim().toUpperCase();
  if (/^(HK)?\d{5}$|\.HK$/.test(normalized)) return 'hk';
  if (/\.T$/.test(normalized)) return 'jp';
  if (/\.(KS|KQ)$/.test(normalized)) return 'kr';
  if (/\.US$/.test(normalized) || /^[A-Z]{1,5}$/.test(normalized)) return 'us';
  if (/\.(SH|SZ|BJ)$/.test(normalized) || /^\d{6}$/.test(normalized)) return 'cn';
  return fallback;
}

function resolveStockQuery(query: string, index: StockIndexItem[], fallbackMarket: string) {
  const value = query.trim();
  if (!value) return null;

  const exactMatch = searchStocks(value, index, { limit: 1 })[0];
  if (exactMatch?.score >= 96) {
    return {
      code: exactMatch.displayCode,
      name: exactMatch.nameZh,
      market: toDebateMarket(exactMatch.market),
    };
  }

  if (/^(?:HK)?\d{4,6}(?:\.(?:SH|SZ|BJ|HK|T|KS|KQ))?$|^[A-Z]{1,5}(?:\.US)?$/i.test(value)) {
    return {
      code: value.toUpperCase(),
      name: '',
      market: inferMarketFromCode(value, fallbackMarket),
    };
  }

  return null;
}

function stanceVariant(stance: string): 'success' | 'danger' | 'info' {
  if (stance === 'bull') return 'success';
  if (stance === 'bear') return 'danger';
  return 'info';
}

function consensusVariant(consensus: string): 'success' | 'danger' | 'info' {
  if (consensus === 'bull') return 'success';
  if (consensus === 'bear') return 'danger';
  return 'info';
}

function recordToResult(record: MasterDebateRecordItem): MasterDebateResponse {
  const total = record.bullCount + record.bearCount + record.neutralCount;
  const majority = Math.max(record.bullCount, record.bearCount, record.neutralCount);
  const bullArguments = record.personas
    .filter((persona) => persona.stance === 'bull')
    .slice(0, 3)
    .map((persona) => persona.thesis)
    .filter(Boolean);
  const bearArguments = record.personas
    .filter((persona) => persona.stance === 'bear')
    .slice(0, 3)
    .map((persona) => persona.thesis)
    .filter(Boolean);
  return {
    ...record,
    conviction: total > 0 ? Math.round((100 * majority) / total) : 0,
    bullArguments,
    bearArguments,
    summary: record.summary ?? '',
  };
}

const MasterDebatePage: React.FC = () => {
  const { t } = useUiLanguage();
  const [form, setForm] = useState(EMPTY_FORM);
  const [result, setResult] = useState<MasterDebateResponse | null>(null);
  const [viewedRecord, setViewedRecord] = useState<MasterDebateRecordItem | null>(null);
  const [history, setHistory] = useState<MasterDebateRecordItem[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [stockQuery, setStockQuery] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const { index: stockIndex } = useStockIndex();
  const requestSeqRef = useRef(0);

  const loadHistory = useCallback(async () => {
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    try {
      const data = await masterDebateApi.list({ page: 1, pageSize: 20 });
      if (seq === requestSeqRef.current) setHistory(data.items);
    } catch {
      // history 加载失败不打断主流程
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    return () => {
      requestSeqRef.current += 1;
    };
  }, [loadHistory]);

  const handleRun = async () => {
    const resolvedStock = form.code.trim()
      ? { code: form.code.trim(), name: form.name.trim(), market: form.market }
      : resolveStockQuery(stockQuery, stockIndex, form.market);
    if (!resolvedStock) {
      const message = t('debate.form.invalidStock');
      setError({
        title: t('debate.form.invalidStockTitle'),
        message,
        rawMessage: message,
        category: 'missing_params',
      });
      return;
    }

    setRunning(true);
    setError(null);
    try {
      const data = await masterDebateApi.run({
        code: resolvedStock.code,
        name: resolvedStock.name || undefined,
        market: resolvedStock.market,
        context: form.context.trim() || undefined,
        persist: true,
      });
      setResult(data);
      setViewedRecord(null);
      await loadHistory();
    } catch (err) {
      setError(toParsedError(err, t('debate.error.title'), t('debate.error.title')));
    } finally {
      setRunning(false);
    }
  };

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow="Master Toolkit"
          title={t('debate.title')}
          description={t('debate.description')}
          actions={
            <Button variant="secondary" onClick={() => void loadHistory()}>
              <RefreshCw className="h-4 w-4" />
              {t('journal.refresh')}
            </Button>
          }
        />

        {error ? (
          <ApiErrorAlert error={error} actionLabel={t('common.retry')} onAction={() => setError(null)} />
        ) : null}

        <Card padding="md" variant="bordered">
          <p className="mb-2 text-sm font-medium text-foreground">{t('debate.form.stock')}</p>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
            <div className="min-w-0 flex-1">
              <StockAutocomplete
                value={stockQuery}
                onChange={(value) => {
                  setStockQuery(value);
                  setForm((current) => ({ ...current, code: '', name: '' }));
                  if (error?.category === 'missing_params') setError(null);
                }}
                onSubmit={(code, name, _source, metadata) => {
                  const displayCode = metadata?.displayCode || code.replace(/\.(SH|SZ|BJ|HK|US|T|KS|KQ)$/i, '');
                  const market = metadata?.market
                    ? toDebateMarket(metadata.market)
                    : inferMarketFromCode(code, form.market);
                  setStockQuery(displayCode);
                  setForm((current) => ({
                    ...current,
                    code: displayCode,
                    name: name || '',
                    market,
                  }));
                }}
                ariaLabel={t('debate.form.stock')}
                placeholder={t('debate.form.stockPlaceholder')}
                disabled={running}
                className="h-12 rounded-xl px-4 text-sm"
              />
              <div className="mt-2 flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary-text">
                <span>{t('debate.form.stockHint')}</span>
                {form.code ? (
                  <span className="font-medium text-accent">
                    {t('debate.form.recognized')} {form.name || form.code} · {form.code}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="lg:w-52">
              <Button
                variant="primary"
                className="h-12 w-full"
                isLoading={running}
                loadingText={t('debate.running')}
                disabled={!stockQuery.trim()}
                onClick={() => void handleRun()}
              >
                <Sparkles className="h-4 w-4" />
                {t('debate.form.run')}
              </Button>
            </div>
          </div>

          <button
            type="button"
            className="mt-4 inline-flex items-center gap-2 text-xs font-medium text-secondary-text transition-colors hover:text-foreground"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            {t('debate.form.advanced')}
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${advancedOpen ? 'rotate-180' : ''}`} />
          </button>

          {advancedOpen ? (
            <div className="mt-4 grid gap-4 border-t border-border/60 pt-4 md:grid-cols-[minmax(12rem,0.35fr)_minmax(0,1fr)]">
              <Select label={t('debate.form.market')} value={form.market} onChange={(v) => setForm((f) => ({ ...f, market: v }))} options={MARKET_OPTIONS} />
              <Input label={t('debate.form.context')} value={form.context} onChange={(e) => setForm((f) => ({ ...f, context: e.target.value }))} placeholder={t('debate.form.context')} />
            </div>
          ) : null}
        </Card>

        {running ? (
          <div className="h-32 animate-pulse rounded-2xl border border-border/60 bg-card/60" />
        ) : result ? (
          <>
            <div className="grid gap-4 md:grid-cols-3">
              <StatCard
                label={t('debate.consensus')}
                value={<Badge variant={consensusVariant(result.consensus)} size="md">{t(('debate.consensus.' + result.consensus) as 'debate.consensus.bull')}</Badge>}
                tone="primary"
                icon={<Scale className="h-5 w-5" />}
              />
              <StatCard label={t('debate.divergence')} value={result.divergence + '%'} hint={result.bullCount + ' ' + t('debate.stance.bull') + ' / ' + result.bearCount + ' ' + t('debate.stance.bear')} />
              <StatCard label={t('debate.conviction')} value={result.conviction + '%'} />
            </div>

            <Card padding="md" variant="bordered">
              {viewedRecord ? (
                <p className="mb-2 text-xs text-secondary-text">
                  {t('debate.viewingHistory')}
                  {viewedRecord.createdAt ? new Date(viewedRecord.createdAt).toLocaleString() : '-'}
                </p>
              ) : null}
              <p className="text-sm leading-6 text-secondary-text">{result.summary}</p>
            </Card>

            {result.bullArguments.length > 0 || result.bearArguments.length > 0 ? (
              <div className="grid gap-4 md:grid-cols-2">
                <Card padding="md" variant="bordered">
                  <h3 className="text-sm font-semibold text-success">{t('debate.bullArguments')}</h3>
                  <ul className="mt-2 space-y-1 text-sm text-secondary-text">
                    {result.bullArguments.map((arg, i) => <li key={i}>· {arg}</li>)}
                  </ul>
                </Card>
                <Card padding="md" variant="bordered">
                  <h3 className="text-sm font-semibold text-danger">{t('debate.bearArguments')}</h3>
                  <ul className="mt-2 space-y-1 text-sm text-secondary-text">
                    {result.bearArguments.map((arg, i) => <li key={i}>· {arg}</li>)}
                  </ul>
                </Card>
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {result.personas.map((persona) => (
                <Card key={persona.personaId} padding="md" variant="bordered" className="flex flex-col">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-foreground">{persona.name}</p>
                      <p className="text-xs text-secondary-text">{persona.englishName}</p>
                    </div>
                    <Badge variant={stanceVariant(persona.stance)}>{t(('debate.stance.' + persona.stance) as 'debate.stance.bull')}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-secondary-text">{persona.thesis}</p>
                  {persona.keyPoints.length > 0 ? (
                    <ul className="mt-2 space-y-1 text-xs text-secondary-text">
                      {persona.keyPoints.map((point, i) => <li key={i}>· {point}</li>)}
                    </ul>
                  ) : null}
                  <div className="mt-auto pt-3">
                    <p className="text-xs text-secondary-text">{t('debate.confidence')}: {(persona.confidence * 100).toFixed(0)}%</p>
                    {persona.risk ? <p className="mt-1 text-xs text-warning">{t('debate.risk')}: {persona.risk}</p> : null}
                  </div>
                </Card>
              ))}
            </div>
          </>
        ) : null}

        <Card padding="md" variant="bordered">
          <h2 className="text-lg font-semibold text-foreground">{t('debate.history')}</h2>
          {history.length === 0 ? (
            <div className="mt-4">
              <EmptyState title={t('debate.empty')} icon={<Scale className="h-6 w-6" />} />
            </div>
          ) : (
            <div className="mt-4 divide-y divide-border/60">
              {history.map((record) => (
                <button
                  key={record.id}
                  type="button"
                  aria-label={t('debate.viewHistory') + ': ' + (record.name || record.code)}
                  className="group flex w-full flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-3 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/60"
                  onClick={() => {
                    setViewedRecord(record);
                    setResult(recordToResult(record));
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-foreground">{record.name || record.code}</span>
                    <span className="text-xs text-secondary-text">{record.code}</span>
                    <Badge variant={consensusVariant(record.consensus)}>{t(('debate.consensus.' + record.consensus) as 'debate.consensus.bull')}</Badge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-secondary-text">
                    <span>{record.bullCount}{t('debate.stance.bull')} / {record.bearCount}{t('debate.stance.bear')}</span>
                    <span>{t('debate.divergence')} {record.divergence}%</span>
                    <span>{record.createdAt ? new Date(record.createdAt).toLocaleString() : '-'}</span>
                    <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>
    </AppPage>
  );
};

export default MasterDebatePage;
