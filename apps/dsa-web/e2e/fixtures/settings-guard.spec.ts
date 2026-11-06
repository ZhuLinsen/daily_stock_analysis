import { expect, test, type Page } from '@playwright/test';

// Use the real application/router and draft owners, without backend I/O or secrets.
async function fixture(page: Page, requireLogin = false) {
  let loggedIn = !requireLogin;
  const item = (key: string, value: string, category: string, title = key) => ({
    key, value, rawValueExists: true, isMasked: false,
    schema: { key, title, category, dataType: 'string', uiControl: 'text', isSensitive: false,
      isRequired: false, isEditable: true, options: [], validation: {}, displayOrder: 1 },
  });
  const items = [
    item('FIXTURE_VALUE', 'saved', 'base', 'Fixture value'),
    item('LLM_CHANNELS', 'primary', 'ai_model'),
    item('LLM_PRIMARY_PROTOCOL', 'openai', 'ai_model'),
    item('LLM_PRIMARY_MODELS', 'fixture-model', 'ai_model'),
    item('SCHEDULE_ENABLED', 'false', 'system'),
    item('SCHEDULE_TIME', '18:00', 'system'),
  ];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    // Vite source modules also contain /api/; only intercept HTTP API paths.
    if (!path.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (path === '/api/v1/auth/login') loggedIn = true;
    if (path === '/api/v1/auth/logout') loggedIn = false;
    if (path === '/api/v1/system/config/import') {
      // Replace a generic value without changing the model fingerprint.
      items[0].value = 'imported';
      await route.fulfill({ json: { updatedKeys: ['FIXTURE_VALUE'], configVersion: 'fixture-v2', warnings: [] } });
      return;
    }
    const json = path === '/api/v1/auth/status'
      ? { authEnabled: requireLogin, loggedIn, passwordSet: true, setupState: 'enabled' }
      : path === '/api/v1/system/config'
        ? { configVersion: 'fixture-v1', maskToken: '******', items }
        : path === '/api/v1/system/config/setup/status'
          ? { ready: true, checks: [] }
          : path === '/api/v1/system/scheduler/status'
            ? { enabled: true, running: false, scheduleTimes: ['18:00'] }
            : path.includes('/generation-backends/')
              ? { primaryBackendId: 'litellm', primary: { backendId: 'litellm', available: true }, backends: [] }
              : { success: true, accounts: [], items: [], total: 0, page: 1, page_size: 20 };
    await route.fulfill({ json });
  });
}

