import { expect, test } from '@playwright/test';

// Mount the real workspace at the same sidebar widths as HomePage. Only its
// input data is fixed; production component, localization and CSS are unchanged.
const rows = [
  { code: '600519', analyzedToday: true, latestItem: { id: 21, stockCode: '600519', stockName: '贵州茅台', sentimentScore: 88, operationAdvice: '买入', analysisCount: 1, lastAnalysisTime: '2026-10-01T09:00:00+08:00' } },
  { code: '00700', analyzedToday: false },
  { code: 'AAPL', analyzedToday: false, activeTask: { taskId: 'aapl-demo', stockCode: 'AAPL', status: 'processing', progress: 25, reportType: 'simple', createdAt: '2026-10-01T09:20:00+08:00' } },
];

test('watchlist signals stay readable and accessible at sidebar widths', async ({ page }, testInfo) => {
  await page.route('**/src/main.tsx', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `
      import React from '/node_modules/.vite/deps/react.js';
      import ReactDOMClient from '/node_modules/.vite/deps/react-dom_client.js';
      import '/src/index.css';
      import { HomeStockWorkspace } from '/src/components/watchlist/HomeStockWorkspace.tsx';
      import { UiLanguageProvider } from '/src/contexts/UiLanguageContext.tsx';
      const noop = async () => {};
      ReactDOMClient.createRoot(document.getElementById('root')).render(React.createElement(UiLanguageProvider, null,
        React.createElement('main', {className: 'min-h-screen bg-background p-4 text-foreground'},
          React.createElement('div', {className: 'flex h-[1100px] w-full md:w-64 lg:w-72'},
            React.createElement(HomeStockWorkspace, {
              activeTab: 'watchlist', onTabChange: noop, watchlistRows: ${JSON.stringify(rows)},
              watchlistLoading: false, watchlistActioning: false, watchlistMessage: null,
              onAddToWatchlist: noop, onRemoveFromWatchlist: noop, onRefreshWatchlist: noop,
              onAnalyzeWatchlist: async (mode) => { document.documentElement.dataset.analysisMode = mode; },
              isBatchAnalyzing: false, batchStatus: null, todayItems: [], isLoadingTodayItems: false,
              todayLoadError: false, watchlistAnalyzedTodayCount: 1, historyItems: [],
              isLoadingHistory: false, selectedStockCode: '600519', selectedRecordId: 21,
              onHistoryItemClick: noop
            })
          )
        )
      ));
    `,
  }));
  await page.goto('/');
  await expect(page.getByText('今日待分析 1')).toBeVisible();
  await expect(page.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' })).toHaveAccessibleDescription(
    '变化：等待首次分析；状态：任务分析中；下一步：等待任务完成',
  );
  await page.getByRole('button', { name: '仅未分析', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-analysis-mode', 'pending');
  for (const width of [900, 1280, 390]) {
    await page.setViewportSize({ width, height: 1200 });
    const workspace = page.getByTestId('home-stock-workspace');
    for (const code of ['600519', '00700', 'AAPL']) {
      const row = page.getByTestId(`watchlist-row-${code}`);
      await expect(row).toBeVisible();
      await expect(row.getByText('下一步', { exact: true })).toBeVisible();
      expect(await row.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const screenshot = testInfo.outputPath(`watchlist-signals-${width}.png`);
    await workspace.screenshot({ path: screenshot, animations: 'disabled' });
    await testInfo.attach(`watchlist-${width}`, { path: screenshot, contentType: 'image/png' });
  }
});
