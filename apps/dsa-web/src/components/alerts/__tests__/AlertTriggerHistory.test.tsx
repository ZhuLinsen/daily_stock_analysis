import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { AlertTriggerItem } from '../../../types/alerts';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { AlertTriggerHistory } from '../AlertTriggerHistory';

const sampleTriggers: AlertTriggerItem[] = [
  {
    id: 1,
    ruleId: 10,
    target: '600519',
    status: 'triggered',
    observedValue: 1805,
    threshold: 1800,
    dataSource: 'efinance',
    dataTimestamp: '2026-05-18T09:30:00Z',
    triggeredAt: '2026-05-18T09:30:05Z',
    reason: 'Price crossed threshold',
    marketPhaseSummary: {
      market: 'cn',
      phase: 'intraday',
      isPartialBar: false,
      warnings: [],
    },
    analysisContextPackOverview: {
      packVersion: 'v1',
      subject: { code: '600519' },
      blocks: [],
      counts: {
        available: 1,
        missing: 0,
        notSupported: 0,
        fallback: 0,
        stale: 0,
        estimated: 0,
        partial: 0,
        fetchFailed: 0,
      },
      dataQuality: {
        level: 'good',
        blockScores: {},
        limitations: ['limit one', 'limit two'],
      },
      warnings: [],
      metadata: {},
    },
  },
  {
    id: 2,
    ruleId: 11,
    target: 'AAPL',
    status: 'degraded',
    observedValue: null,
    threshold: 210,
    dataSource: null,
    triggeredAt: '2026-05-18T14:00:00Z',
    diagnostics: 'Fallback cache used',
  },
];

describe('AlertTriggerHistory', () => {
  beforeEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  it('renders Chinese trigger history labels by default', () => {
    render(<AlertTriggerHistory triggers={sampleTriggers} />);

    expect(screen.getByText('触发历史')).toBeInTheDocument();
    expect(screen.getByText('评估记录')).toBeInTheDocument();
    expect(screen.getByText('已触发')).toBeInTheDocument();
    expect(screen.getByText('降级')).toBeInTheDocument();
    expect(screen.getByText('CN · 盘中')).toBeInTheDocument();
    expect(screen.getByText('质量：good')).toBeInTheDocument();
    expect(screen.getByText('limit one；limit two')).toBeInTheDocument();
  });

  it('renders English trigger history headers, statuses, phase, and states when UI language is en', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    const { rerender } = render(
      <UiLanguageProvider>
        <AlertTriggerHistory triggers={sampleTriggers} />
      </UiLanguageProvider>,
    );

    expect(screen.getByText('Trigger history')).toBeInTheDocument();
    expect(screen.getByText('Evaluation records')).toBeInTheDocument();
    for (const header of ['Status', 'Phase / Quality', 'Target', 'Observed', 'Threshold', 'Data source', 'Data time', 'Reason']) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    expect(screen.getByText('Triggered')).toBeInTheDocument();
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('CN · Intraday')).toBeInTheDocument();
    expect(screen.getByText('Quality: good')).toBeInTheDocument();
    expect(screen.getByText('limit one; limit two')).toBeInTheDocument();

    rerender(
      <UiLanguageProvider>
        <AlertTriggerHistory triggers={[]} />
      </UiLanguageProvider>,
    );
    expect(screen.getByText('No trigger history yet')).toBeInTheDocument();

    rerender(
      <UiLanguageProvider>
        <AlertTriggerHistory triggers={[]} isLoading />
      </UiLanguageProvider>,
    );
    expect(screen.getByText('Loading trigger history')).toBeInTheDocument();
  });
});
