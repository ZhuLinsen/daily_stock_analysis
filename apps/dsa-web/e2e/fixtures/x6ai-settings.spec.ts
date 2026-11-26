import { expect, test } from '@playwright/test';

// Visual/interaction evidence uses synthetic credentials; live provider tests are separate.
test('x6.ai gateway model selection and sponsor links', async ({ page }, testInfo) => {
  const model = 'openai/minimax/minimax-m3.1-flash-discount';
  const items = Object.entries({
    LLM_CHANNELS: 'x6ai', LLM_X6AI_PROTOCOL: 'openai',
    LLM_X6AI_BASE_URL: 'https://api.x6.ai/v1', LLM_X6AI_API_KEY: 'fixture-only',
    LLM_X6AI_MODELS: 'openai/anthropic/claude-haiku-5-5-discount', LLM_X6AI_ENABLED: 'true',
  }).map(([key, value]) => ({
    key, value, rawValueExists: true, isMasked: false,
    schema: { key, title: key, category: 'ai_model', dataType: 'string', uiControl: 'text',
      isSensitive: key.endsWith('API_KEY'), isRequired: false, isEditable: true,
      options: [], validation: {}, displayOrder: 1 },
  }));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const json = path === '/api/v1/auth/status'
      ? { authEnabled: false, loggedIn: true, passwordSet: true, setupState: 'enabled' }
      : path === '/api/v1/system/config'
        ? { configVersion: 'fixture-v1', maskToken: '******', items }
        : path === '/api/v1/system/config/llm/discover-models'
          ? { success: true, message: 'Models discovered', models: [model, 'openai/anthropic/claude-haiku-5-5-discount'], resolvedProtocol: 'openai' }
          : { ready: true, checks: [], success: true, items: [], accounts: [] };
    await route.fulfill({ json });
  });
  await page.goto('/settings?category=ai_model');
  const providerSelect = page.getByRole('combobox', { name: '', exact: true });
  await providerSelect.selectOption('x6ai');
  await expect(page.getByRole('link', { name: '注册 x6.ai', exact: true })).toHaveAttribute('href', 'https://console.x6pro.io/register?code=zJ2qSdns');
  expect((await providerSelect.locator('option').allTextContents()).slice(1, 4)).toEqual(['Modelflare（聚合平台）', 'x6.ai（聚合平台）', 'DeepSeek 官方']);
  await page.getByRole('button', { name: /x6.ai/i }).click();
  await expect(page.getByRole('link', { name: 'x6.ai 专属注册' })).toHaveAttribute('href', 'https://console.x6pro.io/register?code=zJ2qSdns');
  await page.getByRole('button', { name: '获取模型', exact: true }).click();
  await page.getByLabel(model, { exact: true }).check();
  await expect(page.getByRole('textbox', { name: '手动模型（逗号分隔）', exact: true })).toHaveValue(`openai/anthropic/claude-haiku-5-5-discount,${model}`);
  const screenshot = testInfo.outputPath('x6ai-settings.png');
  await page.screenshot({ path: screenshot, fullPage: true, animations: 'disabled' });
  await testInfo.attach('x6ai-settings', { path: screenshot, contentType: 'image/png' });
});
