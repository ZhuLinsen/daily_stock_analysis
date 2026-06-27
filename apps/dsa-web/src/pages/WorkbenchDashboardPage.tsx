import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BarChart3, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { workbenchApi } from '../api/workbench';
import { ApiErrorAlert, AppPage, Card, Loading, PageHeader, StatCard } from '../components/common';
import { BoardHeatList, WorkbenchDataNotice } from '../components/workbench';
import type { WorkbenchDashboard } from '../types/workbench';
import { cn } from '../utils/cn';
import { formatAmountYi, formatNumber, formatPercent, signedClass } from '../components/workbench/format';

const WorkbenchDashboardPage: React.FC = () => {
  const [data, setData] = useState<WorkbenchDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await workbenchApi.getDashboard());
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = '市场总览 - AI 股票复盘工作台';
    void load();
  }, [load]);

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="AI STOCK WORKBENCH"
        title="市场总览 Dashboard"
        description="用普通用户能看懂的方式看指数、成交额、涨跌家数、涨跌停、强势行业和 AI 市场情绪。"
        actions={(
          <div className="flex flex-wrap gap-2">
            <Link to="/workbench/watchlist" className="btn-secondary inline-flex items-center gap-2">自选股 <ArrowRight className="h-4 w-4" /></Link>
            <Link to="/workbench/funds" className="btn-secondary inline-flex items-center gap-2">场外基金 <ArrowRight className="h-4 w-4" /></Link>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} /> 刷新
            </button>
          </div>
        )}
      />

      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载市场总览..." /> : null}

      {data ? (
        <>
          <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} />
          {data.breadth.partial ? (
            <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200">
              涨跌家数使用同花顺 Fuyao 快照样本 {data.breadth.sampleSize ?? 0} / {data.breadth.totalCount ?? '--'} 只估算，完整全市场统计可由后台定时缓存补齐。
            </div>
          ) : null}
          <section className="grid gap-3 md:grid-cols-3">
            {data.indices.map((item) => (
              <Card key={item.name} className="rounded-lg" padding="sm">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm text-secondary-text">{item.name}</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">{formatNumber(item.current)}</p>
                  </div>
                  <div className={cn('text-right text-sm font-medium', signedClass(item.changePct))}>
                    {item.changePct && item.changePct >= 0 ? <TrendingUp className="ml-auto h-5 w-5" /> : <TrendingDown className="ml-auto h-5 w-5" />}
                    <p className="mt-1">{formatPercent(item.changePct)}</p>
                  </div>
                </div>
              </Card>
            ))}
          </section>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="成交额" value={formatAmountYi(data.breadth.totalAmount)} icon={<BarChart3 className="h-5 w-5" />} />
            <StatCard label="涨跌家数" value={`${data.breadth.upCount} / ${data.breadth.downCount}`} hint={`${data.breadth.partial ? '样本估算 · ' : ''}平盘 ${data.breadth.flatCount}`} icon={<TrendingUp className="h-5 w-5" />} />
            <StatCard label="涨停/跌停" value={`${data.breadth.limitUpCount} / ${data.breadth.limitDownCount}`} hint="短线情绪温度" icon={<TrendingDown className="h-5 w-5" />} />
            <StatCard label="数据状态" value={data.stale ? '延迟' : '正常'} hint={data.source} icon={<RefreshCw className="h-5 w-5" />} />
          </section>

          <Card className="rounded-lg" padding="md">
            <p className="label-uppercase">AI 市场情绪总结</p>
            <p className="mt-2 text-base leading-7 text-foreground">{data.aiMarketSummary}</p>
            <p className="mt-3 text-xs text-secondary-text">{data.disclaimer}</p>
          </Card>

          <section className="grid gap-4 xl:grid-cols-2">
            <BoardHeatList title="强势行业" items={data.strongIndustries} />
            <BoardHeatList title="强势概念" items={data.strongConcepts} />
          </section>

          <Card className="rounded-lg" padding="sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-foreground">涨停池</h3>
              <span className="text-xs text-secondary-text">用于观察短线情绪，不代表次日延续</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-secondary-text">
                  <tr className="border-b border-border/60">
                    <th className="py-2 pr-3">代码</th>
                    <th className="py-2 pr-3">名称</th>
                    <th className="py-2 pr-3 text-right">涨跌幅</th>
                    <th className="py-2 pr-3 text-right">换手率</th>
                    <th className="py-2 pr-3">行业</th>
                    <th className="py-2 pr-3">连板</th>
                  </tr>
                </thead>
                <tbody>
                  {data.limitUpPool.map((item) => (
                    <tr key={`${item.code}-${item.name}`} className="border-b border-border/40 last:border-0">
                      <td className="py-2 pr-3 font-mono text-secondary-text">{item.code}</td>
                      <td className="py-2 pr-3 font-medium text-foreground">{item.name}</td>
                      <td className="py-2 pr-3 text-right text-red-500">{formatPercent(item.changePct)}</td>
                      <td className="py-2 pr-3 text-right">{formatPercent(item.turnoverRate)}</td>
                      <td className="py-2 pr-3 text-secondary-text">{item.industry || '--'}</td>
                      <td className="py-2 pr-3">{item.consecutiveBoards ?? '--'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </AppPage>
  );
};

export default WorkbenchDashboardPage;
