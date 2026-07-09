import { expect, test, type Page } from '@playwright/test';

// Phase 25.7: runtime validation for the structured four-masters commentary UI.
// Data-dependent: discovers records via the history API and skips when the local
// DB has no report with raw_result.four_masters_commentary (CI-safe, no LLM calls).

const smokePassword = process.env.DSA_WEB_SMOKE_PASSWORD;

async function login(page: Page) {
  test.skip(!smokePassword, 'Set DSA_WEB_SMOKE_PASSWORD to run four-masters e2e.');

  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('#password')).toBeVisible({ timeout: 10_000 });
  await page.locator('#password').fill(smokePassword!);
  const submitButton = page.getByRole('button', { name: /授權進入工作臺|完成設定並登入/ });
  await expect(submitButton).toBeVisible();
  await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes('/api/v1/auth/') && response.ok(),
      { timeout: 15_000 }
    ),
    submitButton.click(),
  ]);
  await page.waitForURL('/', { timeout: 15_000 });
  await page.waitForLoadState('domcontentloaded');
}

interface DiscoveredRecords {
  withCommentary: { id: number; stockName: string } | null;
  etfWithCommentary: { id: number; stockName: string } | null;
  legacy: { id: number; stockName: string } | null;
}

async function discoverRecords(page: Page): Promise<DiscoveredRecords> {
  const listResponse = await page.request.get('/api/v1/history/?limit=30');
  expect(listResponse.ok()).toBeTruthy();
  const list = (await listResponse.json()) as {
    items?: Array<{ id: number; stock_name?: string; stock_code?: string }>;
  };
  const result: DiscoveredRecords = { withCommentary: null, etfWithCommentary: null, legacy: null };

  for (const item of list.items ?? []) {
    if (!item?.id || item.stock_code === 'MARKET') continue;
    if (result.withCommentary && result.etfWithCommentary && result.legacy) break;
    const detailResponse = await page.request.get(`/api/v1/history/${item.id}`);
    if (!detailResponse.ok()) continue;
    const detail = (await detailResponse.json()) as {
      details?: { raw_result?: { four_masters_commentary?: unknown; instrument_type?: string } };
    };
    const raw = detail?.details?.raw_result;
    const entry = { id: item.id, stockName: item.stock_name ?? String(item.stock_code ?? item.id) };
    if (raw?.four_masters_commentary && typeof raw.four_masters_commentary === 'object') {
      if (!result.withCommentary) result.withCommentary = entry;
      if (!result.etfWithCommentary && raw.instrument_type === 'etf') result.etfWithCommentary = entry;
    } else if (!result.legacy) {
      result.legacy = entry;
    }
  }
  return result;
}

async function openReportDrawer(page: Page, stockName: string) {
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');

  // On mobile viewports (md:hidden trigger) the history panel lives behind a
  // "歷史記錄" toggle button and renders in a slide-in drawer overlay.
  const viewport = page.viewportSize();
  if (viewport && viewport.width < 768) {
    const mobileHistoryToggle = page.getByRole('button', { name: '歷史記錄' });
    await expect(mobileHistoryToggle).toBeVisible({ timeout: 10_000 });
    await mobileHistoryToggle.click();
  }

  // Desktop renders a `hidden md:flex` copy of the history list alongside the
  // mobile drawer's copy, so scope to the currently-visible one (`:visible`
  // excludes the desktop pane while the drawer is open on narrow viewports).
  const visibleHistoryItems = page.locator('.home-history-item:visible');
  await expect(visibleHistoryItems.first()).toBeVisible({ timeout: 10_000 });

  const historyItem = visibleHistoryItems.filter({ hasText: stockName }).first();
  await expect(historyItem).toBeVisible({ timeout: 10_000 });
  await historyItem.click();

  const detailedReportButton = page.getByRole('button', { name: '完整分析報告' });
  await expect(detailedReportButton).toBeEnabled({ timeout: 5000 });
  await detailedReportButton.click();
  await expect(page.getByRole('dialog').getByText('完整分析報告').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('report-markdown-body')).toBeVisible({ timeout: 15_000 });
}

test.describe('Four masters commentary structured UI', () => {
  test('renders structured section without duplicating the markdown section', async ({ page }) => {
    await login(page);
    const records = await discoverRecords(page);
    test.skip(!records.withCommentary, 'No local report with four_masters_commentary.');

    await openReportDrawer(page, records.withCommentary!.stockName);

    const section = page.getByTestId('four-masters-commentary');
    await expect(section).toBeVisible();
    await expect(section.getByText('巴菲特視角')).toBeVisible();
    await expect(section.getByText('蒙格視角')).toBeVisible();
    await expect(section.getByText('段永平視角')).toBeVisible();
    await expect(section.getByText('李錄視角')).toBeVisible();
    await expect(section.getByTestId('four-masters-synthesis')).toBeVisible();
    await expect(section.getByText(/本段為投資框架模擬點評/)).toBeVisible();

    // Dedup: the markdown body must not carry its own four-masters section,
    // and the page must contain exactly one section header.
    const markdownText = await page.getByTestId('report-markdown-body').textContent();
    expect(markdownText ?? '').not.toContain('四大師視角補充');
    await expect(page.getByText('四大師視角補充')).toHaveCount(1);

    // Commentary-only: no action CTA inside the section.
    expect(await section.locator('button').count()).toBe(0);

    await section.scrollIntoViewIfNeeded();
    await section.screenshot({ path: '../../reports/evaluation/phase25_7/desktop-four-masters.png' });
  });

  test('ETF report renders the section when payload exists', async ({ page }) => {
    await login(page);
    const records = await discoverRecords(page);
    test.skip(!records.etfWithCommentary, 'No local ETF report with four_masters_commentary.');

    await openReportDrawer(page, records.etfWithCommentary!.stockName);
    await expect(page.getByTestId('four-masters-commentary')).toBeVisible();
    await expect(page.getByText('四大師視角補充')).toHaveCount(1);
  });

  test('legacy report without payload renders unchanged', async ({ page }) => {
    await login(page);
    const records = await discoverRecords(page);
    test.skip(!records.legacy, 'No legacy report available.');

    await openReportDrawer(page, records.legacy!.stockName);
    await expect(page.getByTestId('four-masters-commentary')).toHaveCount(0);
    const bodyText = await page.getByTestId('report-markdown-body').textContent();
    expect(bodyText ?? '').not.toContain('四大師視角補充');
  });

  test('mobile viewport stacks cards without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await login(page);
    const records = await discoverRecords(page);
    test.skip(!records.withCommentary, 'No local report with four_masters_commentary.');

    await openReportDrawer(page, records.withCommentary!.stockName);
    const section = page.getByTestId('four-masters-commentary');
    await section.scrollIntoViewIfNeeded();
    await expect(section).toBeVisible();

    const overflow = await page.evaluate(() => ({
      docScroll: document.documentElement.scrollWidth,
      docClient: document.documentElement.clientWidth,
    }));
    expect(overflow.docScroll).toBeLessThanOrEqual(overflow.docClient + 1);

    // Cards stack in one column on mobile (grid-cols-1)
    const firstCard = page.getByTestId('four-masters-card-buffett');
    const secondCard = page.getByTestId('four-masters-card-munger');
    const firstBox = await firstCard.boundingBox();
    const secondBox = await secondCard.boundingBox();
    expect(firstBox && secondBox && secondBox.y > firstBox.y + firstBox.height - 2).toBeTruthy();

    await page.screenshot({
      path: '../../reports/evaluation/phase25_7/mobile-four-masters.png',
      fullPage: false,
    });
  });
});
