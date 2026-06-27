import type React from 'react';
import { useEffect, useMemo, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { EmptyState } from '../common';
import type { FundNavPoint } from '../../types/workbench';
import { echarts } from './echartsSetup';

type FundNavChartProps = {
  data: FundNavPoint[];
  title?: string;
  height?: number;
};

export const FundNavChart: React.FC<FundNavChartProps> = ({ data, title = '基金净值走势', height = 360 }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((item) => item.date);
    return {
      animation: false,
      title: { text: title, left: 8, top: 4, textStyle: { fontSize: 14, color: '#64748b' } },
      tooltip: { trigger: 'axis' },
      legend: { top: 4, right: 8, textStyle: { color: '#64748b' } },
      grid: { left: 52, right: 24, top: 48, bottom: 48 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#64748b' }, axisTick: { show: false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.18)' } } },
      dataZoom: [
        { type: 'inside', start: Math.max(0, 100 - Math.min(90, data.length)), end: 100 },
        { type: 'slider', bottom: 8, height: 18, start: Math.max(0, 100 - Math.min(90, data.length)), end: 100 },
      ],
      series: [
        {
          name: '单位净值',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: data.map((item) => item.nav),
          lineStyle: { width: 1.8, color: '#0ea5e9' },
          areaStyle: { color: 'rgba(14, 165, 233, 0.08)' },
        },
        {
          name: '累计净值',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: data.map((item) => item.accNav),
          lineStyle: { width: 1.2, color: '#f59e0b' },
        },
      ],
    } as EChartsOption;
  }, [data, title]);

  useEffect(() => {
    if (!ref.current || data.length === 0) return undefined;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [data.length, option]);

  if (data.length === 0) {
    return <EmptyState title="暂无基金净值" description="场外基金接口异常时不会影响股票复盘页。" />;
  }

  return <div ref={ref} className="w-full" style={{ height }} aria-label={title} />;
};
