import { expect, test } from '@playwright/test';

test('API Route preset discovers models and saves the OpenAI gateway configuration', async ({ page }, testInfo) => {
  let savedItems: Array<{ key: string; value: string }> = [];
  const item = (key: string, value: string) => ({
    key, value, rawValueExists: Boolean(value), isMasked: false,
    schema: { key, title: key, category: 'ai_model', dataType: 'string', uiControl: 'text',
      isSensitive: false, isRequired: false, isEditable: true, options: [], validation: {}, displayOrder: 1 },
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (path === '/api/v1/system/config/llm/discover-models') {
      expect(route.request().postDataJSON()).toMatchObject({
        name: 'api_route', protocol: 'openai', base_url: 'https://global.api-route.com/v1',
        api_key: 'fixture-only-key',
      });
      await route.fulfill({ json: { success: true, resolved_protocol: 'openai',
        models: ['gpt-6.1-sol', 'claude-fable-5-1'], latency_ms: 10 } });
      return;
    }
    if (path === '/api/v1/system/config/llm/test-channel') {
      expect(route.request().postDataJSON()).toMatchObject({ name: 'api_route', protocol: 'openai' });
      await route.fulfill({ json: { success: true, message: 'LLM channel test succeeded',
        resolved_protocol: 'openai', resolved_model: 'openai/gpt-6.1-sol', latency_ms: 10 } });
      return;
    }
    if (path === '/api/v1/system/config' && route.request().method() === 'PUT') {
      savedItems = route.request().postDataJSON().items;
      await route.fulfill({ json: { success: true, config_version: 'fixture-v2',
        applied_count: savedItems.length, skipped_masked_count: 0, reload_triggered: true,
        updated_keys: savedItems.map(({ key }) => key), warnings: [] } });
      return;
    }
    const json = path === '/api/v1/auth/status'
      ? { authEnabled: false, loggedIn: true, passwordSet: false, setupState: 'disabled' }
      : path === '/api/v1/system/config'
        ? { configVersion: 'fixture-v1', maskToken: '******', items: [item('LLM_CHANNELS', '')] }
        : path === '/api/v1/system/config/setup/status'
          ? { ready: true, checks: [] }
          : { success: true, accounts: [], items: [], total: 0, backends: [] };
    await route.fulfill({ json });
  });

  await page.goto('/settings');
  await page.getByRole('navigation', { name: '配置分类' }).getByRole('button', { name: /AI 模型/ }).click();
  await page.locator('select').filter({ has: page.getByRole('option', { name: 'API Route', exact: true }) }).selectOption('api_route');
  await page.getByRole('button', { name: '+ 添加渠道', exact: true }).click();
  await expect(page.getByLabel('渠道名称', { exact: true })).toHaveValue('api_route');
  await expect(page.getByLabel('Base URL', { exact: true })).toHaveValue('https://global.api-route.com/v1');
  await expect(page.getByLabel('协议', { exact: true })).toHaveValue('openai');
  await expect(page.getByText(/模型列表依赖 API Key 所属分组/)).toBeVisible();
  await page.getByLabel('API Key', { exact: true }).fill('fixture-only-key');
  await page.getByLabel('模型（逗号分隔）', { exact: true }).fill('');
  await page.getByRole('button', { name: '获取模型', exact: true }).click();
  await page.getByLabel('gpt-6.1-sol', { exact: true }).check();
  await page.getByLabel('claude-fable-5-1', { exact: true }).check();
  await expect(page.getByLabel('手动模型（逗号分隔）', { exact: true })).toHaveValue('gpt-6.1-sol,claude-fable-5-1');
  await page.getByLabel('主模型', { exact: true }).selectOption('openai/gpt-6.1-sol');
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText('连接成功 · openai/gpt-6.1-sol · 10 ms', { exact: true })).toBeVisible();
  const path = testInfo.outputPath('api-route-settings.png');
  await page.screenshot({ path, fullPage: true, animations: 'disabled' });
  await testInfo.attach('api-route-settings', { path, contentType: 'image/png' });
  await page.getByRole('button', { name: '保存 AI 配置', exact: true }).click();
  await expect.poll(() => savedItems).toEqual(expect.arrayContaining([
    { key: 'LLM_CHANNELS', value: 'api_route' },
    { key: 'LLM_API_ROUTE_PROTOCOL', value: 'openai' },
    { key: 'LLM_API_ROUTE_BASE_URL', value: 'https://global.api-route.com/v1' },
    { key: 'LLM_API_ROUTE_MODELS', value: 'gpt-6.1-sol,claude-fable-5-1' },
    { key: 'LITELLM_MODEL', value: 'openai/gpt-6.1-sol' },
  ]));
});