test('back/forward and cancel/discard preserve drafts and exact destinations', async ({ page }, testInfo) => {
  await fixture(page);
  await page.goto('/alerts?filter=active#rules');
  await page.getByRole('link', { name: '设置', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Fixture value' });
  await input.fill('unsaved');
  await page.goBack();
  await expect(page.getByRole('heading', { name: '存在未保存的修改' })).toContainText('存在未保存的修改');
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    const path = testInfo.outputPath(`settings-guard-${name}.png`);
    await page.screenshot({ path, fullPage: true, animations: 'disabled' });
    await testInfo.attach(`settings-guard-${name}`, { path, contentType: 'image/png' });
  }
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(input).toHaveValue('unsaved');
  await page.goBack();
  await page.getByRole('button', { name: '放弃并离开', exact: true }).click();
  await expect(page).toHaveURL(/\/alerts\?filter=active#rules$/);
  await page.goForward();
  await expect(input).toHaveValue('saved');
});

test('native reload cancellation preserves drafts and Reset releases the guard', async ({ page }) => {
  await fixture(page);
  await page.goto('/settings');
  const input = page.getByRole('textbox', { name: 'Fixture value' });
  await input.click(); // Ensure sticky user activation for the native unload prompt.
  await input.fill('reload-draft');
  const nativeDialog = page.waitForEvent('dialog');
  // A cancelled reload never reaches page.reload()'s load lifecycle. Trigger
  // the real browser reload without waiting for a navigation that is rejected.
  const triggerReload = page.evaluate(() => window.location.reload());
  const unload = await nativeDialog;
  expect(unload.type()).toBe('beforeunload');
  await unload.dismiss();
  await triggerReload;
  await expect(input).toHaveValue('reload-draft');
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(input).toHaveValue('saved');
  await page.reload();
  await expect(input).toHaveValue('saved');
});

test('invalid LLM drafts and scheduler overrides survive category changes and reset', async ({ page }) => {
  await fixture(page);
  await page.goto('/settings');
  const categories = page.getByRole('navigation', { name: '配置分类' });
  await categories.getByRole('button', { name: /AI 模型/ }).click();
  await page.getByRole('button', { name: /primary/i }).click();
  await page.getByLabel('渠道名称', { exact: true }).fill('');
  await categories.getByRole('button', { name: /基础设置/ }).click();
  await page.getByRole('link', { name: '告警', exact: true }).click();
  await expect(page.getByRole('heading', { name: '存在未保存的修改' })).toContainText('存在未保存的修改');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await categories.getByRole('button', { name: /AI 模型/ }).click();
  await expect(page.getByLabel('渠道名称', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await categories.getByRole('button', { name: /系统设置/ }).click();
  const enabled = page.getByTestId('scheduler-enabled-checkbox');
  await expect(enabled).toBeChecked();
  await enabled.uncheck(); // Saved=false/runtime=true makes this a local override only.
  await categories.getByRole('button', { name: /基础设置/ }).click();
  await page.getByRole('link', { name: '告警', exact: true }).click();
  await expect(page.getByRole('heading', { name: '存在未保存的修改' })).toContainText('存在未保存的修改');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await categories.getByRole('button', { name: /系统设置/ }).click();
  await expect(enabled).not.toBeChecked();
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(enabled).toBeChecked();
  await page.getByRole('link', { name: '告警', exact: true }).click();
  await expect(page).toHaveURL(/\/alerts$/);
});

test('protected deep links survive the data-router login boundary', async ({ page }) => {
  await fixture(page, true);
  await page.goto('/settings?category=system#desktop-version-info');
  await expect(page).toHaveURL(/\/login\?redirect=%2Fsettings%3Fcategory%3Dsystem%23desktop-version-info$/);
  await page.locator('#password').fill('fixture-only-password');
  await page.getByRole('button', { name: '授权进入工作台', exact: true }).click();
  await expect(page).toHaveURL(/\/settings\?category=system#desktop-version-info$/);
  await expect(page.getByTestId('scheduler-enabled-checkbox')).toBeVisible();
});

test('accepted backup import discards hidden model drafts and scheduler overrides', async ({ page }) => {
  await fixture(page, true);
  await page.goto('/settings');
  await page.locator('#password').fill('fixture-only-password');
  await page.getByRole('button', { name: '授权进入工作台', exact: true }).click();
  const categories = page.getByRole('navigation', { name: '配置分类' });
  await categories.getByRole('button', { name: /AI 模型/ }).click();
  await page.getByRole('button', { name: /primary/i }).click();
  await page.getByLabel('渠道名称', { exact: true }).fill('');
  await categories.getByRole('button', { name: /系统设置/ }).click();
  const enabled = page.getByTestId('scheduler-enabled-checkbox');
  await expect(enabled).toBeChecked();
  await enabled.uncheck();
  await page.getByRole('button', { name: '导入 .env', exact: true }).click();
  await expect(page.getByText('导入会覆盖当前草稿', { exact: true })).toBeVisible();
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '继续导入', exact: true }).click();
  await (await chooser).setFiles({ name: 'backup.env', mimeType: 'text/plain', buffer: Buffer.from('FIXTURE_VALUE=imported\n') });
  await expect(page.getByText('已导入 .env 备份并重新加载配置。', { exact: true })).toBeVisible();
  await expect(enabled).toBeChecked();
  await categories.getByRole('button', { name: /AI 模型/ }).click();
  await page.getByRole('button', { name: /primary/i }).click();
  await expect(page.getByLabel('渠道名称', { exact: true })).toHaveValue('primary');
  await categories.getByRole('button', { name: /基础设置/ }).click();
  await expect(page.getByRole('textbox', { name: 'Fixture value' })).toHaveValue('imported');
  await page.getByRole('link', { name: '告警', exact: true }).click();
  await expect(page).toHaveURL(/\/alerts$/);
});

test('logout explicitly confirms draft loss and Cancel preserves the session', async ({ page }, testInfo) => {
  await fixture(page, true);
  let logoutRequests = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/v1/auth/logout') logoutRequests += 1;
  });
  await page.goto('/settings');
  await page.locator('#password').fill('fixture-only-password');
  await page.getByRole('button', { name: '授权进入工作台', exact: true }).click();
  const input = page.getByRole('textbox', { name: 'Fixture value' });
  await input.fill('keep-until-confirmed');
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await expect(page.getByText(/退出会丢弃本页未保存的设置/)).toBeVisible();
  const path = testInfo.outputPath('settings-logout-confirm.png');
  await page.screenshot({ path, fullPage: true, animations: 'disabled' });
  await testInfo.attach('settings-logout-confirm', { path, contentType: 'image/png' });
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(input).toHaveValue('keep-until-confirmed');
  expect(logoutRequests).toBe(0);
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await page.getByRole('button', { name: '确认退出', exact: true }).click();
  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(logoutRequests).toBe(1);
});
