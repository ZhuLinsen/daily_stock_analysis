import { expect, test } from '@playwright/test';

// Render the real settings page with no backend, credentials, or external requests.
for (const language of ['zh', 'en'] as const) {
  test(`TickPlus recommendation and registration help (${language})`, async ({ page }, testInfo) => {
    const registration = 'http://www.tickplus.org/register?reg=5433cf922395';
    await page.addInitScript((value) => localStorage.setItem('dsa.uiLanguage', value), language);
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      const json = path === '/api/v1/auth/status'
        ? { authEnabled: false, loggedIn: true, passwordSet: true, setupState: 'enabled' }
        : path === '/api/v1/system/config'
          ? {
              configVersion: 'fixture-v1', maskToken: '******', items: [{
                key: 'TICKPLUS_API_KEY', value: '', rawValueExists: false, isMasked: false,
                schema: {
                  key: 'TICKPLUS_API_KEY', title: 'TickPlus API Key (Recommended)',
                  category: 'data_source', dataType: 'string', uiControl: 'password',
                  isSensitive: true, isRequired: false, isEditable: true,
                  options: [], validation: {}, displayOrder: 15,
                  helpKey: 'settings.data_source.TICKPLUS_API_KEY',
                  examples: ['TICKPLUS_API_KEY=your_tickplus_key'],
                  docs: [{ label: 'TickPlus (Recommended) — Register', href: registration }],
                },
              }],
            }
          : { ready: true, checks: [], success: true, items: [], accounts: [] };
      await route.fulfill({ json });
    });
    await page.goto('/settings?category=data_source');
    const title = language === 'zh' ? 'TickPlus API Key（推荐）' : 'TickPlus API Key (Recommended)';
    await expect(page.getByLabel(title, { exact: true })).toBeVisible();
    const settingsPath = testInfo.outputPath(`tickplus-settings-${language}.png`);
    await page.screenshot({ path: settingsPath, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`tickplus-settings-${language}`, { path: settingsPath, contentType: 'image/png' });

    await page.getByRole('button', { name: /TickPlus/ }).click();
    await expect(page.getByRole('dialog', { name: title })).toBeVisible();
    await expect(page.getByRole('link', { name: /TickPlus.*Register/ })).toHaveAttribute('href', registration);
    const helpPath = testInfo.outputPath(`tickplus-help-${language}.png`);
    await page.screenshot({ path: helpPath, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`tickplus-help-${language}`, { path: helpPath, contentType: 'image/png' });
  });
}
