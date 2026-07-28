import { AlertTriangle, ExternalLink, Newspaper, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { personalNewsApi, type PersonalNewsItem, type ProviderStatus, type RefreshStatus, type WatchlistItem } from '../api/personalNews';

const formatTime = (value: string | null) => value ? new Date(value).toLocaleString() : '时间未知';

const directionTone: Record<string, string> = {
  POSITIVE: 'text-emerald-400',
  NEGATIVE: 'text-rose-400',
  MIXED: 'text-amber-400',
  UNCERTAIN: 'text-secondary-text',
};

const actionLabels: Record<string, string> = {
  WATCH_NOW: '重点关注',
  WAIT_FOR_CONFIRMATION: '等待确认',
  RISK_ALERT: '风险预警',
  AVOID_CHASING: '避免追高',
  POTENTIAL_OPPORTUNITY: '潜在机会',
  NO_ACTION: '暂无操作',
  INSUFFICIENT_EVIDENCE: '证据不足',
};

const PAGE_OPEN_REFRESH_KEY = 'personal-news-page-open-refreshed';

const NewsPage = () => {
  const [items, setItems] = useState<PersonalNewsItem[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [symbolsInput, setSymbolsInput] = useState('');
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshError, setRefreshError] = useState('');

  const load = async () => {
    setLoading(true);
    const [newsResult, providersResult, watchlistResult] = await Promise.allSettled([
      personalNewsApi.list(),
      personalNewsApi.providers(),
      personalNewsApi.watchlist(),
    ]);
    if (newsResult.status === 'fulfilled') {
      setItems(newsResult.value);
      setError('');
    } else {
      setError('历史资讯加载失败；若已安装 PWA，仍可查看最近缓存。');
    }
    if (providersResult.status === 'fulfilled') setProviders(providersResult.value);
    if (watchlistResult.status === 'fulfilled') setWatchlist(watchlistResult.value);
    setLoading(false);
  };

  const followRefresh = async (initial: RefreshStatus) => {
    setRefreshStatus(initial);
    if (!['started', 'running'].includes(initial.status)) {
      if (initial.status === 'failed') setRefreshError(initial.error || '刷新失败');
      return;
    }
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const status = await personalNewsApi.refreshStatus();
      setRefreshStatus(status);
      if (!['started', 'running'].includes(status.status)) {
        if (status.status === 'failed') setRefreshError(status.error || '刷新失败');
        await load();
        return;
      }
    }
    setRefreshError('刷新仍在后台运行，请稍后手动刷新页面状态。');
  };

  const startRefresh = async (trigger: 'page_open' | 'manual') => {
    setRefreshError('');
    try {
      await followRefresh(await personalNewsApi.refresh(trigger));
    } catch (reason) {
      setRefreshError(reason instanceof Error ? reason.message : '刷新请求失败');
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().then(async () => {
        if (!sessionStorage.getItem(PAGE_OPEN_REFRESH_KEY)) {
          sessionStorage.setItem(PAGE_OPEN_REFRESH_KEY, '1');
          await startRefresh('page_open');
        } else {
          try { setRefreshStatus(await personalNewsApi.refreshStatus()); } catch { /* history remains usable */ }
        }
      });
    }, 0);
    return () => window.clearTimeout(timer);
    // This is deliberately a once-per-mount bootstrap; page-open deduplication is in sessionStorage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addSymbols = async () => {
    if (!symbolsInput.trim()) return;
    setRefreshError('');
    try {
      const result = await personalNewsApi.addWatchlist(symbolsInput);
      setWatchlist(result.items);
      setSymbolsInput('');
      if (result.refresh) await followRefresh(result.refresh);
    } catch (reason) {
      setRefreshError(reason instanceof Error ? reason.message : '自选股添加失败');
    }
  };

  const deleteSymbol = async (symbol: string) => {
    try {
      setWatchlist(await personalNewsApi.deleteWatchlist(symbol));
    } catch (reason) {
      setRefreshError(reason instanceof Error ? reason.message : '自选股删除失败');
    }
  };

  const newIds = new Set(refreshStatus?.newArticleIds || []);
  const newImportant = items.filter((item) => newIds.has(item.id) && item.importanceScore >= 60);
  const history = items.filter((item) => !newIds.has(item.id));
  const latestAnalyses = items.filter((item) => item.analysis).slice(0, 5);
  const isRefreshing = ['started', 'running'].includes(refreshStatus?.status || '');

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 px-1 pb-8">
      <section className="rounded-2xl border border-cyan-500/25 bg-card/70 p-4 shadow-soft-card sm:p-6">
        <h1 className="text-xl font-semibold text-foreground">自选股管理</h1>
        <p className="mt-1 text-sm text-secondary-text">输入单只或批量粘贴；支持逗号、空格和换行。示例：600519、00700、NVDA。</p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <textarea
            value={symbolsInput}
            onChange={(event) => setSymbolsInput(event.target.value)}
            placeholder={'600519, 300750\n00700 NVDA AAPL'}
            className="min-h-24 flex-1 rounded-xl border border-border bg-background/60 px-4 py-3 text-sm text-foreground outline-none transition focus:border-cyan-500"
          />
          <button type="button" onClick={() => void addSymbols()} className="btn-primary inline-flex items-center justify-center gap-2 self-stretch sm:self-end">
            <Plus className="h-4 w-4" />添加并检查
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {watchlist.map((item) => (
            <span key={item.symbol} className="inline-flex items-center gap-2 rounded-full border border-border bg-background/50 px-3 py-1.5 text-sm">
              <span className="font-medium text-foreground">{item.name}</span><span className="text-cyan-300">{item.symbol}</span>
              <button type="button" onClick={() => void deleteSymbol(item.symbol)} aria-label={`删除 ${item.symbol}`} className="text-secondary-text hover:text-rose-300"><Trash2 className="h-3.5 w-3.5" /></button>
            </span>
          ))}
          {!loading && watchlist.length === 0 && <span className="text-sm text-secondary-text">尚未添加股票，请从上方输入开始。</span>}
        </div>
      </section>

      <section className="rounded-2xl border border-border/70 bg-card/70 p-4 shadow-soft-card sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-400">Personal radar</p>
            <h1 className="mt-1 text-2xl font-semibold text-foreground">重要股票新闻</h1>
            <p className="mt-1 text-sm text-secondary-text">08:00 与 20:00（Asia/Shanghai）自动检查；页面打开也会在冷却允许时异步刷新。</p>
          </div>
          <button type="button" onClick={() => void startRefresh('manual')} className="btn-secondary inline-flex items-center gap-2" disabled={isRefreshing || watchlist.length === 0}>
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />立即刷新
          </button>
        </div>
        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
          <StatusCard label="当前任务状态" value={isRefreshing ? '正在检查最新资讯' : refreshStatus?.status || '等待刷新'} />
          <StatusCard label="最后检查时间" value={formatTime(refreshStatus?.lastRefreshAt || null)} />
          <StatusCard label="本轮新增" value={`${refreshStatus?.stats?.new || 0} 条`} />
        </div>
      </section>

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">{error}</div>}
      {refreshError && <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">{refreshError}；历史缓存仍可继续查看。</div>}

      <section className="rounded-2xl border border-border/70 bg-card/70 p-5">
        <h2 className="text-lg font-semibold text-foreground">最新 AI 综合观察</h2>
        {latestAnalyses.length > 0 ? (
          <ul className="mt-3 space-y-2 text-sm leading-6 text-secondary-text">
            {latestAnalyses.map((item) => <li key={item.id}><span className="font-medium text-cyan-300">{item.symbols.join(', ')}</span>：{item.analysis?.summary}</li>)}
          </ul>
        ) : <p className="mt-3 text-sm text-secondary-text">暂无已验证分析。添加自选股并刷新后，这里会保留最近一次观察。</p>}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-foreground">新的重要资讯</h2>
        {!isRefreshing && newImportant.length === 0 && <div className="rounded-xl border border-border/70 bg-card/50 p-5 text-sm text-secondary-text">暂无新的重要资讯，下面仍保留历史分析。</div>}
        <NewsGrid items={newImportant} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-foreground">历史资讯列表</h2>
        {!loading && items.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border p-10 text-center text-secondary-text">
            <Newspaper className="mx-auto mb-3 h-8 w-8" />还没有历史资讯。请先在页面顶部添加股票，然后点击“立即刷新”。
          </div>
        )}
        <NewsGrid items={history} />
      </section>

      <section className="rounded-2xl border border-border/70 bg-card/70 p-5">
        <h2 className="text-lg font-semibold text-foreground">数据源状态</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {providers.map((provider) => <span key={provider.provider} className="rounded-full border border-border/70 bg-background/50 px-3 py-1 text-xs text-secondary-text">{provider.provider} · {provider.status}</span>)}
          {providers.length === 0 && <span className="text-sm text-secondary-text">尚无状态记录；只配置博查也可以启动。</span>}
        </div>
      </section>
    </div>
  );
};

