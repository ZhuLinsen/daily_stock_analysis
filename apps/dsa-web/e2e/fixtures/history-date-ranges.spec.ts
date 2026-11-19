import { expect, test } from '@playwright/test';

test.use({ timezoneId: 'America/New_York' });

for (const { instant, today, start30, start90 } of [
  { instant: '2026-03-10T15:30:00Z', today: '2026-03-10', start30: '2026-02-08', start90: '2025-12-10' },
  { instant: '2026-11-02T16:30:00Z', today: '2026-11-03', start30: '2026-10-04', start90: '2026-08-05' },
]) {
  test(`dashboard requests Shanghai calendar ranges on ${today} across a browser DST change`, async ({ page }) => {
    await page.clock.setFixedTime(new Date(instant));
    await page.route('**/api/v1/**', route => {
      if (new URL(route.request().url()).pathname === '/api/v1/auth/status') {
        return route.fulfill({ json: { authEnabled: false, loggedIn: true, setupState: 'disabled' } });
      }
      return route.fulfill({ json: { items: [], tasks: [], total: 0, page: 1 } });
    });

    const [history, stockBar] = await Promise.all([
      page.waitForRequest(request => {
        const url = new URL(request.url());
        return url.pathname === '/api/v1/history' && url.searchParams.get('end_date') === today;
      }),
      page.waitForRequest('**/api/v1/history/stocks?*'),
      page.goto('/'),
    ]);

    expect(new URL(history.url()).searchParams.get('start_date')).toBe(start30);
    const stockBarParams = new URL(stockBar.url()).searchParams;
    expect(stockBarParams.get('start_date')).toBe(start90);
    expect(stockBarParams.get('end_date')).toBe(today);
  });
}
