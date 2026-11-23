import { expect, test } from '@playwright/test';

test.use({ locale: 'zh-CN' });

test('alerts disclose legacy sources with an empty database list', async ({ page }, testInfo) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) {
      await route.continue();
      return;
    }
    const json = path === '/api/v1/auth/status'
      ? { authEnabled: false, loggedIn: true, setupState: 'no_password' }
      : path === '/api/v1/portfolio/accounts'
        ? { accounts: [] }
        : {
          items: [], total: 0, page: 1, page_size: 20,
          ...(path === '/api/v1/alerts/rules'
            ? { rule_sources: { legacy_configured: 2, legacy_effective: 1 } }
            : {}),
        };
    await route.fulfill({ json });
  });
  await page.goto('/alerts');
  const notice = page.getByRole('alert').filter({ hasText: '存在环境变量告警规则' });
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('配置了 2 条有效规则');
  await expect(notice).toContainText('去重后有 1 条');
  await expect(notice).toContainText('删除或禁用页面规则不会停用环境规则');
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    await expect(notice).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const path = testInfo.outputPath(`alerts-sources-${name}.png`);
    await page.screenshot({ path, fullPage: true });
    await testInfo.attach(`alerts-sources-${name}`, { path, contentType: 'image/png' });
  }
});