const StatusCard = ({ label, value }: { label: string; value: string }) => <div className="rounded-xl bg-background/45 p-3"><p className="text-xs text-secondary-text">{label}</p><p className="mt-1 font-medium text-foreground">{value}</p></div>;

const NewsGrid = ({ items }: { items: PersonalNewsItem[] }) => (
  <div className="grid gap-4 md:grid-cols-2">
    {items.map((item) => (
      <Link key={item.id} to={`/news/${item.id}`} className="group rounded-2xl border border-border/70 bg-card/70 p-5 shadow-soft-card transition hover:-translate-y-0.5 hover:border-cyan-500/50">
        <div className="flex items-start justify-between gap-3"><div className="flex flex-wrap gap-2">{item.symbols.map((symbol) => <span key={symbol} className="rounded-md bg-cyan-500/10 px-2 py-1 text-xs font-semibold text-cyan-300">{symbol}</span>)}{item.isAnnouncement && <span className="rounded-md bg-violet-500/10 px-2 py-1 text-xs text-violet-300">公告</span>}</div><span className={`rounded-full px-2.5 py-1 text-sm font-bold ${item.importanceScore >= 75 ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-500/15 text-amber-300'}`}>{item.importanceScore}</span></div>
        <h3 className="mt-4 line-clamp-2 text-base font-semibold leading-6 text-foreground group-hover:text-cyan-300">{item.title}</h3>
        <p className="mt-2 line-clamp-3 text-sm leading-6 text-secondary-text">{item.analysis?.summary || item.summary || '等待结构化分析'}</p>
        <div className="mt-4 flex items-center justify-between text-xs text-secondary-text"><span>{item.source} · {formatTime(item.publishedAt)}</span><span className={directionTone[item.analysis?.direction || 'UNCERTAIN']}>{item.analysis?.action ? actionLabels[item.analysis.action] : item.analysisStatus}</span></div>
      </Link>
    ))}
  </div>
);

