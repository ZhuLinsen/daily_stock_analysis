import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, RefreshCw } from 'lucide-react';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { workbenchApi } from '../api/workbench';
import { ApiErrorAlert, AppPage, Card, EmptyState, Loading, PageHeader } from '../components/common';
import { RiskTags, WorkbenchDataNotice } from '../components/workbench';
import type { WorkbenchWatchlist } from '../types/workbench';
import { cn } from '../utils/cn';
import { formatAmountYi, formatNumber, formatPercent, signedClass } from '../components/workbench/format';

const WorkbenchWatchlistPage: React.FC = () => {
  const [data, setData] = useState<WorkbenchWatchlist | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [entryBudget, setEntryBudget] = useState('10000');

  const loadWithBudget = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const parsedBudget = Number(entryBudget || 10000);
      setData(await workbenchApi.getWatchlist(Number.isFinite(parsedBudget) && parsedBudget > 0 ? parsedBudget : 10000));
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, [entryBudget]);

  useEffect(() => {
    document.title = '自选股 - AI 股票复盘工作台';
    void workbenchApi.getWatchlist(10000)
      .then(setData)
      .catch((err) => setError(getParsedApiError(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="WATCHLIST"
        title="自选股 Watchlist"
        description="集中查看价格、题材、AI评分、状态标签，以及按预算估算的建仓挂单参考。"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-secondary-text">
              预算
              <input
                className="h-9 w-28 rounded-lg border border-border/70 bg-card px-3 text-sm text-foreground outline-none focus:border-primary/60"
                type="number"
                min="100"
                step="100"
                value={entryBudget}
                onChange={(event) => setEntryBudget(event.target.value)}
              />
            </label>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void loadWithBudget()} disabled={loading}><RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />刷新</button>
          </div>
        )}
      />
      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载自选股..." /> : null}
      {data ? <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} /> : null}
      {data && data.items.length === 0 ? <EmptyState title="暂无自选股" description="在首页或设置页维护 STOCK_LIST 后，这里会显示工作台视图。" /> : null}
      {data && data.items.length > 0 ? (
        <Card className="rounded-lg" padding="none">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1280px] text-sm">
              <thead className="bg-muted/60 text-left text-xs text-secondary-text">
                <tr>
                  <th className="px-4 py-3">代码</th>
                  <th className="px-4 py-3">名称</th>
                  <th className="px-4 py-3 text-right">最新价</th>
                  <th className="px-4 py-3 text-right">涨跌幅</th>
                  <th className="px-4 py-3 text-right">成交额</th>
                  <th className="px-4 py-3 text-right">换手率</th>
                  <th className="px-4 py-3 text-right">主力净流入</th>
                  <th className="px-4 py-3">行业/概念</th>
                  <th className="px-4 py-3 text-right">AI评分</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">建仓参考</th>
                  <th className="px-4 py-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.symbol} className="border-t border-border/50 hover:bg-hover/40">
                    <td className="px-4 py-3 font-mono text-secondary-text">{item.symbol}</td>
                    <td className="px-4 py-3 font-medium text-foreground">{item.name}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{item.latestPrice ?? '--'}</td>
                    <td className={cn('px-4 py-3 text-right tabular-nums', signedClass(item.changePct))}>{formatPercent(item.changePct)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatAmountYi(item.amount)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatPercent(item.turnoverRate)}</td>
                    <td className={cn('px-4 py-3 text-right tabular-nums', signedClass(item.mainNetInflow))}>{formatAmountYi(item.mainNetInflow)}</td>
                    <td className="max-w-[260px] px-4 py-3 text-secondary-text">
                      <div className="truncate">{item.industry || '--'}</div>
                      <div className="truncate text-xs">{item.concepts?.slice(0, 3).join(' / ') || '--'}</div>
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums text-cyan">{item.aiScore}</td>
                    <td className="px-4 py-3"><RiskTags status={item.statusTag} risks={item.riskTags} opportunities={item.opportunityTags} watches={item.watchTags} /></td>
                    <td className="max-w-[320px] px-4 py-3 text-xs leading-5 text-secondary-text">
                      {item.entryAdvice ? (
                        <div className="space-y-1">
                          <div className="font-medium text-foreground">{item.entryAdvice.action}</div>
                          <div>
                            限价 {formatNumber(item.entryAdvice.referencePrice, 3)} · {item.entryAdvice.lots} 手 · 约 {formatNumber(item.entryAdvice.estimatedAmount, 0)} 元
                          </div>
                          <div className="truncate">{item.entryAdvice.triggerCondition || item.entryAdvice.timing}</div>
                          <div className="truncate text-danger">失效：{item.entryAdvice.invalidCondition || '--'}</div>
                        </div>
                      ) : '--'}
                    </td>
                    <td className="px-4 py-3">
                      <Link className="btn-secondary inline-flex items-center gap-1 !px-3 !py-1.5 !text-xs" to={`/workbench/stocks/${encodeURIComponent(item.symbol)}`}><Eye className="h-3.5 w-3.5" />详情</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-border/60 px-4 py-3 text-xs text-secondary-text">
            {data.disclaimer}
          </div>
        </Card>
      ) : null}
    </AppPage>
  );
};

export default WorkbenchWatchlistPage;
