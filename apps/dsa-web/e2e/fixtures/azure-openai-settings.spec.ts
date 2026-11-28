import { expect, test } from '@playwright/test';

test('switches Azure channel settings between Chinese and English', async ({ page }, testInfo) => {
  const items = Object.entries({
    LLM_CHANNELS: 'azure',
    LLM_AZURE_PROTOCOL: 'azure',
    LLM_AZURE_BASE_URL: 'https://example.openai.azure.com/openai/v1',
    LLM_AZURE_MODELS: '',
    LLM_AZURE_ENABLED: 'true',
  }).map(([key, value]) => ({
    key, value, rawValueExists: true, isMasked: false,
    schema: { key, title: key, category: 'ai_model', dataType: 'string', uiControl: 'text',
      isSensitive: false, isRequired: false, isEditable: true,
      options: [], validation: {}, displayOrder: 1 },
  }));
  await page.addInitScript(() => localStorage.setItem('dsa.uiLanguage', 'zh'));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    const json = path === '/api/v1/auth/status'
      ? { authEnabled: false, loggedIn: true, passwordSet: true, setupState: 'enabled' }
      : path === '/api/v1/system/config'
        ? { configVersion: 'fixture-v1', maskToken: '******', items }
        : path === '/api/v1/system/config/llm/test-channel'
          ? {
            success: false, stage: 'chat_completion', error_code: 'invalid_config',
            message: 'LLM channel configuration is invalid',
            error: 'Azure OpenAI requires a resource endpoint',
            details: { issue_code: 'invalid_azure_endpoint' },
          }
          : { ready: true, checks: [], success: true, items: [], accounts: [] };
    await route.fulfill({ json });
  });
  await page.goto('/settings?category=ai_model');
  await page.getByRole('button', { name: /Azure OpenAI/ }).click();
  await expect(page.getByPlaceholder('留空使用 DefaultAzureCredential')).toBeVisible();
  await expect(page.getByPlaceholder('Azure 部署名称')).toBeVisible();
  await expect(page.getByText('请手动输入 Azure 门户中的部署名称，不是基础模型名称。')).toBeVisible();
  await expect(page.getByText('填写 Azure OpenAI 资源的 HTTPS 根地址和部署名称。', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: '获取模型', exact: true })).toHaveCount(0);
  await page.getByPlaceholder('Azure 部署名称').fill('my-deployment');
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText('请填写 Azure OpenAI 资源根地址', { exact: false })).toBeVisible();
  await expect(page.getByText('使用 Microsoft Entra ID 时，API Key 可留空。', { exact: false })).toBeVisible();
  const zhPath = testInfo.outputPath('azure-openai-zh.png');
  await page.screenshot({ path: zhPath, fullPage: true, animations: 'disabled' });
  await testInfo.attach('azure-openai-zh', { path: zhPath, contentType: 'image/png' });

  await page.getByRole('button', { name: '切换界面语言' }).click();
  await expect(page.getByPlaceholder('Leave blank to use DefaultAzureCredential')).toBeVisible();
  await expect(page.getByPlaceholder('Azure deployment name')).toBeVisible();
  await expect(page.getByText('Enter the deployment name from the Azure portal, not the base model name.')).toBeVisible();
  await expect(page.getByText('Enter the HTTPS root URL of your Azure OpenAI resource', { exact: false })).toBeVisible();
  await expect(page.getByText('Microsoft Entra ID', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Fetch Models', exact: true })).toHaveCount(0);
  await expect(page.getByText('Enter an Azure OpenAI resource URL such as', { exact: false })).toBeVisible();
  await expect(page.getByText('Leave the API Key blank when using Microsoft Entra ID.', { exact: false })).toBeVisible();
  const enPath = testInfo.outputPath('azure-openai-en.png');
  await page.screenshot({ path: enPath, fullPage: true, animations: 'disabled' });
  await testInfo.attach('azure-openai-en', { path: enPath, contentType: 'image/png' });
});
