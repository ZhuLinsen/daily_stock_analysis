import { AlertTriangle, ExternalLink, Newspaper, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { personalNewsApi, type PersonalNewsItem, type ProviderStatus } from '../api/personalNews';

const formatTime = (value: string | null) => value ? new Date(value).toLocaleString() : '时间未知';

const directionTone: Record<string, string> = {
  POSITIVE: 'text-emerald-400',
  NEGATIVE: 'text-rose-400',
  MIXED: 'text-amber-400',
  UNCERTAIN: 'text-secondary-text',
};

const NewsPage = () => {
  const [items, setItems] = useState<PersonalNewsItem[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [news, status] = await Promise.all([personalNewsApi.list(), personalNewsApi.providers()]);
      setItems(news);
      setProviders(status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '新闻加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 px-1 pb-8">
      <section className="rounded-2xl border border-border/70 bg-card/70 p-4 shadow-soft-card sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-400">Personal radar</p>
            <h1 className="mt-1 text-2xl font-semibold text-foreground">重要股票新闻</h1>
            <p className="mt-1 text-sm text-secondary-text">规则先评分，达到阈值后才调用 AI；内容仅供观察，不构成投资建议。</p>
          </div>
          <button type="button" onClick={() => void load()} className="btn-secondary inline-flex items-center gap-2" disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新
          </button>
        </div>
        {providers.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {providers.map((provider) => (
              <span key={provider.provider} className="rounded-full border border-border/70 bg-background/50 px-3 py-1 text-xs text-secondary-text">
                {provider.provider} · {provider.status}
              </span>
            ))}
          </div>
        )}
      </section>

      {error && <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">{error}</div>}
      {!loading && items.length === 0 && (
        <div className="rounded-2xl border border-dashed border-border p-10 text-center text-secondary-text">
          <Newspaper className="mx-auto mb-3 h-8 w-8" />暂无新闻，启动 <code>python main.py --news-watch</code> 后会自动轮询。
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((item) => (
          <Link key={item.id} to={`/news/${item.id}`} className="group rounded-2xl border border-border/70 bg-card/70 p-5 shadow-soft-card transition hover:-translate-y-0.5 hover:border-cyan-500/50">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {item.symbols.map((symbol) => <span key={symbol} className="rounded-md bg-cyan-500/10 px-2 py-1 text-xs font-semibold text-cyan-300">{symbol}</span>)}
                {item.isAnnouncement && <span className="rounded-md bg-violet-500/10 px-2 py-1 text-xs text-violet-300">公告</span>}
              </div>
              <span className={`rounded-full px-2.5 py-1 text-sm font-bold ${item.importanceScore >= 75 ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-500/15 text-amber-300'}`}>{item.importanceScore}</span>
            </div>
            <h2 className="mt-4 line-clamp-2 text-base font-semibold leading-6 text-foreground group-hover:text-cyan-300">{item.title}</h2>
            <p className="mt-2 line-clamp-3 text-sm leading-6 text-secondary-text">{item.analysis?.summary || item.summary || '等待结构化分析'}</p>
            <div className="mt-4 flex items-center justify-between text-xs text-secondary-text">
              <span>{item.source} · {formatTime(item.publishedAt)}</span>
              <span className={directionTone[item.analysis?.direction || 'UNCERTAIN']}>{item.analysis?.direction || item.analysisStatus}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
};

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
          <div className="rounded-xl bg-background/50 p-4 text-sm"><strong className="text-foreground">建议动作：{analysis.action}</strong><p className="mt-2 text-secondary-text">{analysis.actionReason}</p></div>
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
