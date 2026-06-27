import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardCopy, Download, Eye, RefreshCw, ShieldAlert, Target } from 'lucide-react';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { workbenchApi } from '../api/workbench';
import { ApiErrorAlert, AppPage, Badge, Card, EmptyState, Loading, PageHeader, StatCard } from '../components/common';
import { BoardHeatList, RiskTags, WorkbenchDataNotice } from '../components/workbench';
import type { WorkbenchDailyReview } from '../types/workbench';
import { cn } from '../utils/cn';
import { formatAmountYi, formatPercent, signedClass } from '../components/workbench/format';

const downloadMarkdown = (filename: string, content: string) => {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
};

function actionVariant(action: string): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (action === '止损观察') return 'danger';
  if (action === '减仓') return 'warning';
  if (action === '加仓等待') return 'info';
  if (action === '持有') return 'success';
  return 'default';
}

const WorkbenchDailyReviewPage: React.FC = () => {
  const [data, setData] = useState<WorkbenchDailyReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await workbenchApi.getDailyReview());
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const payload = await workbenchApi.exportDailyReviewMarkdown();
      downloadMarkdown(payload.filename || 'daily-review.md', payload.markdown || data?.markdown || '');
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setExporting(false);
    }
  }, [data?.markdown]);

  const handleCopy = useCallback(async () => {
    if (!data?.markdown || !navigator.clipboard?.writeText) return;
    await navigator.clipboard.writeText(data.markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }, [data?.markdown]);

  useEffect(() => {
    document.title = '每日复盘 - AI 股票复盘工作台';
    void load();
  }, [load]);

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="DAILY REVIEW"
        title="每日复盘 DailyReview"
        description="市场一句话、强弱板块、自选股表现、持仓风险和明日观察清单。"
        actions={(
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void handleCopy()} disabled={!data?.markdown}>
              <ClipboardCopy className="h-4 w-4" />{copied ? '已复制' : '复制 Markdown'}
            </button>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void handleExport()} disabled={exporting || !data?.markdown}>
              <Download className="h-4 w-4" />{exporting ? '导出中' : '导出 Markdown'}
            </button>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />刷新
            </button>
          </div>
        )}
      />

      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载每日复盘..." /> : null}

      {data ? (
        <>
          <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} />

          <Card className="rounded-lg" padding="md">
            <p className="label-uppercase">今日市场一句话</p>
            <p className="mt-2 text-lg leading-8 text-foreground">{data.oneLiner || '今日市场数据不完整，先以自选股和板块热度做轻量复盘。'}</p>
            <p className="mt-3 text-xs text-secondary-text">{data.disclaimer}</p>
          </Card>

          <section className="grid gap-3 md:grid-cols-3">
            <StatCard label="自选股数量" value={data.watchlistPerformance.length} hint="纳入今日复盘" />
            <StatCard label="风险提醒" value={data.holdingRisks.length} hint="高位、破位或资金流出" tone={data.holdingRisks.length > 0 ? 'danger' : 'success'} />
            <StatCard label="持仓处理" value={data.portfolioActionList?.length || 0} hint="真实持仓建议卡" tone={(data.holdingActionSummary?.止损观察 || data.holdingActionSummary?.减仓 || 0) > 0 ? 'warning' : 'success'} />
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <BoardHeatList title="今日最强板块" items={data.strongestBoards} />
            <BoardHeatList title="今日风险板块" items={data.riskBoards} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.75fr)]">
            <Card className="rounded-lg" padding="none">
              <div className="border-b border-border/60 p-4">
                <h3 className="text-base font-semibold text-foreground">自选股表现</h3>
              </div>
              {data.watchlistPerformance.length === 0 ? (
                <EmptyState title="暂无自选股表现" description="配置 STOCK_LIST 后，这里会生成每日复盘表格。" className="m-4" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[760px] text-sm">
                    <thead className="bg-muted/60 text-left text-xs text-secondary-text">
                      <tr>
                        <th className="px-4 py-3">代码</th>
                        <th className="px-4 py-3">名称</th>
                        <th className="px-4 py-3 text-right">涨跌幅</th>
                        <th className="px-4 py-3 text-right">成交额</th>
                        <th className="px-4 py-3 text-right">AI评分</th>
                        <th className="px-4 py-3">状态</th>
                        <th className="px-4 py-3">详情</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.watchlistPerformance.map((item) => (
                        <tr key={item.symbol} className="border-t border-border/50 hover:bg-hover/40">
                          <td className="px-4 py-3 font-mono text-secondary-text">{item.symbol}</td>
                          <td className="px-4 py-3 font-medium text-foreground">{item.name}</td>
                          <td className={cn('px-4 py-3 text-right tabular-nums', signedClass(item.changePct))}>{formatPercent(item.changePct)}</td>
                          <td className="px-4 py-3 text-right tabular-nums">{formatAmountYi(item.amount)}</td>
                          <td className="px-4 py-3 text-right font-semibold text-cyan tabular-nums">{item.aiScore}</td>
                          <td className="px-4 py-3"><RiskTags status={item.statusTag} risks={item.riskTags} opportunities={item.opportunityTags} watches={item.watchTags} /></td>
                          <td className="px-4 py-3">
                            <Link className="btn-secondary inline-flex items-center gap-1 !px-3 !py-1.5 !text-xs" to={`/workbench/stocks/${encodeURIComponent(item.symbol)}`}><Eye className="h-3.5 w-3.5" />查看</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <div className="space-y-4">
              <Card className="rounded-lg" padding="sm">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Target className="h-4 w-4 text-cyan" />
                    <h3 className="text-base font-semibold text-foreground">明日持仓处理清单</h3>
                  </div>
                  <span className="text-xs text-secondary-text">{data.holdingActionSummary?.total || 0} 只</span>
                </div>
                {(data.portfolioActionList || []).length === 0 ? (
                  <p className="text-sm leading-6 text-secondary-text">暂无真实持仓建议。导入持仓后，这里会按盈亏和仓位生成处理清单。</p>
                ) : (
                  <div className="space-y-3">
                    {(data.portfolioActionList || []).slice(0, 8).map((item) => (
                      <div key={`${item.accountId ?? 'all'}-${item.symbol}`} className="rounded-lg border border-border/60 bg-card/60 p-3">
                        <div className="flex items-start justify-between gap-3 text-sm">
                          <div className="min-w-0">
                            <div className="truncate font-medium text-foreground">{item.name || item.symbol}</div>
                            <div className="mt-1 font-mono text-xs text-secondary-text">{item.symbol} · 仓位 {formatPercent(item.weightPct)}</div>
                          </div>
                          <Badge variant={actionVariant(item.action)}>{item.action}</Badge>
                        </div>
                        <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                          <div className="rounded-md bg-muted/40 p-2">
                            <div className="text-secondary-text">盈亏</div>
                            <div className={cn('mt-1 font-semibold', item.unrealizedPnlPct !== null && item.unrealizedPnlPct !== undefined && item.unrealizedPnlPct < 0 ? 'text-danger' : 'text-red-500 dark:text-red-300')}>{formatPercent(item.unrealizedPnlPct)}</div>
                          </div>
                          <div className="rounded-md bg-muted/40 p-2">
                            <div className="text-secondary-text">AI评分</div>
                            <div className="mt-1 font-semibold text-cyan">{item.aiScore}</div>
                          </div>
                          <div className="rounded-md bg-muted/40 p-2">
                            <div className="text-secondary-text">价格</div>
                            <div className="mt-1 font-semibold text-foreground">{item.priceStale ? '延迟' : '可用'}</div>
                          </div>
                        </div>
                        <p className="mt-2 text-xs leading-5 text-secondary-text">{item.reason}</p>
                        {item.nextDayWatch.length > 0 ? (
                          <div className="mt-2 space-y-1 text-xs leading-5 text-secondary-text">
                            {item.nextDayWatch.slice(0, 2).map((watch) => <p key={`${item.symbol}-${watch}`}>- {watch}</p>)}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card className="rounded-lg" padding="sm">
                <div className="mb-3 flex items-center gap-2">
                  <ShieldAlert className="h-4 w-4 text-danger" />
                  <h3 className="text-base font-semibold text-foreground">自选股风险</h3>
                </div>
                {data.holdingRisks.length === 0 ? (
                  <p className="text-sm leading-6 text-secondary-text">暂无明显风险标签，仍需按计划控制仓位。</p>
                ) : (
                  <div className="space-y-3">
                    {data.holdingRisks.map((item) => (
                      <div key={item.symbol} className="rounded-lg border border-danger/20 bg-danger/10 p-3">
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="font-medium text-foreground">{item.name}</span>
                          <span className={signedClass(item.changePct)}>{formatPercent(item.changePct)}</span>
                        </div>
                        <RiskTags className="mt-2" status={item.statusTag} risks={item.riskTags} />
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card className="rounded-lg" padding="sm">
                <div className="mb-3 flex items-center gap-2">
                  <Target className="h-4 w-4 text-cyan" />
                  <h3 className="text-base font-semibold text-foreground">明日观察清单</h3>
                </div>
                {data.nextDayWatchlist.length === 0 ? (
                  <p className="text-sm leading-6 text-secondary-text">暂无等待确认标的。</p>
                ) : (
                  <div className="space-y-3">
                    {data.nextDayWatchlist.map((item) => (
                      <div key={item.symbol} className="rounded-lg border border-border/60 bg-card/60 p-3">
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="font-medium text-foreground">{item.name}</span>
                          <RiskTags status={item.statusTag} watches={item.watchTags} />
                        </div>
                        <div className="mt-2 space-y-1 text-xs leading-5 text-secondary-text">
                          {item.nextDayWatch.slice(0, 2).map((watch) => <p key={watch}>- {watch}</p>)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <Card className="rounded-lg" padding="md">
              <p className="label-uppercase">AI 总结</p>
              <p className="mt-2 text-sm leading-7 text-secondary-text">{data.aiSummary}</p>
            </Card>
            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-foreground">Markdown 预览</h3>
                <span className="text-xs text-secondary-text">{data.markdown.length} 字符</span>
              </div>
              <pre className="max-h-[420px] overflow-auto rounded-lg border border-border/60 bg-muted/40 p-3 text-xs leading-6 text-secondary-text whitespace-pre-wrap">{data.markdown}</pre>
            </Card>
          </section>
        </>
      ) : null}
    </AppPage>
  );
};

export default WorkbenchDailyReviewPage;
