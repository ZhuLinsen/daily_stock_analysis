import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { sentimentReviewApi } from '../api/sentimentReview';
import { Card, EmptyState, PageHeader } from '../components/common';
import { SentimentTrendDrawer } from '../components/sentiment-review/SentimentTrendDrawer';
import type { SentimentReviewDate, SentimentReviewDetail } from '../types/sentimentReview';

type Metric = { title: string; value: string; paths: Array<{ path: string; label: string }> };
const percent = (value?: number | null) => value == null ? '--' : `${(value * 100).toFixed(1)}%`;
const number = (value?: number | null) => value == null ? '--' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const SentimentReviewPage: React.FC = () => {
  const [dates, setDates] = useState<SentimentReviewDate[]>([]);
  const [selectedDate, setSelectedDate] = useState('');
  const [detail, setDetail] = useState<SentimentReviewDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [trend, setTrend] = useState<Metric | null>(null);
  const [error, setError] = useState('');
  const loadDates = useCallback(async () => {
    const rows = await sentimentReviewApi.dates(); setDates(rows);
    setSelectedDate(current => current || rows[0]?.tradeDate || '');
  }, []);
  useEffect(() => { void loadDates().catch(err => setError(String(err))); }, [loadDates]);
  useEffect(() => { if (selectedDate) void sentimentReviewApi.detail(selectedDate).then(setDetail).catch(err => setError(String(err))); }, [selectedDate]);
  const run = async () => {
    setRunning(true); setError('');
    try { const result = await sentimentReviewApi.run(); await loadDates(); setSelectedDate(result.tradeDate); }
    catch (err) { setError(String(err)); } finally { setRunning(false); }
  };
  const p = detail?.payload;
  const metrics = useMemo<Metric[]>(() => [
    { title: '涨跌家数差', value: number(p?.breadth?.delta), paths: [{ path: 'breadth.delta', label: '涨跌家数差' }] },
    { title: '最高板', value: number(p?.boards?.highest), paths: [{ path: 'boards.highest', label: '最高板' }] },
    { title: '炸板率', value: percent(p?.boards?.brokenRate), paths: [{ path: 'boards.broken_rate', label: '炸板率' }] },
    { title: '连板晋级率', value: percent(p?.boards?.promotionRates?.second), paths: [
      { path: 'boards.promotion_rates.second', label: '2板晋级' }, { path: 'boards.promotion_rates.third', label: '3板晋级' }, { path: 'boards.promotion_rates.fourth_plus', label: '4板及以上' },
    ] },
    { title: '昨日涨停今日表现', value: percent(p?.nextDayFeedback?.closeMedian), paths: [{ path: 'next_day_feedback.close_median', label: '收盘中位数' }] },
    { title: '昨日涨停竞价表现', value: percent(p?.nextDayFeedback?.auctionMedian), paths: [{ path: 'next_day_feedback.auction_median', label: '竞价中位数' }] },
  ], [p]);
  return <div className="space-y-6">
    <PageHeader eyebrow="POST-CLOSE" title="每日情绪复盘" description="指标由固定规则计算；LLM 仅生成行情分析与次日观察方向。" actions={<>
      <select className="input-surface h-10 rounded-xl border px-3" value={selectedDate} onChange={event => setSelectedDate(event.target.value)}><option value="">选择日期</option>{dates.map(row => <option key={row.tradeDate}>{row.tradeDate}</option>)}</select>
      <button className="btn-primary" disabled={running} onClick={() => void run()}><RefreshCw className={`mr-2 h-4 w-4 ${running ? 'animate-spin' : ''}`} />{running ? '计算中' : '启动今日复盘'}</button>
    </>} />
    {error ? <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-500">{error}</div> : null}
    {!detail ? <EmptyState title="暂无复盘记录" description="收盘后点击启动按钮生成当日复盘。" /> : <>
      <div className="flex items-center gap-3 text-sm"><span>{detail.tradeDate}</span><span className="rounded-full bg-primary/10 px-3 py-1 text-primary">{detail.dataQuality}</span><span>情绪状态：{p?.emotionState || '样本不足'}</span></div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{metrics.map(metric => <button key={metric.title} className="text-left" onClick={() => setTrend(metric)}><Card hoverable title={metric.title}><p className="text-3xl font-semibold">{metric.value}</p><p className="mt-2 text-xs text-secondary-text">点击查看 10/30/60 日曲线</p></Card></button>)}</div>
      <div className="grid gap-4 lg:grid-cols-2"><Card title="行情分析"><p className="whitespace-pre-wrap text-sm leading-7">{detail.narrative.analysis || 'LLM 总结尚未生成，规则指标不受影响。'}</p></Card><Card title="次日观察方向"><p className="whitespace-pre-wrap text-sm leading-7">{detail.narrative.nextDayWatch || '--'}</p>{detail.narrative.riskNotes ? <p className="mt-4 border-t border-border pt-4 text-sm text-secondary-text">风险：{detail.narrative.riskNotes}</p> : null}</Card></div>
      <Card title="题材强度"><div className="flex flex-wrap gap-2">{(p?.themes || []).map(item => <span key={item.name} className="rounded-full border border-border px-3 py-1 text-sm">{item.name} · {item.limitUpCount}</span>)}</div></Card>
    </>}
    <SentimentTrendDrawer metric={trend} onClose={() => setTrend(null)} />
  </div>;
};
export default SentimentReviewPage;
