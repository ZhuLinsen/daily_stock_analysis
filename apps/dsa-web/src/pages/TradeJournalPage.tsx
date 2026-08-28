import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NotebookPen, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { tradeJournalApi } from '../api/tradeJournal';
import type { TradeJournalEmotion, TradeJournalItem, TradeJournalMarket, TradeJournalReviewResponse } from '../types/tradeJournal';
import type { ParsedApiError } from '../api/error';
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
import { EMOTION_OPTIONS, MARKET_OPTIONS, toParsedError } from '../utils/masterKit';
import { cn } from '../utils/cn';

const EMPTY_FORM = {
  code: '',
  name: '',
  market: 'cn',
  side: 'buy',
  quantity: '',
  price: '',
  fee: '',
  tax: '',
  tradeDate: '',
  thesis: '',
  strategy: '',
  emotion: '',
  planFollowed: false,
  tags: '',
};

function formatPnl(value: number | null | undefined): string {
  if (value == null) return '-';
  const sign = value > 0 ? '+' : '';
  return sign + value.toFixed(2);
}

const TradeJournalPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [entries, setEntries] = useState<TradeJournalItem[]>([]);
  const [review, setReview] = useState<TradeJournalReviewResponse | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const requestSeqRef = useRef(0);

  const load = useCallback(async (targetPage = page) => {
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    setLoading(true);
    setError(null);
    try {
      const [listData, reviewData] = await Promise.all([
        tradeJournalApi.list({ page: targetPage, pageSize }),
        tradeJournalApi.review(),
      ]);
      if (seq !== requestSeqRef.current) return;
      setEntries(listData.items);
      setTotal(listData.total);
      setReview(reviewData);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      setError(toParsedError(err, t('journal.error.title'), t('journal.error.title')));
    } finally {
      if (seq === requestSeqRef.current) setLoading(false);
    }
  }, [page, pageSize, t]);

  useEffect(() => {
    void load();
    return () => {
      requestSeqRef.current += 1;
    };
  }, [load]);

  const setField = (key: keyof typeof EMPTY_FORM, value: string | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    if (!form.code.trim() || !form.quantity || !form.price || !form.tradeDate) return;
    setSubmitting(true);
    setError(null);
    try {
      await tradeJournalApi.create({
        code: form.code.trim(),
        name: form.name.trim() || undefined,
        market: form.market as TradeJournalMarket,
        side: form.side,
        quantity: Number(form.quantity),
        price: Number(form.price),
        fee: form.fee ? Number(form.fee) : 0,
        tax: form.tax ? Number(form.tax) : 0,
        tradeDate: form.tradeDate,
        thesis: form.thesis.trim() || undefined,
        strategy: form.strategy.trim() || undefined,
        emotion: (form.emotion || undefined) as TradeJournalEmotion,
        planFollowed: form.planFollowed || undefined,
        tags: form.tags ? form.tags.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load(1);
    } catch (err) {
      setError(toParsedError(err, t('journal.error.title'), t('journal.error.title')));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setError(null);
    try {
      await tradeJournalApi.remove(id);
      await load(page);
    } catch (err) {
      setError(toParsedError(err, t('journal.error.title'), t('journal.error.title')));
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow="Master Toolkit"
          title={t('journal.title')}
          description={t('journal.description')}
          actions={
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="md" onClick={() => void load()} disabled={loading}>
                <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
                {t('journal.refresh')}
              </Button>
              <Button variant="primary" size="md" onClick={() => setShowForm((v) => !v)}>
                <Plus className="h-4 w-4" />
                {t('journal.addTrade')}
              </Button>
            </div>
          }
        />

        {error ? (
          <ApiErrorAlert error={error} actionLabel={t('common.retry')} onAction={() => void load()} />
        ) : null}

        {showForm ? (
          <Card padding="md" variant="bordered">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Input label={t('journal.form.code')} value={form.code} onChange={(e) => setField('code', e.target.value)} placeholder="600519" />
              <Input label={t('journal.form.name')} value={form.name} onChange={(e) => setField('name', e.target.value)} placeholder={t('journal.form.name')} />
              <Select label={t('journal.form.market')} value={form.market} onChange={(v) => setField('market', v)} options={MARKET_OPTIONS} />
              <Select label={t('journal.form.side')} value={form.side} onChange={(v) => setField('side', v)} options={[{ value: 'buy', label: t('journal.side.buy') }, { value: 'sell', label: t('journal.side.sell') }]} />
              <Input label={t('journal.form.quantity')} type="number" value={form.quantity} onChange={(e) => setField('quantity', e.target.value)} placeholder="100" />
              <Input label={t('journal.form.price')} type="number" value={form.price} onChange={(e) => setField('price', e.target.value)} placeholder="10.00" />
              <Input label={t('journal.form.fee')} type="number" value={form.fee} onChange={(e) => setField('fee', e.target.value)} placeholder="0" />
              <Input label={t('journal.form.tax')} type="number" value={form.tax} onChange={(e) => setField('tax', e.target.value)} placeholder="0" />
              <Input label={t('journal.form.tradeDate')} type="date" value={form.tradeDate} onChange={(e) => setField('tradeDate', e.target.value)} />
              <Input label={t('journal.form.strategy')} value={form.strategy} onChange={(e) => setField('strategy', e.target.value)} placeholder="trend" />
              <Select label={t('journal.form.emotion')} value={form.emotion} onChange={(v) => setField('emotion', v)} options={[{ value: '', label: '-' }, ...EMOTION_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))]} />
              <Input label={t('journal.form.tags')} value={form.tags} onChange={(e) => setField('tags', e.target.value)} placeholder="趋势, 价值" />
            </div>
            <Input label={t('journal.form.thesis')} className="mt-4" value={form.thesis} onChange={(e) => setField('thesis', e.target.value)} placeholder={t('journal.form.thesis')} />
            <label className="mt-4 flex items-center gap-2 text-sm text-secondary-text">
              <input type="checkbox" checked={form.planFollowed} onChange={(e) => setField('planFollowed', e.target.checked)} />
              {t('journal.form.planFollowed')}
            </label>
            <div className="mt-5 flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowForm(false)}>{t('journal.form.cancel')}</Button>
              <Button variant="primary" isLoading={submitting} onClick={() => void handleSubmit()}>{t('journal.form.submit')}</Button>
            </div>
          </Card>
        ) : null}

        {review ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <StatCard label={t('journal.review.entryCount')} value={String(review.entryCount)} icon={<NotebookPen className="h-5 w-5" />} tone="primary" />
            <StatCard label={t('journal.review.closedTrades')} value={String(review.closedTradeCount)} />
            <StatCard label={t('journal.review.winRate')} value={review.winRate == null ? '-' : review.winRate + '%'} tone={review.winRate != null && review.winRate >= 50 ? 'success' : 'default'} />
            <StatCard label={t('journal.review.totalPnl')} value={formatPnl(review.totalPnl)} tone={review.totalPnl >= 0 ? 'success' : 'danger'} />
            <StatCard label={t('journal.review.disciplineScore')} value={review.disciplineScore == null ? '-' : review.disciplineScore + '%'} tone="primary" />
          </div>
        ) : null}

        <Card padding="md" variant="bordered">
          <h2 className="text-lg font-semibold text-foreground">{t('journal.list.title')}</h2>
          {loading && entries.length === 0 ? (
            <div className="mt-4 space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl border border-border/60 bg-card/60" />
              ))}
            </div>
          ) : entries.length === 0 ? (
            <div className="mt-4">
              <EmptyState title={t('journal.list.empty')} icon={<NotebookPen className="h-6 w-6" />} />
            </div>
          ) : (
            <div className="mt-4 divide-y divide-border/60">
              {entries.map((entry) => (
                <div key={entry.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-foreground">{entry.name || entry.code}</span>
                      <span className="text-xs text-secondary-text">{entry.code}</span>
                      <Badge variant={entry.side === 'buy' ? 'success' : 'danger'}>{entry.side === 'buy' ? t('journal.side.buy') : t('journal.side.sell')}</Badge>
                      {entry.emotion ? <Badge variant="info">{entry.emotion}</Badge> : null}
                    </div>
                    <p className="mt-1 truncate text-xs text-secondary-text">
                      {entry.quantity} × {entry.price} · {entry.tradeDate || '-'}
                      {entry.thesis ? ' · ' + entry.thesis : ''}
                    </p>
                  </div>
                  <Button variant="danger-subtle" size="sm" onClick={() => void handleDelete(entry.id)}>
                    <Trash2 className="h-4 w-4" />
                    {t('journal.delete')}
                  </Button>
                </div>
              ))}
            </div>
          )}
          <div className="mt-4 flex justify-end">
            {totalPages > 1 ? (
              <div className="flex items-center gap-1">
                <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => { setPage((p) => Math.max(1, p - 1)); }}>‹</Button>
                <span className="px-2 text-sm text-secondary-text">{page} / {totalPages}</span>
                <Button variant="secondary" size="sm" disabled={page >= totalPages} onClick={() => { setPage((p) => p + 1); }}>›</Button>
              </div>
            ) : null}
          </div>
        </Card>
      </div>
    </AppPage>
  );
};

export default TradeJournalPage;
