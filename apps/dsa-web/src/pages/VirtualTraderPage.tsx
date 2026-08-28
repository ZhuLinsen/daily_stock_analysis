import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  Bot,
  Briefcase,
  PiggyBank,
  Play,
  RefreshCw,
  Target,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { virtualTraderApi } from '../api/virtualTrader';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  InlineAlert,
  PageHeader,
  StatCard,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type {
  VirtualTraderAccount,
  VirtualTraderEquityCurve,
  VirtualTraderPredictionList,
  VirtualTraderStats,
  VirtualTraderTradeList,
} from '../types/virtualTrader';

const fmtCny = (value?: number | null) =>
  value == null ? '-' : `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
const fmtPct = (value?: number | null) =>
  value == null ? '-' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;

const pnlTextClass = (value?: number | null) => {
  if (value == null) return 'text-muted-text';
  return value >= 0 ? 'text-success' : 'text-danger';
};

const MARKET_LABELS: Record<string, string> = {
  cn: 'A 股',
  hk: '港股',
  us: '美股',
};

const TH_BASE = 'px-3 py-2 font-medium';
const TD_BASE = 'px-3 py-2';

export const VirtualTraderPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [account, setAccount] = useState<VirtualTraderAccount | null>(null);
  const [trades, setTrades] = useState<VirtualTraderTradeList | null>(null);
  const [predictions, setPredictions] = useState<VirtualTraderPredictionList | null>(null);
  const [curve, setCurve] = useState<VirtualTraderEquityCurve | null>(null);
  const [stats, setStats] = useState<VirtualTraderStats | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const requestSeqRef = useRef(0);

  const loadAll = useCallback(async () => {
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    setIsLoading(true);
    setError(null);
    try {
      const [accountData, tradeData, predictionData, curveData, statsData] = await Promise.all([
        virtualTraderApi.getAccount(),
        virtualTraderApi.listTrades({ pageSize: 30 }),
        virtualTraderApi.listPredictions({ pageSize: 30 }),
        virtualTraderApi.getEquityCurve(),
        virtualTraderApi.getStats(),
      ]);
      if (requestSeqRef.current !== seq) return;
      setAccount(accountData);
      setTrades(tradeData);
      setPredictions(predictionData);
      setCurve(curveData);
      setStats(statsData);
    } catch (nextError) {
      if (requestSeqRef.current === seq) {
        setError(getParsedApiError(nextError));
      }
    } finally {
      if (requestSeqRef.current === seq) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const handleRun = useCallback(async () => {
    setIsRunning(true);
    setRunMessage(null);
    try {
      const { results } = await virtualTraderApi.run();
      const ran = results.filter((r) => r.status === 'success').length;
      const skipped = results.filter((r) => r.status === 'skipped').length;
      setRunMessage(
        ran > 0
          ? t('trader.runDone', { ran, skipped }).replace('{ran}', String(ran)).replace('{skipped}', String(skipped))
          : t('trader.runSkipped'),
      );
      await loadAll();
    } catch (runError) {
      setError(getParsedApiError(runError));
    } finally {
      setIsRunning(false);
    }
  }, [loadAll, t]);

  const handleReset = useCallback(async () => {
    setShowResetConfirm(false);
    setIsRunning(true);
    try {
      await virtualTraderApi.reset();
      setRunMessage(t('trader.resetDone'));
      await loadAll();
    } catch (resetError) {
      setError(getParsedApiError(resetError));
    } finally {
      setIsRunning(false);
    }
  }, [loadAll, t]);

  const firstLoad = isLoading && !account;
  const prediction = stats?.prediction;
  const settledPredictions = prediction ? prediction.hit + prediction.miss : 0;
  const hitRate = prediction && settledPredictions > 0
    ? (prediction.hit / settledPredictions * 100).toFixed(1) + '%'
    : '-';
  const totalReturnPct = account?.totalReturnPct;
  const chartData = (curve?.points ?? []).map((p) => ({
    date: p.tradeDate.slice(5),
    value: p.totalValueCny,
  }));

  const renderSkeletonRow = (height: string) => (
    <div className={`${height} animate-pulse rounded-xl border border-border/60 bg-card/60`} />
  );

  return (
    <AppPage>
      <div className="space-y-5">
          <PageHeader
          title={t('trader.title')}
          description={t('trader.description')}
          actions={(
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void loadAll()}
                disabled={isLoading || isRunning}
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                {t('common.retry')}
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleRun()}
                disabled={isLoading || isRunning}
                isLoading={isRunning}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                {t('trader.runNow')}
              </Button>
              <Button
                variant="danger-subtle"
                size="sm"
                onClick={() => setShowResetConfirm(true)}
                disabled={isLoading || isRunning}
              >
                {t('trader.reset')}
              </Button>
            </>
          )}
        />

        {error ? <ApiErrorAlert error={error} /> : null}
        {runMessage ? (
          <InlineAlert variant="success" message={runMessage} />
        ) : null}

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {firstLoad ? (
            Array.from({ length: 5 }).map(() => renderSkeletonRow('h-[86px]'))
          ) : (
            <>
              <StatCard
                label={t('trader.totalValue')}
                value={fmtCny(account?.totalValueCny)}
                hint={`${t('trader.initialCapital')} ${fmtCny(account?.initialCashCny)}`}
                icon={<Wallet className="h-5 w-5" aria-hidden="true" />}
              />
              <StatCard
                label={t('trader.totalReturn')}
                value={
                  <span className={pnlTextClass(totalReturnPct)}>{fmtPct(totalReturnPct)}</span>
                }
                tone={(totalReturnPct ?? 0) >= 0 ? 'success' : 'danger'}
                icon={<TrendingUp className="h-5 w-5" aria-hidden="true" />}
              />
              <StatCard
                label={t('trader.cashReserve')}
                value={fmtCny(account?.cashTotalCny)}
                icon={<PiggyBank className="h-5 w-5" aria-hidden="true" />}
              />
              <StatCard
                label={t('trader.positionsValue')}
                value={fmtCny(account?.positionsValueCny)}
                hint={account ? t('trader.positionsCount').replace('{count}', String(account.positions.length)) : undefined}
                icon={<Briefcase className="h-5 w-5" aria-hidden="true" />}
              />
              <StatCard
                label={t('trader.hitRate')}
                value={hitRate}
                hint={
                  prediction && settledPredictions > 0
                    ? t('trader.hitMiss').replace('{hit}', String(prediction.hit)).replace('{miss}', String(prediction.miss))
                    : undefined
                }
                icon={<Target className="h-5 w-5" aria-hidden="true" />}
              />
            </>
          )}
        </div>

        <Card title={t('trader.equityCurve')}>
          {curve && chartData.length > 1 ? (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                  <defs>
                    <linearGradient id="vtEquityFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--chart-primary, #10b981)" stopOpacity={0.22} />
                      <stop offset="95%" stopColor="var(--chart-primary, #10b981)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    tickFormatter={(v: number) => `${(v / 10000).toFixed(0)}万`}
                    width={48}
                  />
                  <ChartTooltip
                    formatter={((value: unknown) => [fmtCny(Number(value)), t('trader.totalValue')]) as never}
                  />
                  <ReferenceLine
                    y={curve.initialCashCny}
                    stroke="currentColor"
                    strokeDasharray="4 4"
                    opacity={0.4}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="var(--chart-primary, #10b981)"
                    strokeWidth={2}
                    fill="url(#vtEquityFill)"
                    dot={chartData.length <= 30 ? { r: 2, strokeWidth: 0 } : false}
                    activeDot={{ r: 4 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : firstLoad ? (
            renderSkeletonRow('h-64')
          ) : (
            <EmptyState
              title={t('trader.curveEmpty')}
              icon={<TrendingUp className="h-8 w-8" aria-hidden="true" />}
              description={t('trader.curveEmptyDescription')}
            />
          )}
        </Card>

        <Card title={t('trader.positions')}>
          {account && account.positions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm tabular-nums">
                <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                  <tr>
                    <th className={TH_BASE}>{t('trader.colCode')}</th>
                    <th className={TH_BASE}>{t('trader.colMarket')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colQuantity')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colAvgCost')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colLastPrice')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colValueCny')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colPnl')}</th>
                  </tr>
                </thead>
                <tbody>
                  {account.positions.map((p) => (
                    <tr key={p.id} className="border-b border-border/40 last:border-b-0">
                      <td className={`${TD_BASE} font-medium`}>
                        {p.stockCode}
                        {p.name ? <span className="ml-2 text-muted-text">{p.name}</span> : null}
                      </td>
                      <td className={TD_BASE}>{MARKET_LABELS[p.market] ?? p.market}</td>
                      <td className={`${TD_BASE} text-right`}>{p.quantity}</td>
                      <td className={`${TD_BASE} text-right`}>{p.avgCost.toFixed(2)}</td>
                      <td className={`${TD_BASE} text-right`}>{p.lastPrice?.toFixed(2) ?? '-'}</td>
                      <td className={`${TD_BASE} text-right`}>{fmtCny(p.marketValueCny)}</td>
                      <td className={`${TD_BASE} text-right`}>
                        <Badge variant={(p.unrealizedPnlPct ?? 0) >= 0 ? 'success' : 'danger'} size="sm">
                          {fmtPct(p.unrealizedPnlPct)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : firstLoad ? (
            renderSkeletonRow('h-40')
          ) : (
            <EmptyState
              title={t('trader.noPositions')}
              description={t('trader.noPositionsDescription')}
              icon={<Bot className="h-8 w-8" aria-hidden="true" />}
            />
          )}
        </Card>

        <Card title={`${t('trader.trades')} (${trades?.total ?? 0})`}>
          {trades && trades.items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm tabular-nums">
                <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                  <tr>
                    <th className={TH_BASE}>{t('trader.colDate')}</th>
                    <th className={TH_BASE}>{t('trader.colSide')}</th>
                    <th className={TH_BASE}>{t('trader.colCode')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colQuantity')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colPrice')}</th>
                    <th className={TH_BASE}>{t('trader.colReason')}</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.items.map((trade) => (
                    <tr key={trade.id} className="border-b border-border/40 last:border-b-0">
                      <td className={`${TD_BASE} whitespace-nowrap`}>{trade.tradeDate}</td>
                      <td className={TD_BASE}>
                        <Badge variant={trade.side === 'buy' ? 'success' : 'danger'} size="sm">
                          {trade.side === 'buy' ? t('trader.buy') : t('trader.sell')}
                        </Badge>
                      </td>
                      <td className={`${TD_BASE} font-medium`}>{trade.stockCode}</td>
                      <td className={`${TD_BASE} text-right`}>{trade.quantity}</td>
                      <td className={`${TD_BASE} text-right`}>{trade.price.toFixed(2)}</td>
                      <td className={`${TD_BASE} text-muted-text`}>{trade.reason ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : firstLoad ? (
            renderSkeletonRow('h-40')
          ) : (
            <EmptyState title={t('trader.noTrades')} icon={<Bot className="h-8 w-8" aria-hidden="true" />} />
          )}
        </Card>

        <Card title={`${t('trader.predictions')} (${predictions?.total ?? 0})`}>
          {predictions && predictions.items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm tabular-nums">
                <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                  <tr>
                    <th className={TH_BASE}>{t('trader.colAnchorDate')}</th>
                    <th className={TH_BASE}>{t('trader.colCode')}</th>
                    <th className={TH_BASE}>{t('trader.colDirection')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colTarget')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colHorizon')}</th>
                    <th className={TH_BASE}>{t('trader.colOutcome')}</th>
                    <th className={`${TH_BASE} text-right`}>{t('trader.colActual')}</th>
                  </tr>
                </thead>
                <tbody>
                  {predictions.items.map((p) => (
                    <tr key={p.id} className="border-b border-border/40 last:border-b-0">
                      <td className={`${TD_BASE} whitespace-nowrap`}>{p.anchorDate}</td>
                      <td className={`${TD_BASE} font-medium`}>{p.stockCode}</td>
                      <td className={TD_BASE}>
                        <span className={`inline-flex items-center gap-1 ${p.direction === 'up' ? 'text-success' : 'text-danger'}`}>
                          {p.direction === 'up'
                            ? <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
                            : <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />}
                          {p.direction === 'up' ? t('trader.dirUp') : t('trader.dirDown')}
                        </span>
                      </td>
                      <td className={`${TD_BASE} text-right`}>{p.targetPrice.toFixed(2)}</td>
                      <td className={`${TD_BASE} text-right`}>{p.horizonDays}d</td>
                      <td className={TD_BASE}>
                        {p.status === 'pending' ? (
                          <Badge variant="history" size="sm">{t('trader.pending')}</Badge>
                        ) : p.outcome === 'hit' ? (
                          <Badge variant="success" size="sm">{t('trader.hit')}</Badge>
                        ) : p.outcome === 'miss' ? (
                          <Badge variant="danger" size="sm">{t('trader.miss')}</Badge>
                        ) : (
                          <Badge variant="history" size="sm">{t('trader.unable')}</Badge>
                        )}
                      </td>
                      <td className={`${TD_BASE} text-right ${pnlTextClass(p.actualReturnPct)}`}>
                        {fmtPct(p.actualReturnPct)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : firstLoad ? (
            renderSkeletonRow('h-40')
          ) : (
            <EmptyState
              title={t('trader.noPredictions')}
              description={t('trader.noPredictionsDescription')}
              icon={<TrendingUp className="h-8 w-8" aria-hidden="true" />}
            />
          )}
        </Card>

        <ConfirmDialog
          isOpen={showResetConfirm}
          title={t('trader.reset')}
          message={t('trader.resetConfirm')}
          confirmText={t('trader.reset')}
          cancelText={t('common.cancel')}
          isDanger
          onConfirm={() => void handleReset()}
          onCancel={() => setShowResetConfirm(false)}
        />
      </div>
    </AppPage>
  );
};

export default VirtualTraderPage;
