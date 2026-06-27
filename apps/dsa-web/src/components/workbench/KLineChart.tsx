import type React from 'react';
import { useEffect, useMemo, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { EmptyState } from '../common';
import type { KLineBar } from '../../types/workbench';
import { echarts } from './echartsSetup';

type KLineChartProps = {
  data: KLineBar[];
  title?: string;
  height?: number;
};

function lineSeries(
  name: string,
  data: Array<number | null | undefined>,
  color: string,
  xAxisIndex = 0,
  yAxisIndex = 0,
) {
  return {
    name,
    type: 'line' as const,
    data,
    xAxisIndex,
    yAxisIndex,
    smooth: true,
    symbol: 'none',
    lineStyle: { width: 1.2, color },
  };
}

export const KLineChart: React.FC<KLineChartProps> = ({ data, title = 'K线图', height = 620 }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((item) => item.date);
    const candles = data.map((item) => [item.open, item.close, item.low, item.high]);
    const volume = data.map((item, index) => [index, item.volume ? Number(item.volume) / 10000 : 0, (item.close ?? 0) >= (item.open ?? 0) ? 1 : -1]);
    return {
      animation: false,
      color: ['#0ea5e9', '#f59e0b', '#8b5cf6', '#64748b'],
      title: { text: title, left: 8, top: 4, textStyle: { fontSize: 14, color: '#64748b' } },
      legend: { top: 4, right: 8, itemWidth: 10, selected: { 'BOLL上轨': false, 'BOLL中轨': false, 'BOLL下轨': false }, textStyle: { color: '#64748b' } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 50, right: 20, top: 42, height: '38%' },
        { left: 50, right: 20, top: '50%', height: '12%' },
        { left: 50, right: 20, top: '67%', height: '12%' },
        { left: 50, right: 20, top: '82%', height: '10%' },
      ],
      xAxis: [0, 1, 2, 3].map((gridIndex) => ({
        type: 'category',
        data: dates,
        gridIndex,
        boundaryGap: false,
        axisLine: { onZero: false },
        axisLabel: { show: gridIndex === 3, color: '#64748b' },
        axisTick: { show: false },
        splitLine: { show: false },
        min: 'dataMin',
        max: 'dataMax',
      })),
      yAxis: [0, 1, 2, 3].map((gridIndex) => ({
        scale: true,
        gridIndex,
        splitNumber: gridIndex === 0 ? 4 : 2,
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.18)' } },
      })),
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: Math.max(0, 100 - Math.min(80, data.length)), end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2, 3], bottom: 2, height: 18, start: Math.max(0, 100 - Math.min(80, data.length)), end: 100 },
      ],
      visualMap: {
        show: false,
        seriesIndex: 5,
        dimension: 2,
        pieces: [{ value: 1, color: '#ef4444' }, { value: -1, color: '#10b981' }],
      },
      series: [
        {
          name: '日K',
          type: 'candlestick' as const,
          data: candles,
          itemStyle: { color: '#ef4444', color0: '#10b981', borderColor: '#ef4444', borderColor0: '#10b981' },
        },
        lineSeries('MA5', data.map((item) => item.ma5), '#0ea5e9'),
        lineSeries('MA10', data.map((item) => item.ma10), '#f59e0b'),
        lineSeries('MA20', data.map((item) => item.ma20), '#8b5cf6'),
        lineSeries('MA60', data.map((item) => item.ma60), '#64748b'),
        { name: '成交量(万手)', type: 'bar' as const, xAxisIndex: 1, yAxisIndex: 1, data: volume },
        { name: 'MACD', type: 'bar' as const, xAxisIndex: 2, yAxisIndex: 2, data: data.map((item) => item.macd) },
        lineSeries('DIF', data.map((item) => item.macdDif), '#0ea5e9', 2, 2),
        lineSeries('DEA', data.map((item) => item.macdDea), '#f59e0b', 2, 2),
        lineSeries('KDJ-K', data.map((item) => item.kdjK), '#0ea5e9', 3, 3),
        lineSeries('KDJ-D', data.map((item) => item.kdjD), '#f59e0b', 3, 3),
        lineSeries('KDJ-J', data.map((item) => item.kdjJ), '#8b5cf6', 3, 3),
        lineSeries('RSI', data.map((item) => item.rsi), '#ef4444', 3, 3),
        { ...lineSeries('BOLL上轨', data.map((item) => item.bollUpper), '#94a3b8'), lineStyle: { width: 1, type: 'dashed' as const, color: '#94a3b8' } },
        { ...lineSeries('BOLL中轨', data.map((item) => item.bollMid), '#64748b'), lineStyle: { width: 1, type: 'dotted' as const, color: '#64748b' } },
        { ...lineSeries('BOLL下轨', data.map((item) => item.bollLower), '#94a3b8'), lineStyle: { width: 1, type: 'dashed' as const, color: '#94a3b8' } },
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
    return <EmptyState title="暂无K线数据" description="接口异常时会优先读取本地 SQLite 最近一次成功数据。" />;
  }

  return <div ref={ref} className="w-full" style={{ height }} aria-label={title} />;
};
