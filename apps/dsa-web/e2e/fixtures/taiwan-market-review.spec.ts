import { expect, test } from '@playwright/test';

// Real pages and HTTP serialization; fixed API responses avoid credentials and live LLM calls.
for (const language of ['zh', 'en'] as const) {
  test(`Taiwan recap selection and settings help (${language})`, async ({ page }, testInfo) => {
    await page.addInitScript((locale) => localStorage.setItem('dsa.uiLanguage', locale), language);
    let submittedRegion: string | undefined;
    const items = [{
      key: 'MARKET_REVIEW_REGION', value: 'cn', rawValueExists: true, isMasked: false,
      schema: {
        key: 'MARKET_REVIEW_REGION', title: 'Market Review Region', category: 'system',
        description: 'Market region for review: cn, hk, us, jp, kr, tw (Taiwan), or both (all markets).',
        dataType: 'string', uiControl: 'text', isSensitive: false, isRequired: false,
        isEditable: true, options: ['cn', 'hk', 'us', 'jp', 'kr', 'tw', 'both'],
        validation: { allowedValues: ['cn', 'hk', 'us', 'jp', 'kr', 'tw', 'both'], delimiter: ',' },
        displayOrder: 48, helpKey: 'settings.system.market_review',
      },
    }];
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      if (path === '/api/v1/analysis/market-review') {
        submittedRegion = route.request().postDataJSON().region;
        return route.fulfill({ json: {
          status: 'accepted', message: 'Fixture accepted', send_notification: false,
          task_id: 'tw-fixture', region: submittedRegion,
        } });
      }
      const json = path === '/api/v1/auth/status'
        ? { authEnabled: false, loggedIn: true, passwordSet: false, setupState: 'disabled' }
        : path === '/api/v1/system/config'
          ? { configVersion: 'fixture', maskToken: '******', items }
          : path === '/api/v1/system/config/setup/status'
            ? { ready: true, checks: [] }
            : path === '/api/v1/analysis/status/tw-fixture'
              ? { task_id: 'tw-fixture', status: 'completed', region: 'tw', progress: 100,
                market_review_report: '## Taiwan Market Recap\n\n### Data Limits\n- TWOII: data unavailable' }
              : { success: true, skills: [], items: [], tasks: [], accounts: [], total: 0, page: 1, page_size: 20 };
      return route.fulfill({ json });
    });

    await page.goto('/');
    const selector = page.getByRole('button', { name: language === 'zh' ? '选择大盘复盘市场' : 'Select market review regions' });
    await selector.click();
    await page.getByRole('checkbox', { name: language === 'zh' ? /台股/ : /Taiwan/ }).check();
    await expect(selector).toContainText(language === 'zh' ? '台股' : 'Taiwan');
    const selectorImage = testInfo.outputPath(`taiwan-selector-${language}.png`);
    await page.screenshot({ path: selectorImage, animations: 'disabled' });
    await testInfo.attach('Taiwan selector', { path: selectorImage, contentType: 'image/png' });
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: language === 'zh' ? '大盘复盘' : 'Market review', exact: true }).click();
    await expect.poll(() => submittedRegion).toBe('tw');

    await page.goto('/settings');
    await page.getByRole('button', { name: language === 'zh' ? /系统设置/ : /^System/ }).click();
    const regionInput = page.getByRole('textbox', { name: language === 'zh' ? '大盘复盘市场' : 'Market Review Region', exact: true });
    await expect(regionInput).toHaveValue('cn');
    await regionInput.fill('cn,tw');
    await page.getByRole('button', { name: language === 'zh' ? '查看 大盘复盘市场 配置说明' : /Market Review Region.*help|help.*Market Review Region/i }).click();
    await expect(page.getByText(language === 'zh' ? /tw 覆盖台股/ : /tw covers Taiwan/)).toBeVisible();
    const settingsImage = testInfo.outputPath(`taiwan-settings-${language}.png`);
    await page.screenshot({ path: settingsImage, fullPage: true, animations: 'disabled' });
    await testInfo.attach('Taiwan settings help', { path: settingsImage, contentType: 'image/png' });
  });
}
