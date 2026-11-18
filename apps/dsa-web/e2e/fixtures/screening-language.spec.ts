import { expect, test } from '@playwright/test';

test('switches language during a screening run and on its completed results', async ({ page }, testInfo) => {
  let submissions = 0;
  let polls = 0;
  let statusRequests = 0;
  let finishRun = false;
  await page.addInitScript(() => localStorage.setItem('dsa.uiLanguage', 'en'));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    let json: unknown = { items: [], total: 0 };
    if (path.endsWith('/auth/status')) json = { authEnabled: false, loggedIn: true };
    if (path.endsWith('/screening/status')) {
      statusRequests++;
      json = { enabled: true, available: true };
    }
    if (path.endsWith('/screening/strategies')) json = {
      enabled: true, strategies: [{ id: 'quality', name: 'Quality', description: 'Quality factor screen', category: 'quality' }],
    };
    if (path.endsWith('/screening/hotspots')) json = { enabled: true, hotspots: [] };
    if (path.endsWith('/screening/history')) json = { runs: [] };
    if (path.endsWith('/screening/screen/tasks')) {
      submissions++;
      json = { task_id: 'language-test', status: 'pending', message: '选股任务已提交' };
    }
    if (path.endsWith('/screening/screen/tasks/language-test')) {
      polls++;
      json = finishRun ? {
        task_id: 'language-test', status: 'completed', progress: 100, result: {
          enabled: true, strategy: 'quality', market: 'cn', run_id: 'example-run', candidate_count: 1,
          candidates: [{
            rank: 1, code: '600519', name: '贵州茅台', reason: '数据源提供的摘要',
            amount: 100_000_000, score: 85, risk_level: 'medium', factor_scores: { value: 86 }, raw: {},
          }],
        },
      } : { task_id: 'language-test', status: 'processing', progress: 25, message: '正在读取全市场快照' };
    }
    await route.fulfill({ json });
  });
  await page.clock.install();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/screening');
  const runButton = page.getByRole('button', { name: 'Run screening', exact: true });
  await expect(runButton).toBeEnabled();
  const initialStatusRequests = statusRequests;
  await runButton.click();
  await expect(page.getByText('Loading the market snapshot · 25%')).toBeVisible();
  await page.getByRole('button', { name: 'Switch UI language' }).click();
  await expect(page.getByText('正在读取全市场快照 · 25%')).toBeVisible();
  expect(polls).toBe(1);
  finishRun = true;
  await page.clock.fastForward(2000);
  await expect(page.getByRole('heading', { name: '选股结果' })).toBeVisible();
  await expect(page.getByText('1.00 亿', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('stock-screening-zh.png'), animations: 'disabled' });
  await page.getByRole('button', { name: '切换界面语言' }).click();
  await expect(page.getByRole('heading', { name: 'Screening results' })).toBeVisible();
  await expect(page.getByText('100.00 M', { exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '贵州茅台' })).toBeVisible();
  await expect(page.getByText('数据源提供的摘要', { exact: true })).toBeVisible();
  expect(submissions).toBe(1);
  expect(polls).toBe(2);
  expect(statusRequests).toBe(initialStatusRequests);
  await page.screenshot({ path: testInfo.outputPath('stock-screening-en.png'), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Run screening', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('stock-screening-en-mobile.png'), animations: 'disabled' });
});
