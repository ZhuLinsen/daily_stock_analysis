import type React from 'react';
import { useEffect, useMemo, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { EmptyState } from '../common';
import type { MoneyFlowData } from '../../types/workbench';
import { echarts } from './echartsSetup';

type MoneyFlowChartProps = {
  data?: MoneyFlowData | null;
  height?: number;
};

const toYi = (value?: number | null): number => {
  if (value === null || value === undefined || Number.isNaN(value)) return 0;
  return Math.round((Number(value) / 100000000) * 100) / 100;
};

export const MoneyFlowChart: React.FC<MoneyFlowChartProps> = ({ data, height = 260 }) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const values = useMemo(() => {
    const stockFlow = data?.stockFlow ?? {};
    return [
      { name: '今日主力', value: toYi(stockFlow.mainNetInflow) },
      { name: '5日累计', value: toYi(stockFlow.inflow5d) },
      { name: '10日累计', value: toYi(stockFlow.inflow10d) },
    ];
  }, [data]);

  const hasData = values.some((item) => item.value !== 0);

  const option = useMemo<EChartsOption>(() => ({
    animation: false,
    grid: { left: 52, right: 18, top: 24, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => `${value}亿`,
    },
    xAxis: {
      type: 'category',
      data: values.map((item) => item.name),
      axisTick: { show: false },
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value',
      name: '亿元',
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.18)' } },
    },
    series: [{
      name: '资金净流入',
      type: 'bar',
      data: values.map((item) => ({
        value: item.value,
        itemStyle: { color: item.value >= 0 ? '#ef4444' : '#10b981' },
      })),
      barWidth: 38,
    }],
  }), [values]);

  useEffect(() => {
    if (!ref.current || !hasData) return undefined;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.dispose();
    };
  }, [hasData, option]);

  if (!hasData) {
    return <EmptyState title="暂无资金流数据" description="接口异常时页面仍会展示行情、K线和 AI 评分。" className="py-8" />;
  }

  return <div ref={ref} className="w-full" style={{ height }} aria-label="资金流图表" />;
};
