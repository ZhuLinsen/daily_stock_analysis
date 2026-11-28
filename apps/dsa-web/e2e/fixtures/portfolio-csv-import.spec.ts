import { expect, test } from '@playwright/test';

test('direct CSV import displays the skipped-row count', async ({ page }, testInfo) => {
  await page.route('**/api/v1/**', async (route) => {
    switch (new URL(route.request().url()).pathname) {
      case '/api/v1/auth/status':
        return route.fulfill({ json: { auth_enabled: false, logged_in: true } });
      case '/api/v1/portfolio/accounts':
        return route.fulfill({ json: { accounts: [{ id: 1, name: 'Demo', market: 'cn', base_currency: 'CNY' }] } });
      case '/api/v1/portfolio/imports/csv/brokers':
        return route.fulfill({ json: { brokers: [{ broker: 'huatai', aliases: [], display_name: '华泰' }] } });
      case '/api/v1/portfolio/imports/csv/commit':
        return route.fulfill({ json: {
          account_id: 1, record_count: 1, inserted_count: 1, duplicate_count: 0,
          skipped_count: 1, failed_count: 0, dry_run: false, errors: [],
        } });
      default:
        return route.fulfill({ json: { items: [], accounts: [], total: 0 } });
    }
  });

  await page.goto('/portfolio');
  await page.getByRole('combobox').first().selectOption('1');
  await page.getByLabel('选择 CSV').setInputFiles({
    name: 'trades.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from([
      '成交时间,发生日期,证券代码,买卖标志,成交数量,成交均价',
      '09:35:11,2024-01-31,000001,买入,10,7.5',
      '09:36:00,,000001,买入,30,7.7',
    ].join('\n')),
  });
  await page.getByLabel('仅预演（不写入）').uncheck();
  await page.getByRole('button', { name: '提交导入', exact: true }).click();

  const alert = page.getByRole('alert').filter({ hasText: 'CSV 提交结果' });
  await expect(alert).toContainText('写入 1 条');
  await expect(alert).toContainText('跳过 1 条');
  await alert.screenshot({ path: testInfo.outputPath('csv-commit-skipped.png') });
});
