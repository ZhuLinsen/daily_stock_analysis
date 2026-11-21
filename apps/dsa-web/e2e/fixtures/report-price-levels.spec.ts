import { expect, test } from '@playwright/test';

test('saved report fetches price levels on demand and recovers from empty and failed history', async ({ page }, testInfo) => {
  const report = {
    id: 1, stock_code: 'EXAMPLE', stock_name: 'Example', query_id: 'example',
    report_type: 'detailed', report_language: 'en', created_at: '2026-11-20T10:00:00Z',
    current_price: 179,
  };
  const bars = Array.from({ length: 80 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 6, 6 + Math.floor(i / 5) * 7 + i % 5)).toISOString().slice(0, 10),
    open: 99 + i, high: 101 + i, low: 98 + i, close: 100 + i,
  }));
  let historyRequests = 0;

  await page.addInitScript(() => {
    localStorage.setItem('dsa.uiLanguage', 'en');
    localStorage.setItem('theme', 'light');
  });
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    switch (url.pathname) {
      case '/api/v1/auth/status':
        return route.fulfill({ json: { authEnabled: false, loggedIn: true, setupState: 'no_password' } });
      case '/api/v1/system/config/setup/status':
        return route.fulfill({ json: { ready: true, checks: [] } });
      case '/api/v1/history': {
        const items = url.searchParams.get('report_type') === 'market_review' ? [] : [report];
        return route.fulfill({ json: { items, total: items.length, page: 1, limit: 20 } });
      }
      case '/api/v1/history/1':
        return route.fulfill({
          json: {
            meta: report,
            summary: { sentiment_score: 50 },
            strategy: { ideal_buy: '$145', secondary_buy: '$140', stop_loss: '$130', take_profit: '$185' },
          },
        });
      case '/api/v1/stocks/EXAMPLE/history': {
        historyRequests += 1;
        if (historyRequests === 2) {
          return route.fulfill({ status: 500, json: { detail: 'Example request error' } });
        }
        return route.fulfill({
          json: { stock_code: 'EXAMPLE', period: 'daily', data: historyRequests === 1 ? [] : bars },
        });
      }
      default:
        return route.fulfill({ json: { items: [], accounts: [], tasks: [], skills: [], total: 0 } });
    }
  });

  await page.goto('/');
  const toggle = page.getByRole('button', { name: 'Levels Chart' });
  const card = page.locator('.terminal-card').filter({ has: toggle }).last();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(historyRequests).toBe(0);
  const request = page.waitForRequest('**/api/v1/stocks/EXAMPLE/history?*');
  await toggle.click();
  expect(Object.fromEntries(new URL((await request).url()).searchParams)).toEqual({ period: 'daily', days: '60' });

  await expect(page.getByText('No daily K-line history available for price overlay.')).toBeVisible();
  const retry = page.getByRole('button', { name: 'Retry', exact: true });
  await retry.click();
  await expect(page.getByText('Could not load daily price history.')).toBeVisible();
  await retry.click();

  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(card.getByText('179.00', { exact: true })).toBeVisible();
  await expect(card.getByText('(60D)', { exact: false })).toBeVisible();
  for (const label of ['MA5', 'MA20', 'Buy 145', '2nd 140', 'SL 130', 'TP 185']) {
    await expect(card.getByText(label, { exact: true })).toBeVisible();
  }
  await expect(card.locator('path.recharts-line-curve')).toHaveCount(2);
  const screenshotPath = testInfo.outputPath('report-price-levels-expanded.png');
  await card.screenshot({ path: screenshotPath, animations: 'disabled' });
  await testInfo.attach('Expanded report price levels', { path: screenshotPath, contentType: 'image/png' });

  await toggle.click();
  await expect(card.getByText('(60D)', { exact: false })).toHaveCount(0);
  await toggle.click();
  await expect(card.getByText('(60D)', { exact: false })).toBeVisible();
  expect(historyRequests).toBe(3);
});
