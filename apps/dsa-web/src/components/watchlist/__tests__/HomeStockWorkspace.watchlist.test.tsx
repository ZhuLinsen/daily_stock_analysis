import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HomeStockWorkspace } from '../HomeStockWorkspace';
import type { HomeWatchlistRow } from '../HomeStockWorkspace';
import type { StockBarItem } from '../../../types/analysis';

const baseHistoryItem: StockBarItem = {
  id: 1001,
  stockCode: '600519',
  stockName: '贵州茅台',
  lastAnalysisTime: '2026-03-21T08:00:00Z',
  sentimentScore: 72,
  action: 'hold',
  analysisCount: 1,
};

function makeRow(overrides: Partial<HomeWatchlistRow> = {}): HomeWatchlistRow {
  return {
    code: baseHistoryItem.stockCode,
    latestItem: baseHistoryItem,
    analyzedToday: true,
    ...overrides,
  };
}

const baseProps = {
  activeTab: 'watchlist' as const,
  onTabChange: vi.fn(),
  watchlistRows: [] as HomeWatchlistRow[],
  watchlistLoading: false,
  watchlistActioning: false,
  watchlistMessage: null,
  onAddToWatchlist: vi.fn(),
  onRemoveFromWatchlist: vi.fn(),
  onRefreshWatchlist: vi.fn(),
  onAnalyzeWatchlist: vi.fn(),
  isBatchAnalyzing: false,
  batchStatus: null,
  todayItems: [],
  isLoadingTodayItems: false,
  todayLoadError: false,
  watchlistAnalyzedTodayCount: 0,
  historyItems: [],
  isLoadingHistory: false,
  onHistoryItemClick: vi.fn(),
  onDeleteStock: vi.fn(),
  isDeleting: false,
};

describe('HomeStockWorkspace watchlist row click + keyboard accessibility (#2115)', () => {
  it('calls onHistoryItemClick with latest record id when row is clicked', () => {
    const onHistoryItemClick = vi.fn();
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    fireEvent.click(row);
    expect(onHistoryItemClick).toHaveBeenCalledTimes(1);
    expect(onHistoryItemClick).toHaveBeenCalledWith(1001);
  });

  it('calls onHistoryItemClick when Enter key is pressed on focused row', () => {
    const onHistoryItemClick = vi.fn();
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onHistoryItemClick).toHaveBeenCalledTimes(1);
    expect(onHistoryItemClick).toHaveBeenCalledWith(1001);
  });

  it('calls onHistoryItemClick when Space key is pressed on focused row', () => {
    const onHistoryItemClick = vi.fn();
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    fireEvent.keyDown(row, { key: ' ' });
    expect(onHistoryItemClick).toHaveBeenCalledTimes(1);
    expect(onHistoryItemClick).toHaveBeenCalledWith(1001);
  });

  it('calls onNoHistoryHint instead of onHistoryItemClick when row has no latestItem', () => {
    const onHistoryItemClick = vi.fn();
    const onNoHistoryHint = vi.fn();
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow({ latestItem: undefined, analyzedToday: false })]}
        onHistoryItemClick={onHistoryItemClick}
        onNoHistoryHint={onNoHistoryHint}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    fireEvent.click(row);
    expect(onHistoryItemClick).not.toHaveBeenCalled();
    expect(onNoHistoryHint).toHaveBeenCalledTimes(1);
    expect(onNoHistoryHint).toHaveBeenCalledWith('600519');
  });

  it('does not trigger row click when delete button is clicked (stopPropagation)', () => {
    const onHistoryItemClick = vi.fn();
    const onRemoveFromWatchlist = vi.fn(async () => {});
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
      />,
    );

    const removeButton = screen.getByLabelText('从自选股移除 600519');
    fireEvent.click(removeButton);

    expect(onRemoveFromWatchlist).toHaveBeenCalledTimes(1);
    expect(onRemoveFromWatchlist).toHaveBeenCalledWith('600519');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('row has role=button, tabIndex=0, and aria-label describing action', () => {
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    expect(row).toHaveAttribute('role', 'button');
    expect(row).toHaveAttribute('tabindex', '0');
    expect(row).toHaveAttribute('aria-label', '打开 600519 最新分析详情');
  });

  it('row aria-label flips to no-history state when latestItem is missing', () => {
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow({ latestItem: undefined, analyzedToday: false })]}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    expect(row).toHaveAttribute('aria-label', '600519 暂无分析记录，点击查看');
  });

  it('default onNoHistoryHint is noop when not provided (does not throw)', () => {
    const onHistoryItemClick = vi.fn();
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow({ latestItem: undefined, analyzedToday: false })]}
        onHistoryItemClick={onHistoryItemClick}
      />,
    );

    const row = screen.getByTestId('watchlist-row-item');
    expect(() => fireEvent.click(row)).not.toThrow();
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  // PR #2144 review blocker OR-COR-68a8034a regression:
  // 删除按钮聚焦后按 Enter / Space 不应冒泡到行级 handleClick — 否则会
  // 同时打开详情或弹「无历史记录」提示，并且行级 preventDefault() 会
  // 干预按钮原生键盘激活，导致键盘删除行为不稳定。
  it('does not trigger row click when Enter is pressed on focused delete button (OR-COR-68a8034a)', () => {
    const onHistoryItemClick = vi.fn();
    const onNoHistoryHint = vi.fn();
    const onRemoveFromWatchlist = vi.fn(async () => {});
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
        onNoHistoryHint={onNoHistoryHint}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
      />,
    );

    const removeButton = screen.getByLabelText('从自选股移除 600519');
    fireEvent.keyDown(removeButton, { key: 'Enter' });

    expect(onHistoryItemClick).not.toHaveBeenCalled();
    expect(onNoHistoryHint).not.toHaveBeenCalled();
  });

  it('does not trigger row click when Space is pressed on focused delete button (OR-COR-68a8034a)', () => {
    const onHistoryItemClick = vi.fn();
    const onNoHistoryHint = vi.fn();
    const onRemoveFromWatchlist = vi.fn(async () => {});
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow()]}
        onHistoryItemClick={onHistoryItemClick}
        onNoHistoryHint={onNoHistoryHint}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
      />,
    );

    const removeButton = screen.getByLabelText('从自选股移除 600519');
    fireEvent.keyDown(removeButton, { key: ' ' });

    expect(onHistoryItemClick).not.toHaveBeenCalled();
    expect(onNoHistoryHint).not.toHaveBeenCalled();
  });

  it('does not trigger row click when Enter is pressed on focused delete button in no-history row (OR-COR-68a8034a + OR-COR-94f7edc3)', () => {
    const onHistoryItemClick = vi.fn();
    const onNoHistoryHint = vi.fn();
    const onRemoveFromWatchlist = vi.fn(async () => {});
    render(
      <HomeStockWorkspace
        {...baseProps}
        watchlistRows={[makeRow({ latestItem: undefined, analyzedToday: false })]}
        onHistoryItemClick={onHistoryItemClick}
        onNoHistoryHint={onNoHistoryHint}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
      />,
    );

    const removeButton = screen.getByLabelText('从自选股移除 600519');
    fireEvent.keyDown(removeButton, { key: 'Enter' });

    expect(onNoHistoryHint).not.toHaveBeenCalled();
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });
});
