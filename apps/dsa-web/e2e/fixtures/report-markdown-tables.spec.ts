import { expect, test } from '@playwright/test';

const reference = 'REF-' + '1234567890'.repeat(12);
const metrics = Array.from({ length: 18 }, (_, i) => `Metric ${i + 1}`);
const markdown = [
  '### Position notes',
  '| Position | Observation |',
  '| --- | --- |',
  '| Watching | Wait for the next report before acting. Recheck the price, volume and latest update together before reviewing the position. |',
  '| Holding | 结合价格与成交量观察后续变化，并在下次报告更新后重新检查当前持仓情况。 |',
  '',
  '### Report reference',
  '| Type | Identifier |',
  '| --- | --- |',
  `| Source | ${reference} |`,
  '',
  '### Market data',
  `| ${metrics.join(' | ')} |`,
  `| ${metrics.map(() => '---').join(' | ')} |`,
  `| ${metrics.map((_, i) => 10000 + i).join(' | ')} |`,
].join('\n');

function countTextLines(cell: Element) {
  const range = document.createRange();
  range.selectNodeContents(cell);
  return range.getClientRects().length;
}

test('report tables wrap prose and identifiers and scroll wide data', async ({ page }, testInfo) => {
  const record = {
    id: 1, stock_code: 'EXAMPLE', stock_name: 'Example', query_id: 'example',
    report_type: 'detailed', report_language: 'en', created_at: new Date().toISOString(),
  };
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
        const items = url.searchParams.get('report_type') === 'market_review' ? [] : [record];
        return route.fulfill({ json: { items, total: items.length, page: 1, limit: 20 } });
      }
      case '/api/v1/history/1':
        return route.fulfill({ json: { meta: record, summary: { sentiment_score: 50 } } });
      case '/api/v1/history/1/markdown':
        return route.fulfill({ json: { content: markdown } });
      default:
        return route.fulfill({ json: { items: [], accounts: [], tasks: [], skills: [], total: 0 } });
    }
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Full analysis report' }).click();
  const drawer = page.getByRole('dialog');
  const tables = drawer.getByRole('table');
  await expect(tables).toHaveCount(3);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    if (width === 390) {
      const path = testInfo.outputPath('report-tables-390.png');
      await drawer.screenshot({ path, animations: 'disabled' });
      await testInfo.attach('Report tables at 390px', {
        path, contentType: 'image/png',
      });
    }
    for (const table of [tables.nth(0), tables.nth(1)]) {
      expect(await table.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    }
    expect(await drawer.getByRole('cell', { name: reference }).evaluate(countTextLines)).toBeGreaterThan(1);
    if (width === 390) {
      for (const name of [/Wait for the next report/, /结合价格与成交量/]) {
        expect(await drawer.getByRole('cell', { name }).evaluate(countTextLines)).toBeGreaterThan(1);
      }
    }
    const wide = tables.nth(2);
    await wide.scrollIntoViewIfNeeded();
    await wide.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    expect(await wide.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
    const lastValue = wide.getByRole('cell', { name: '10017' });
    await expect(lastValue).toBeInViewport();
    expect(await lastValue.evaluate(countTextLines)).toBe(1);
  }
});
