import { expect, test } from '@playwright/test';

const position = (symbol: string, market: string, currency: string, value: number) => ({
  symbol, market, currency, quantity: 10, avgCost: value / 10, totalCost: value,
  lastPrice: value / 10, marketValueBase: value, unrealizedPnlBase: 0,
  unrealizedPnlPct: 0, valuationCurrency: 'CNY', priceSource: 'history_close',
  priceDate: '2026-10-01', priceStale: false, priceAvailable: true,
});

for (const state of ['complete', 'missing-price', 'snapshot-error', 'invalid-top', 'invalid-sector', 'rounded-tail', 'empty'] as const) {
  test(`portfolio risk dashboard: ${state}`, async ({ page }, testInfo) => {
    const positions = [position('600519', 'cn', 'CNY', 6000), position('AAPL', 'us', 'USD', 4000)];
    if (state === 'rounded-tail') {
      Object.assign(positions[0], { lastPrice: 1000000, marketValueBase: 10000000 });
      Object.assign(positions[1], { lastPrice: 0.1, marketValueBase: 1 });
    }
    if (state === 'empty') positions.length = 0;
    if (state === 'missing-price') {
      Object.assign(positions[1], { lastPrice: 0, marketValueBase: 0, priceSource: 'missing', priceAvailable: false });
    }
    const snapshot = {
      asOf: '2026-10-01', costMethod: 'fifo', currency: 'CNY', accountCount: 1,
      totalCash: 1000, totalMarketValue: 10000, totalEquity: 11000, fxStale: false,
      dataQuality: 'ok', limitations: [],
      accounts: [{ accountId: 1, accountName: 'Demo', baseCurrency: 'CNY', fxStale: false, positions }],
    };
    const risk = {
      asOf: snapshot.asOf, currency: 'CNY', accountId: null, costMethod: 'fifo', thresholds: {},
      concentration: { totalMarketValue: 10000, topWeightPct: 60, alert: true, topPositions: [
        { symbol: state === 'invalid-top' ? '' : '600519', marketValueBase: 6000, weightPct: 60, isAlert: true },
        { symbol: 'AAPL', marketValueBase: 4000, weightPct: 40, isAlert: false },
      ] },
      sectorConcentration: state === 'invalid-sector' ? {
        totalMarketValue: 10000, topWeightPct: 80, alert: true,
        topSectors: [
          { sector: '白酒', marketValueBase: 2000, weightPct: 20, symbolCount: 1, isAlert: false },
          { sector: '科技', marketValueBase: 8000, weightPct: 80, symbolCount: 1, isAlert: true },
        ], coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      } : {},
      drawdown: { seriesPoints: 10, currentDrawdownPct: 3, maxDrawdownPct: 8, fxStale: false, alert: false },
      stopLoss: { triggeredCount: 0, nearCount: 0, nearAlert: false, items: [] },
      decisionSignalRisk: { available: true, total: 0, actions: { sell: 0, reduce: 0, alert: 0 }, items: [] },
    };
    if (state === 'rounded-tail') {
      snapshot.totalMarketValue = 10000001;
      snapshot.totalEquity = 10001001;
      risk.concentration.totalMarketValue = 10000001;
      risk.concentration.topWeightPct = 100;
      risk.concentration.topPositions[0] = { symbol: '600519', marketValueBase: 10000000, weightPct: 100, isAlert: true };
      risk.concentration.topPositions[1] = { symbol: 'AAPL', marketValueBase: 1, weightPct: 0, isAlert: false };
      risk.sectorConcentration = { totalMarketValue: 10000001, topWeightPct: 100, alert: true,
        topSectors: [
          { sector: '白酒', marketValueBase: 10000000, weightPct: 100, symbolCount: 1, isAlert: true },
          { sector: '科技', marketValueBase: 1, weightPct: 0, symbolCount: 1, isAlert: false },
        ], coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      };
    }
    if (state === 'empty') {
      snapshot.totalMarketValue = 0; snapshot.totalEquity = 1000;
      risk.concentration = { totalMarketValue: 0, topWeightPct: 0, alert: false, topPositions: [] };
    }
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      let json: unknown = { items: [], total: 0, page: 1, pageSize: 20 };
      if (path.endsWith('/auth/status')) json = { authEnabled: false, loggedIn: true, setupState: 'no_password' };
      else if (path.endsWith('/portfolio/accounts')) json = { accounts: [{ id: 1, name: 'Demo', market: 'cn', baseCurrency: 'CNY', isActive: true }] };
      else if (path.endsWith('/portfolio/snapshot')) {
        if (state === 'snapshot-error') return route.fulfill({ status: 503, json: { detail: 'Snapshot unavailable' } });
        json = snapshot;
      } else if (path.endsWith('/portfolio/risk')) json = risk;
      else if (path.endsWith('/portfolio/import/brokers')) json = { brokers: [] };
      await route.fulfill({ json });
    });
    await page.goto('/portfolio');
    const dashboard = page.locator('section').filter({ has: page.getByText('风险与暴露看板', { exact: true }) });
    await expect(dashboard).toBeVisible();
    await expect(page.getByRole('button', { name: '刷新数据', exact: true })).toBeVisible();
    if (state === 'snapshot-error') {
      await expect(dashboard.getByText('总市值: --')).toBeVisible();
      await expect(dashboard.getByText('持仓: --')).toBeVisible();
      await expect(page.getByText('共 -- 项')).toBeVisible();
      await expect(page.getByText('账户数: --')).toBeVisible();
      await expect(page.getByText('最新', { exact: true })).toHaveCount(0);
      await expect(page.getByText('持仓快照不可用', { exact: true })).toBeVisible();
    }
    if (state === 'empty') {
      await expect(dashboard.getByText('总市值: CNY 0.00')).toBeVisible();
      await expect(dashboard.getByText('持仓: 0')).toBeVisible();
      await expect(dashboard.getByText('暂无暴露数据')).toHaveCount(2);
      await expect(page.getByText('当前无持仓数据', { exact: true })).toBeVisible();
    }
    if (state === 'rounded-tail') {
      await expect(dashboard.getByText('Top1: 600519')).toBeVisible();
      await expect(dashboard.getByText('Top1: 白酒')).toBeVisible();
      await expect(dashboard.getByText('100.00%')).toHaveCount(4);
      await expect(page.locator('.recharts-pie-sector')).toHaveCount(1);
      await expect(page.getByText('暂无集中度数据', { exact: true })).toHaveCount(0);
    }
    if (state === 'complete') {
      await expect(dashboard.getByText('Top1: 600519')).toBeVisible();
      await expect(dashboard.getByText('60.00%')).toHaveCount(3);
    }
    if (state === 'invalid-top') {
      await expect(dashboard.getByText('Top1: AAPL')).toHaveCount(0);
      await expect(page.getByText('暂无集中度数据', { exact: true })).toBeVisible();
    }
    if (state === 'invalid-sector') {
      await expect(dashboard.getByText('Top1: 白酒')).toHaveCount(0);
      await expect(dashboard.getByText('Top1: 600519')).toBeVisible();
      await expect(page.getByText('行业数据暂不可用，当前展示个股集中度', { exact: true })).toBeVisible();
    }
    if (state === 'missing-price') await expect(dashboard.getByText('暴露不可用')).toHaveCount(2);
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      // Screenshot animations:disabled does not stop Recharts' JavaScript animation.
      // Assert every expected sector has its final arc (outerRadius=90, no inner
      // radius/padding), including the position fallback in invalid-sector.
      const weights = state === 'rounded-tail' ? [100]
        : state === 'complete' || state === 'invalid-sector' ? [60, 40] : [];
      const sectors = page.locator('.recharts-pie-sector path');
      await expect(sectors).toHaveCount(weights.length);
      for (const [index, weight] of weights.entries()) {
        const expectedLength = 180 + 90 * Math.PI * 2 * weight / 100;
        await expect.poll(async () => Math.abs(
          await sectors.nth(index).evaluate((path) => (path as SVGPathElement).getTotalLength())
          - expectedLength,
        )).toBeLessThan(0.5);
      }
      const screenshot = testInfo.outputPath(`portfolio-${state}-${viewport.width}.png`);
      await dashboard.screenshot({ path: screenshot, animations: 'disabled' });
      await testInfo.attach(`${state}-${viewport.width}`, { path: screenshot, contentType: 'image/png' });
      if (state === 'snapshot-error' || state === 'rounded-tail') {
        const fullPage = testInfo.outputPath(`portfolio-full-${state}-${viewport.width}.png`);
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: fullPage, fullPage: true, animations: 'disabled' });
        await testInfo.attach(`full-${state}-${viewport.width}`, { path: fullPage, contentType: 'image/png' });
      }
    }
  });
}
