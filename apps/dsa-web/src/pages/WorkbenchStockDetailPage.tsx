import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink, RefreshCw, ShieldAlert, Target, TrendingUp } from 'lucide-react';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { workbenchApi } from '../api/workbench';
import { ApiErrorAlert, AppPage, Badge, Card, EmptyState, Loading, PageHeader, StatCard } from '../components/common';
import { AiScoreCard, KLineChart, MoneyFlowChart, RiskTags, WorkbenchDataNotice } from '../components/workbench';
import type { WorkbenchStockDetail } from '../types/workbench';
import { cn } from '../utils/cn';
import { formatAmountYi, formatNumber, formatPercent, signedClass } from '../components/workbench/format';

const fallbackSymbol = '600519.SH';

const WorkbenchStockDetailPage: React.FC = () => {
  const params = useParams<{ symbol: string }>();
  const symbol = params.symbol ? decodeURIComponent(params.symbol) : fallbackSymbol;
  const [data, setData] = useState<WorkbenchStockDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await workbenchApi.getStockDetail(symbol));
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    document.title = `${symbol} - 个股详情 - AI 股票复盘工作台`;
    void load();
  }, [load, symbol]);

  const quote = data?.quote;
  const analysis = data?.aiAnalysis;
  const concepts = data?.themes?.concepts ?? [];
  const industries = data?.themes?.industry ?? [];

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="STOCK DETAIL"
        title={data ? `${data.name || symbol} ${data.symbol}` : `个股详情 ${symbol}`}
        description="K线、均线、常用技术指标、资金流、题材归属和 AI 复盘结论集中展示。"
        actions={(
          <div className="flex flex-wrap gap-2">
            <Link to="/workbench/watchlist" className="btn-secondary inline-flex items-center gap-2"><ArrowLeft className="h-4 w-4" />自选股</Link>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />刷新
            </button>
          </div>
        )}
      />

      {error ? <ApiErrorAlert error={error} /> : null}
      {loading && !data ? <Loading label="加载个股详情..." /> : null}

      {data ? (
        <>
          <WorkbenchDataNotice stale={data.stale} error={data.error} source={data.source} />

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="最新价"
              value={<span className={signedClass(quote?.changePct)}>{formatNumber(quote?.price)}</span>}
              hint={`涨跌幅 ${formatPercent(quote?.changePct)}`}
              icon={<TrendingUp className="h-5 w-5" />}
              tone={quote?.changePct && quote.changePct > 0 ? 'danger' : quote?.changePct && quote.changePct < 0 ? 'success' : 'default'}
            />
            <StatCard label="成交额" value={formatAmountYi(quote?.amount)} hint={`换手率 ${formatPercent(quote?.turnoverRate)}`} />
            <StatCard label="振幅" value={formatPercent(quote?.amplitude)} hint={`量比 ${formatNumber(quote?.volumeRatio)}`} />
            <StatCard label="估值" value={`PE ${formatNumber(quote?.peRatio)}`} hint={`PB ${formatNumber(quote?.pbRatio)}`} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(360px,0.8fr)]">
            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-foreground">K线与技术指标</h3>
                  <p className="mt-1 text-xs text-secondary-text">包含成交量、MA5/10/20/60、MACD、KDJ、RSI、BOLL，可缩放查看。</p>
                </div>
                <Badge variant="info">日线</Badge>
              </div>
              <KLineChart data={data.kline ?? []} title={`${data.name || data.symbol} 日K`} />
            </Card>

            <div className="space-y-4">
              {analysis ? <AiScoreCard analysis={analysis} riskTags={data.riskTags} opportunityTags={data.opportunityTags} watchTags={data.watchTags} /> : null}
              <Card className="rounded-lg" padding="sm">
                <div className="mb-3 flex items-center gap-2">
                  <ShieldAlert className="h-4 w-4 text-danger" />
                  <h3 className="text-base font-semibold text-foreground">风险提示</h3>
                </div>
                <RiskTags risks={data.riskTags} opportunities={data.opportunityTags} watches={data.watchTags} />
                <div className="mt-3 space-y-2 text-sm leading-6 text-secondary-text">
                  {(analysis?.risks ?? []).map((item) => <p key={item}>- {item}</p>)}
                </div>
              </Card>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-foreground">资金流图表</h3>
                <span className="text-xs text-secondary-text">红色为净流入，绿色为净流出</span>
              </div>
              <MoneyFlowChart data={data.moneyFlow} />
            </Card>

            <Card className="rounded-lg" padding="sm">
              <h3 className="text-base font-semibold text-foreground">所属行业 / 概念</h3>
              <div className="mt-3 space-y-3">
                <div>
                  <p className="text-xs text-secondary-text">行业</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {industries.length > 0 ? industries.map((item) => <Badge key={item} variant="info">{item}</Badge>) : <span className="text-sm text-secondary-text">暂无行业归属</span>}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-secondary-text">概念</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {concepts.length > 0 ? concepts.slice(0, 12).map((item) => <Badge key={item} variant="default">{item}</Badge>) : <span className="text-sm text-secondary-text">暂无概念归属</span>}
                  </div>
                </div>
                <p className="rounded-lg border border-border/60 bg-muted/40 p-3 text-sm leading-6 text-secondary-text">
                  指标口径偏向复盘：行业和概念用于理解资金正在看什么，不等同于买卖依据。
                </p>
              </div>
            </Card>
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <Card className="rounded-lg" padding="sm">
              <div className="mb-3 flex items-center gap-2">
                <Target className="h-4 w-4 text-cyan" />
                <h3 className="text-base font-semibold text-foreground">明日观察位</h3>
              </div>
              <div className="space-y-2 text-sm leading-6 text-secondary-text">
                {(analysis?.nextDayWatch ?? []).map((item) => <p key={item}>- {item}</p>)}
                {analysis?.technical.support ? <p>- 支撑参考：{analysis.technical.support}</p> : null}
                {analysis?.technical.resistance ? <p>- 压力参考：{analysis.technical.resistance}</p> : null}
              </div>
            </Card>

            <Card className="rounded-lg" padding="sm">
              <h3 className="text-base font-semibold text-foreground">AI 分析报告</h3>
              <div className="mt-3 space-y-3 text-sm leading-7 text-secondary-text">
                <p>{analysis?.summary || '暂无 AI 分析摘要。'}</p>
                <p>{analysis?.technical.summary}</p>
                <p>{analysis?.capital.summary}</p>
                <p>{analysis?.sector.summary}</p>
              </div>
              <div className="mt-4 rounded-lg border border-border/60 bg-muted/40 p-3 text-sm text-secondary-text">
                操作参考：{analysis?.operationReference.action || '观察'} · 置信度 {analysis?.operationReference.confidence ?? '--'} · 失效条件：{analysis?.operationReference.invalidCondition || '放量下跌且资金继续流出'}
              </div>
              <p className="mt-3 text-xs text-secondary-text">{data.disclaimer}</p>
            </Card>
          </section>

          <Card className="rounded-lg" padding="sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-foreground">新闻 / 公告线索</h3>
              <span className="text-xs text-secondary-text">用于解释异动，不承诺方向</span>
            </div>
            {data.news.length === 0 ? (
              <EmptyState title="暂无新闻线索" className="py-8" />
            ) : (
              <div className="grid gap-2 md:grid-cols-2">
                {data.news.slice(0, 8).map((item) => (
                  <a
                    key={`${item.title}-${item.publishedAt ?? ''}`}
                    className="rounded-lg border border-border/60 bg-card/60 p-3 text-sm transition-colors hover:bg-hover"
                    href={item.url || '#'}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span className="flex items-start justify-between gap-2 text-foreground">
                      <span className="line-clamp-2">{item.title}</span>
                      {item.url ? <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-secondary-text" /> : null}
                    </span>
                    <span className="mt-2 block text-xs text-secondary-text">{item.source || '新闻'} {item.publishedAt || ''}</span>
                  </a>
                ))}
              </div>
            )}
          </Card>
        </>
      ) : null}
    </AppPage>
  );
};

export default WorkbenchStockDetailPage;
