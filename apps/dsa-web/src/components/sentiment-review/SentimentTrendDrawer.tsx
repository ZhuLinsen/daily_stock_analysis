import type React from 'react';
import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { sentimentReviewApi } from '../../api/sentimentReview';

type Metric = { title: string; paths: Array<{ path: string; label: string }> };

export const SentimentTrendDrawer: React.FC<{ metric: Metric | null; onClose: () => void }> = ({ metric, onClose }) => {
  const [windowSize, setWindowSize] = useState(30);
  const [data, setData] = useState<Array<Record<string, string | number | null>>>([]);
  useEffect(() => {
    if (!metric) return;
    void Promise.all(metric.paths.map(item => sentimentReviewApi.trend(item.path, windowSize))).then(series => {
      const byDate = new Map<string, Record<string, string | number | null>>();
      series.forEach((points, index) => points.forEach(point => {
        const row = byDate.get(point.tradeDate) || { tradeDate: point.tradeDate };
        row[metric.paths[index].label] = point.value;
        byDate.set(point.tradeDate, row);
      }));
      setData([...byDate.values()].sort((a, b) => String(a.tradeDate).localeCompare(String(b.tradeDate))));
    });
  }, [metric, windowSize]);
  if (!metric) return null;
  const colors = ['#38bdf8', '#f59e0b', '#f43f5e'];
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
    <aside className="h-full w-full max-w-3xl bg-background p-6 shadow-2xl" onClick={event => event.stopPropagation()}>
      <div className="mb-6 flex items-center justify-between">
        <div><h2 className="text-xl font-semibold">{metric.title} · 历史变化</h2><p className="text-sm text-secondary-text">缺失数据保留为空，不按 0 填充</p></div>
        <button className="rounded-xl p-2 hover:bg-hover" onClick={onClose}><X /></button>
      </div>
      <div className="mb-4 flex gap-2">{[10, 30, 60].map(value => <button key={value} className={windowSize === value ? 'btn-primary' : 'btn-secondary'} onClick={() => setWindowSize(value)}>{value}日</button>)}</div>
      <div className="h-[420px] rounded-2xl border border-border p-4">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.25} /><XAxis dataKey="tradeDate" minTickGap={24} /><YAxis /><Tooltip /><Legend />
          {metric.paths.map((item, index) => <Line key={item.path} type="monotone" dataKey={item.label} stroke={colors[index]} connectNulls={false} strokeWidth={2} dot={false} />)}
        </LineChart></ResponsiveContainer>
      </div>
    </aside>
  </div>;
};
