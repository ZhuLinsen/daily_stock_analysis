import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../../../contexts/UiLanguageContext';
import { formatDateTime, formatShortDateTime } from '../../../utils/format';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { StockHistoryTrendDrawer } from '../StockHistoryTrendDrawer';
import type { AnalysisReport, HistoryItem } from '../../../types/analysis';

const report: AnalysisReport = {
  meta: {
    id: 1,
    queryId: 'q-1',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed',
    createdAt: '2026-03-20T08:00:00Z',
  },
  summary: {
    analysisSummary: '等待确认',
    operationAdvice: '买入',
    action: 'avoid',
    actionLabel: '回避',
    trendPrediction: '震荡',
    sentimentScore: 35,
  },
};

const items: HistoryItem[] = [
  {
    id: 1,
    queryId: 'q-1',
    stockCode: '600519',
    stockName: '贵州茅台',
    sentimentScore: 35,
    operationAdvice: '买入',
    action: 'avoid',
    actionLabel: '回避',
    trendPrediction: '震荡',
    createdAt: '2026-03-20T08:00:00Z',
  },
];

describe('StockHistoryTrendDrawer', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('uses structured action in summary and rows', () => {
    render(
      <StockHistoryTrendDrawer
        report={report}
        items={items}
        total={1}
        hasMore={false}
        isLoading={false}
        isLoadingMore={false}
        filters={{ range: 'all', model: 'all', sort: 'desc' }}
        onClose={vi.fn()}
        onRangeChange={vi.fn()}
        onLoadMore={vi.fn()}
        onSelectRecord={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getAllByText('回避').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('买入')).not.toBeInTheDocument();
  });

  it('keeps full legacy operation advice when structured action is absent', () => {
    render(
      <StockHistoryTrendDrawer
        report={{
          ...report,
          summary: {
            ...report.summary,
            operationAdvice: '继续持有，等待突破',
            action: null,
            actionLabel: null,
          },
        }}
        items={[
          {
            ...items[0],
            operationAdvice: '继续持有，等待突破',
            action: null,
            actionLabel: null,
          },
        ]}
        total={1}
        hasMore={false}
        isLoading={false}
        isLoadingMore={false}
        filters={{ range: 'all', model: 'all', sort: 'desc' }}
        onClose={vi.fn()}
        onRangeChange={vi.fn()}
        onLoadMore={vi.fn()}
        onSelectRecord={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getAllByText('继续持有，等待突破').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('持有')).not.toBeInTheDocument();
  });

  it('keeps multi-guard legacy advice as full text when structured action is absent', () => {
    render(
      <StockHistoryTrendDrawer
        report={{
          ...report,
          summary: {
            ...report.summary,
            operationAdvice: 'risk alert, avoid buying',
            action: null,
            actionLabel: null,
          },
        }}
        items={[
          {
            ...items[0],
            operationAdvice: 'risk alert, avoid buying',
            action: null,
            actionLabel: null,
          },
        ]}
        total={1}
        hasMore={false}
        isLoading={false}
        isLoadingMore={false}
        filters={{ range: 'all', model: 'all', sort: 'desc' }}
        onClose={vi.fn()}
        onRangeChange={vi.fn()}
        onLoadMore={vi.fn()}
        onSelectRecord={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getAllByText('risk alert, avoid buying').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('回避')).not.toBeInTheDocument();
    expect(screen.queryByText('预警')).not.toBeInTheDocument();
  });

  it('uses localized taxonomy labels before server labels in English UI mode', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    render(
      <UiLanguageProvider>
        <StockHistoryTrendDrawer
          report={{
            ...report,
            summary: {
              ...report.summary,
              action: 'sell',
              actionLabel: '买入',
            },
          }}
          items={[
            {
              ...items[0],
              action: 'sell',
              actionLabel: '买入',
            },
          ]}
          total={1}
          hasMore={false}
          isLoading={false}
          isLoadingMore={false}
          filters={{ range: 'all', model: 'all', sort: 'desc' }}
          onClose={vi.fn()}
          onRangeChange={vi.fn()}
          onLoadMore={vi.fn()}
          onSelectRecord={vi.fn()}
          onRetry={vi.fn()}
        />
      </UiLanguageProvider>,
    );

    expect(screen.getAllByText('Sell').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('买入')).not.toBeInTheDocument();
  });

  it('keeps month and day intact in EN rows and immediately re-formats latest and row timestamps on language switch', () => {
    const iso = '2026-05-18T09:30:00Z';
    const zhLatest = formatDateTime(iso, 'zh');
    const enLatest = formatDateTime(iso, 'en');
    const zhShort = formatShortDateTime(iso, 'zh');
    const enShort = formatShortDateTime(iso, 'en');

    const WrapperDrawer = () => {
      const { setLanguage } = useUiLanguage();
      return (
        <>
          <button type="button" onClick={() => setLanguage('en')}>
            switch-en
          </button>
          <StockHistoryTrendDrawer
            report={{
              ...report,
              meta: { ...report.meta, createdAt: iso },
            }}
            items={[{ ...items[0], createdAt: iso }]}
            total={1}
            hasMore={false}
            isLoading={false}
            isLoadingMore={false}
            filters={{ range: 'all', model: 'all', sort: 'desc' }}
            onClose={vi.fn()}
            onRangeChange={vi.fn()}
            onLoadMore={vi.fn()}
            onSelectRecord={vi.fn()}
            onRetry={vi.fn()}
          />
        </>
      );
    };

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    render(
      <UiLanguageProvider>
        <WrapperDrawer />
      </UiLanguageProvider>,
    );

    expect(screen.getByText(`最近一次 ${zhLatest}`)).toBeInTheDocument();
    expect(screen.getByText(zhShort)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'switch-en' }));

    expect(screen.getByText(`Latest ${enLatest}`)).toBeInTheDocument();
    expect(screen.getByText(enShort)).toBeInTheDocument();
    expect(enShort).toMatch(/^05\/18/);
    expect(screen.queryByText(/^\/2026/)).not.toBeInTheDocument();
  });
});
