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
import { formatAmountYi, formatPercent, signedClass } from '../components/workbench/format';

const WorkbenchWatchlistPage: React.FC = () => {
  const [data, setData] = useState<WorkbenchWatchlist | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await workbenchApi.getWatchlist());
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = '自选股 - AI 股票复盘工作台';
    void load();
  }, [load]);

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="WATCHLIST"
        title="自选股 Watchlist"
        description="集中查看价格、涨跌幅、成交额、换手率、主力净流入、题材归属、AI评分和状态标签。"
        actions={<button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void load()} disabled={loading}><RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />刷新</button>}
      />
      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载自选股..." /> : null}
      {data ? <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} /> : null}
      {data && data.items.length === 0 ? <EmptyState title="暂无自选股" description="在首页或设置页维护 STOCK_LIST 后，这里会显示工作台视图。" /> : null}
      {data && data.items.length > 0 ? (
        <Card className="rounded-lg" padding="none">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
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
