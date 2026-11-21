import { expect, test } from '@playwright/test';

test('tool failures stay visible after a successful final response', async ({ page }, testInfo) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    let json: unknown = { items: [], total: 0 };
    if (path.endsWith('/auth/status')) json = { authEnabled: false, loggedIn: true };
    if (path.endsWith('/agent/status')) json = { backend: 'litellm', available: true };
    if (path.endsWith('/agent/skills')) json = { skills: [], default_skill_id: null };
    if (path.endsWith('/agent/chat/sessions')) json = { sessions: [] };
    if (path.endsWith('/agent/chat/stream')) {
      const request = route.request().postDataJSON();
      const events = [
        {
          type: 'accepted', backend: 'litellm', request_id: request.request_id,
          session_id: request.session_id, active_stock_context: null,
          session_state_version: 1, session_generation: 'fixture-generation',
          session_state: { selected_skill_ids: [] },
        },
        { type: 'tool_done', tool: 'get_realtime_quote', display_name: 'Quote unavailable', success: false, duration: 0.1 },
        { type: 'tool_done', tool: 'get_realtime_quote', display_name: 'Cached quote failure', success: false, duration: 0 },
        { type: 'tool_done', tool: 'search_stock_news', display_name: 'News provider failure', success: false, duration: 0.1 },
        { type: 'tool_done', tool: 'search_stock_news', display_name: 'Successful empty search', success: true, duration: 0.1 },
        { type: 'done', success: true, content: 'Data unavailable; wait for confirmation.', total_steps: 3 },
      ];
      await route.fulfill({
        contentType: 'text/event-stream',
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      });
      return;
    }
    await route.fulfill({ json });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/chat');
  await page.getByRole('textbox').fill('Analyze AAPL');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText('Data unavailable; wait for confirmation.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /4 个工具调用/ }).click();
  await expect(page.locator('.chat-progress-item-danger')).toHaveCount(3);
  await expect(page.locator('.chat-progress-item-success')).toHaveCount(1);
  await expect(page.locator('.chat-progress-item-success')).toContainText('Successful empty search');
  await page.screenshot({ path: testInfo.outputPath('agent-tool-outcome-status.png'), animations: 'disabled' });
});