export const NewsDetailPage = ({ newsId }: { newsId: string }) => {
  const [item, setItem] = useState<PersonalNewsItem | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    void personalNewsApi.get(newsId).then(setItem).catch((reason) => setError(reason instanceof Error ? reason.message : '新闻加载失败'));
  }, [newsId]);

  if (error) return <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-rose-300">{error}</div>;
  if (!item) return <div className="p-8 text-center text-secondary-text">正在加载...</div>;
  const analysis = item.analysis;
  return (
    <article className="mx-auto w-full max-w-4xl space-y-5 pb-10">
      <Link to="/news" className="text-sm text-cyan-400 hover:underline">← 返回新闻列表</Link>
      <header className="rounded-2xl border border-border/70 bg-card/70 p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-2 text-xs text-secondary-text">
          <span>{item.source}</span><span>·</span><span>{formatTime(item.publishedAt)}</span><span>·</span><span>数据更新 {formatTime(item.fetchedAt)}</span>
        </div>
        <h1 className="mt-3 text-2xl font-semibold leading-tight text-foreground sm:text-3xl">{item.title}</h1>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="rounded-full bg-rose-500/15 px-3 py-1 text-sm font-semibold text-rose-300">重要性 {item.importanceScore}</span>
          {item.symbols.map((symbol) => <span key={symbol} className="rounded-full bg-cyan-500/10 px-3 py-1 text-sm text-cyan-300">{symbol}</span>)}
        </div>
      </header>
      <section className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-border/70 bg-card/70 p-5"><h2 className="font-semibold text-foreground">原始摘要</h2><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-secondary-text">{item.summary || '无摘要'}</p></div>
        <div className="rounded-2xl border border-border/70 bg-card/70 p-5"><h2 className="font-semibold text-foreground">评分依据</h2><ul className="mt-3 space-y-2 text-sm text-secondary-text">{item.scoreReasons.map((reason) => <li key={reason}>· {reason}</li>)}</ul></div>
      </section>
      {analysis ? (
        <section className="space-y-4 rounded-2xl border border-cyan-500/20 bg-card/70 p-5 sm:p-7">
          <div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-cyan-400" /><h2 className="text-lg font-semibold text-foreground">AI 结构化分析</h2></div>
          <p className="leading-7 text-secondary-text">{analysis.summary}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Factor title="正面因素" items={analysis.positiveFactors} tone="text-emerald-300" />
            <Factor title="负面因素" items={analysis.negativeFactors} tone="text-rose-300" />
          </div>
          <Factor title="主要风险" items={analysis.risks} tone="text-amber-300" icon={<AlertTriangle className="h-4 w-4" />} />
          <Factor title="失效条件" items={analysis.invalidationConditions} tone="text-violet-300" />
          <div className="rounded-xl bg-background/50 p-4 text-sm"><strong className="text-foreground">观察策略：{actionLabels[analysis.action] || analysis.action}</strong><p className="mt-2 text-secondary-text">{analysis.actionReason}</p></div>
        </section>
      ) : <div className="rounded-xl border border-border p-5 text-secondary-text">分析状态：{item.analysisStatus}</div>}
      <a href={item.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm text-cyan-400 hover:underline">查看原始来源 <ExternalLink className="h-4 w-4" /></a>
    </article>
  );
};

const Factor = ({ title, items, tone, icon }: { title: string; items: string[]; tone: string; icon?: React.ReactNode }) => (
  <div className="rounded-xl border border-border/60 bg-background/40 p-4">
    <h3 className={`flex items-center gap-2 text-sm font-semibold ${tone}`}>{icon}{title}</h3>
    <ul className="mt-3 space-y-2 text-sm leading-6 text-secondary-text">{items.map((item) => <li key={item}>· {item}</li>)}</ul>
  </div>
);

export default NewsPage;
