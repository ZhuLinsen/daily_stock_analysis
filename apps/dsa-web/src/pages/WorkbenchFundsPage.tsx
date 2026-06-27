import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { workbenchApi } from '../api/workbench';
import { ApiErrorAlert, AppPage, Badge, Card, EmptyState, Loading, PageHeader, StatCard } from '../components/common';
import { FundNavChart, WorkbenchDataNotice } from '../components/workbench';
import type { WorkbenchFundResponse } from '../types/workbench';
import { cn } from '../utils/cn';
import { formatNumber, formatPercent, signedClass } from '../components/workbench/format';

const WorkbenchFundsPage: React.FC = () => {
  const [fundCode, setFundCode] = useState('000001');
  const [budget, setBudget] = useState('10000');
  const [data, setData] = useState<WorkbenchFundResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const load = useCallback(async () => {
    const code = fundCode.trim();
    if (!code) return;
    setLoading(true);
    setError(null);
    try {
      const parsedBudget = Number(budget || 10000);
      setData(await workbenchApi.getFundAnalysis(code, Number.isFinite(parsedBudget) && parsedBudget > 0 ? parsedBudget : 10000));
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, [budget, fundCode]);

  useEffect(() => {
    document.title = '场外基金 - AI 股票复盘工作台';
    void load();
  }, []);

  const fund = data?.fund;
  const returns = fund?.returns;

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="MUTUAL FUND"
        title="场外基金净值分析"
        description="查看场外基金净值走势、阶段收益、回撤风险和按预算拆分的申购参考。"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="h-9 w-28 rounded-lg border border-border/70 bg-card px-3 text-sm text-foreground outline-none focus:border-primary/60"
              value={fundCode}
              onChange={(event) => setFundCode(event.target.value)}
              placeholder="基金代码"
            />
            <input
              className="h-9 w-28 rounded-lg border border-border/70 bg-card px-3 text-sm text-foreground outline-none focus:border-primary/60"
              type="number"
              min="100"
              step="100"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              placeholder="预算"
            />
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />分析
            </button>
          </div>
        )}
      />

      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载基金净值..." /> : null}
      {data ? <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} /> : null}

      {data && !fund ? <EmptyState title="暂无基金数据" description="请检查基金代码，或稍后重试东方财富基金净值接口。" /> : null}

      {fund ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="最新净值" value={formatNumber(fund.latestNav, 4)} hint={fund.latestDate || '净值确认日'} />
            <StatCard label="日增长率" value={formatPercent(fund.latestGrowthPct)} tone={(fund.latestGrowthPct ?? 0) >= 0 ? 'danger' : 'success'} />
            <StatCard label="最大回撤" value={formatPercent(fund.maxDrawdownPct)} hint="近一年样本" tone="warning" />
            <StatCard label="基金评分" value={fund.aiScore} hint={`风险等级：${fund.riskLevel}`} />
          </section>

          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="盘中估值"
              value={formatNumber(fund.intradayEstimate?.estimateNav, 4)}
              hint={fund.intradayEstimate?.estimateTime || fund.intradayEstimate?.error || '天天基金估值'}
              tone={(fund.intradayEstimate?.estimateGrowthPct ?? 0) >= 0 ? 'danger' : 'success'}
            />
            <StatCard
              label="估值涨跌"
              value={formatPercent(fund.intradayEstimate?.estimateGrowthPct)}
              hint={fund.intradayEstimate?.stale ? '估值延迟/不可用' : '盘中估算，仅作参考'}
              tone={(fund.intradayEstimate?.estimateGrowthPct ?? 0) >= 0 ? 'danger' : 'success'}
            />
            <StatCard
              label="同类排名"
              value={fund.rank?.rank && fund.rank?.total ? `${fund.rank.rank}/${fund.rank.total}` : '--'}
              hint={`${fund.rank?.type || fund.type} · ${fund.rank?.period || '近一年'}`}
            />
            <StatCard
              label="同类分位"
              value={fund.rank?.percentile !== null && fund.rank?.percentile !== undefined ? `${formatNumber(fund.rank.percentile, 1)}%` : '--'}
              hint={fund.rank?.error || '越高代表同类越靠前'}
            />
          </section>

          <Card className="rounded-lg" padding="md">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="label-uppercase">{fund.code}</p>
                <h2 className="mt-1 text-xl font-semibold text-foreground">{fund.name}</h2>
                <p className="mt-2 text-sm text-secondary-text">{fund.type}{fund.manager ? ` · ${fund.manager}` : ''}{fund.scale ? ` · ${fund.scale}` : ''}</p>
              </div>
              <Badge variant={fund.riskLevel === '高' ? 'danger' : fund.riskLevel === '中' ? 'warning' : 'success'}>{fund.riskLevel}风险</Badge>
            </div>
            <p className="mt-4 text-sm leading-7 text-secondary-text">{fund.summary}</p>
            <p className="mt-3 text-xs text-secondary-text">{fund.disclaimer}</p>
          </Card>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.75fr)]">
            <Card className="rounded-lg" padding="sm">
              <FundNavChart data={fund.navHistory} title={`${fund.name} 净值走势`} />
            </Card>
            <Card className="rounded-lg" padding="md">
              <p className="label-uppercase">申购参考</p>
              <h3 className="mt-2 text-lg font-semibold text-foreground">{fund.subscriptionReference.action}</h3>
              <p className="mt-2 text-sm leading-6 text-secondary-text">首笔参考 {formatNumber(fund.subscriptionReference.firstAmount, 0)} 元。{fund.subscriptionReference.timing}</p>
              <div className="mt-4 space-y-2">
                {fund.subscriptionReference.batchPlan.length === 0 ? (
                  <p className="text-sm text-secondary-text">当前建议暂缓申购，先观察净值和回撤是否企稳。</p>
                ) : fund.subscriptionReference.batchPlan.map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-sm">
                    <span className="text-secondary-text">{item.label}</span>
                    <span className="font-medium text-foreground">{formatNumber(item.amount, 0)} 元</span>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs leading-5 text-danger">失效条件：{fund.subscriptionReference.invalidCondition}</p>
            </Card>
          </section>

          <Card className="rounded-lg" padding="sm">
            <h3 className="mb-3 text-base font-semibold text-foreground">阶段收益</h3>
            <div className="grid gap-2 sm:grid-cols-5">
              {(['1w', '1m', '3m', '6m', '1y'] as const).map((key) => (
                <div key={key} className="rounded-lg border border-border/60 bg-card/70 p-3 text-sm">
                  <div className="text-xs text-secondary-text">{key}</div>
                  <div className={cn('mt-1 font-semibold tabular-nums', signedClass(returns?.[key]))}>{formatPercent(returns?.[key])}</div>
                </div>
              ))}
            </div>
          </Card>

          <section className="grid gap-4 xl:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-foreground">基金持仓行业</h3>
                {fund.industryAllocationStatus?.stale || fund.industryAllocationStatus?.error ? <Badge variant="warning">数据延迟</Badge> : null}
              </div>
              {(fund.industryAllocation || []).length === 0 ? (
                <p className="text-sm leading-6 text-secondary-text">暂无行业配置数据。部分基金只在季报披露后更新持仓行业。</p>
              ) : (
                <div className="space-y-3">
                  {(fund.industryAllocation || []).slice(0, 8).map((item) => (
                    <div key={item.name}>
                      <div className="mb-1 flex items-center justify-between text-xs">
                        <span className="truncate text-secondary-text">{item.name}</span>
                        <span className="font-medium text-foreground">{formatPercent(item.weightPct)}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-muted/60">
                        <div className="h-full rounded-full bg-cyan" style={{ width: `${Math.max(0, Math.min(100, item.weightPct ?? 0))}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {fund.industryAllocationStatus?.error ? <p className="mt-3 text-xs text-warning">{fund.industryAllocationStatus.error}</p> : null}
            </Card>

            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-foreground">前十大持仓</h3>
                {fund.holdingsStatus?.stale || fund.holdingsStatus?.error ? <Badge variant="warning">数据延迟</Badge> : null}
              </div>
              {(fund.holdings || []).length === 0 ? (
                <p className="text-sm leading-6 text-secondary-text">暂无持仓明细。场外基金持仓通常按季报披露，不是实时股票池。</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead className="bg-muted/50 text-left text-xs text-secondary-text">
                      <tr>
                        <th className="px-3 py-2">名称</th>
                        <th className="px-3 py-2">代码</th>
                        <th className="px-3 py-2 text-right">占净值</th>
                        <th className="px-3 py-2 text-right">市值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(fund.holdings || []).slice(0, 10).map((item) => (
                        <tr key={`${item.code || item.name}`} className="border-t border-border/50">
                          <td className="px-3 py-2 font-medium text-foreground">{item.name}</td>
                          <td className="px-3 py-2 font-mono text-secondary-text">{item.code || '--'}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{formatPercent(item.weightPct)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{formatNumber(item.marketValue, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {fund.holdingsStatus?.error ? <p className="mt-3 text-xs text-warning">{fund.holdingsStatus.error}</p> : null}
            </Card>
          </section>
        </>
      ) : null}
    </AppPage>
  );
};

export default WorkbenchFundsPage;
