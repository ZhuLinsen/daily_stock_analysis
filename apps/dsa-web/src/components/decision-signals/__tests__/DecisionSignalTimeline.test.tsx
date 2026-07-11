import type React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { DecisionSignalItem } from '../../../types/decisionSignals';
import {
  ACTION_RANK,
  buildTimelineData,
  getTimelinePointStyle,
  sortDecisionSignalTimelineItems,
} from '../../../utils/decisionSignalTimeline';
import {
  DecisionSignalTimeline,
} from '../DecisionSignalTimeline';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ScatterChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Scatter: ({
    data,
    onClick,
    shape,
  }: {
    data: Array<{ item: DecisionSignalItem; radius: number; strokeWidth: number }>;
    onClick: (datum: { item: DecisionSignalItem }) => void;
    shape: (props: unknown) => React.ReactNode;
  }) => (
    <div>
      {data.map((datum, index) => (
        <button
          key={datum.item.id}
          type="button"
          data-testid={`timeline-click-${datum.item.id}`}
          onClick={() => onClick(datum)}
        >
          {shape({ cx: 20 + index * 20, cy: 20, payload: datum })}
          {datum.item.stockCode}
        </button>
      ))}
    </div>
  ),
}));

const baseSignal: DecisionSignalItem = {
  id: 1,
  stockCode: '600519',
  stockName: '贵州茅台',
  market: 'cn',
  sourceType: 'analysis',
  sourceReportId: 3001,
  triggerSource: 'web',
  action: 'watch',
  confidence: 0.5,
  score: 50,
  horizon: '3d',
  planQuality: 'complete',
  status: 'active',
  createdAt: '2026-06-17T09:30:00',
  metadata: { decision_profile: 'balanced' },
};

function makeSignal(overrides: Partial<DecisionSignalItem>): DecisionSignalItem {
  return {
    ...baseSignal,
    ...overrides,
  };
}

function renderTimeline(props: Partial<React.ComponentProps<typeof DecisionSignalTimeline>> = {}) {
  window.localStorage.setItem('dsa.uiLanguage', 'zh');
  const onSelect = props.onSelect ?? vi.fn();
  render(
    <UiLanguageProvider>
      <DecisionSignalTimeline
        items={[baseSignal]}
        onSelect={onSelect}
        {...props}
      />
    </UiLanguageProvider>,
  );
  return { onSelect };
}

describe('DecisionSignalTimeline helpers', () => {
  it('keeps the issue action rank mapping stable', () => {
    expect(ACTION_RANK).toEqual({
      sell: -3,
      reduce: -2,
      avoid: -1,
      watch: 0,
      alert: 0,
      hold: 1,
      add: 2,
      buy: 3,
    });
  });

  it('sorts by createdAt ascending and places invalid dates last', () => {
    const sorted = sortDecisionSignalTimelineItems([
      makeSignal({ id: 1, createdAt: 'bad-date' }),
      makeSignal({ id: 2, createdAt: '2026-06-18T09:30:00' }),
      makeSignal({ id: 3, createdAt: '2026-06-17T09:30:00' }),
    ]);

    expect(sorted.map((item) => item.id)).toEqual([3, 2, 1]);
  });

  it('uses different visual styles for alert and watch at the same rank', () => {
    const watch = getTimelinePointStyle(makeSignal({ action: 'watch' }));
    const alert = getTimelinePointStyle(makeSignal({ action: 'alert' }));

    expect(watch.rank).toBe(0);
    expect(alert.rank).toBe(0);
    expect(watch.shape).toBe('circle');
    expect(alert.shape).toBe('diamond');
  });

  it('clamps invalid score and confidence values without NaN geometry', () => {
    const missing = getTimelinePointStyle(makeSignal({ score: Number.NaN, confidence: Number.NaN }));
    const clamped = getTimelinePointStyle(makeSignal({ score: 150, confidence: 2 }));

    expect(Number.isFinite(missing.radius)).toBe(true);
    expect(Number.isFinite(missing.strokeWidth)).toBe(true);
    expect(clamped.radius).toBeGreaterThanOrEqual(missing.radius);
    expect(clamped.strokeWidth).toBeGreaterThan(missing.strokeWidth);
  });

  it('marks terminal status as muted timeline data', () => {
    const [datum] = buildTimelineData([makeSignal({ status: 'closed' })], Date.UTC(2026, 5, 20));

    expect(datum.terminal).toBe(true);
    expect(datum.fill).toBe('#8a9099');
    expect(datum.statusDasharray).toBe('8 3');
  });
});

describe('DecisionSignalTimeline', () => {
  it('shows truncated warning and opens a selected point', () => {
    const { onSelect } = renderTimeline({ truncated: true });

    expect(screen.getByText('仅展示最近 100 条信号，请缩小时间范围。')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('timeline-click-1'));

    expect(onSelect).toHaveBeenCalledWith(baseSignal);
  });

  it('renders empty and error states', () => {
    const { rerender } = render(
      <UiLanguageProvider>
        <DecisionSignalTimeline items={[]} onSelect={vi.fn()} />
      </UiLanguageProvider>,
    );

    expect(screen.getByText('暂无时间线信号')).toBeInTheDocument();

    rerender(
      <UiLanguageProvider>
        <DecisionSignalTimeline items={[]} error="timeline failed" onSelect={vi.fn()} />
      </UiLanguageProvider>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('timeline failed');
  });
});
