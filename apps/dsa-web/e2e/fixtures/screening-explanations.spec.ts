import { expect, test } from '@playwright/test';

const explanation = (code: string, text: string, source: string, quality: string, value?: number) => ({
  code, text, source, quality, ...(value == null ? {} : { value }),
});

for (const state of ['complete', 'local-only', 'inferred', 'awaiting-evidence'] as const) {
  test(`screening explanations: ${state}`, async ({ page }, testInfo) => {
    const whySelected = state === 'awaiting-evidence'
      ? [explanation('selection_outcome', '已进入当前选股候选结果', 'screening', 'observed')]
      : [explanation('top_factors', '核心因子：quality 91.0、value 86.0', 'screening', 'observed')];
    if (state === 'complete' || state === 'inferred') {
      whySelected.unshift(explanation('selection_reason', '模型判断盈利改善值得关注', 'llm', 'inferred'));
      whySelected.push(explanation('llm_thesis', '独立模型论点：现金流改善', 'llm', 'inferred'));
      whySelected.push(explanation('post_analysis_summary', '后分析器提示业绩兑现仍需跟踪', 'post_analyzer:dsa', 'inferred'));
    }
    if (state === 'complete') {
      whySelected.push(explanation('post_analysis_summary', '同文案但来源不同', 'post_analyzer:scorecard', 'observed'));
      whySelected.push(explanation('post_analysis_summary', '同文案但来源不同', 'post_analyzer:external_http', 'inferred'));
    }
    const whyNow = state === 'complete'
      ? [explanation('news', '消息：公司发布季度经营数据', 'fixture_news', 'observed'),
        explanation('quote_change_pct', '涨跌幅：+0.00%', 'realtime_quote', 'observed', 0)]
      : state === 'inferred'
        ? [explanation('llm_catalyst', '模型催化判断：盈利改善可能持续', 'llm', 'inferred')]
        : [explanation('awaiting_evidence', '暂无带来源的价格、消息或事件证据', 'screening', 'unknown')];
    const candidate = {
      rank: 1, code: '600519', name: '演示候选', score: 88, screen_score: 85,
      reason: state === 'complete' || state === 'inferred' ? '模型判断盈利改善值得关注' : '',
      llm_thesis: state === 'complete' || state === 'inferred' ? '独立模型论点：现金流改善' : '',
      risk_summary: '演示风险提示：注意估值波动', risk_level: 'medium', risk_flags: [],
      industry: '消费', price: 100, change_pct: 0, amount: 0,
      factor_scores: state === 'awaiting-evidence' ? {} : { quality: 91, value: 86 },
      dsa_news: state === 'complete' ? [{ title: '公司发布季度经营数据', source: 'fixture_news', published_date: '2026-10-01' }] : [],
      dsa_context: state === 'complete' ? { quote: { change_pct: 0 } } : {},
      llm_catalysts: state === 'inferred' ? ['盈利改善可能持续'] : [],
      post_analysis_summaries: state === 'complete' || state === 'inferred'
        ? { dsa: '后分析器提示业绩兑现仍需跟踪', ...(state === 'complete' ? { scorecard: '同文案但来源不同', external_http: '同文案但来源不同' } : {}) } : {},
      why_selected: whySelected, why_now: whyNow,
      explanation_quality: {
        why_selected: state === 'complete' || state === 'inferred' ? 'partial' : 'ok',
        why_now: state === 'complete' ? 'ok' : state === 'inferred' ? 'partial' : 'unknown',
      }, raw: {},
    };
    const result = {
      enabled: true, candidates: [candidate], candidate_count: 1, run_id: `fixture-${state}`,
      strategy: 'quality_value', market: 'cn', snapshot_count: 100, after_filter_count: 10,
      llm_ranked: state === 'complete' || state === 'inferred',
      ranking_mode: state === 'complete' || state === 'inferred' ? 'llm' : 'factor',
      warnings: [], source_errors: [],
    };
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      let json: unknown = { items: [], total: 0 };
      if (path.endsWith('/auth/status')) json = { authEnabled: false, loggedIn: true, setupState: 'no_password' };
      else if (path.endsWith('/screening/status')) json = { enabled: true, available: true };
      else if (path.endsWith('/screening/strategies')) json = {
        enabled: true, strategy_count: 1, strategies: [{
          id: 'quality_value', name: 'Quality Value', title: '质量价值', description: '确定性因子与带来源的解释演示',
          category: 'value', market_scope: ['cn'],
        }],
      };
      else if (path.endsWith('/screening/hotspots')) json = { enabled: true, provider: 'fixture', hotspots: [], hotspot_count: 0 };
      else if (path.endsWith('/screening/history')) json = { runs: [] };
      else if (path.endsWith('/screening/screen/tasks')) json = {
        task_id: `fixture-${state}`, status: 'pending', message: 'Fixture task accepted',
        strategy: 'quality_value', market: 'cn', max_results: 10,
      };
      else if (path.endsWith(`/screening/screen/tasks/fixture-${state}`)) json = {
        task_id: `fixture-${state}`, status: 'completed', progress: 100, result,
      };
      await route.fulfill({ json });
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/screening');
    const run = page.getByRole('button', { name: '运行选股', exact: true });
    await expect(run).toBeEnabled();
    await run.click();
    // The first candidate is expanded automatically when a task completes.
    await expect(page.getByRole('button', { name: '收起', exact: true })).toBeVisible();
    const selected = page.getByText('为什么入选', { exact: true }).locator('..');
    const now = page.getByText('为什么现在', { exact: true }).locator('..');
    await expect(selected).toBeVisible();
    await expect(now).toBeVisible();
    await expect(page.getByText(candidate.risk_summary, { exact: true })).toBeVisible();
    await expect(selected).not.toContainText(candidate.risk_summary);
    for (const [card, items] of [[selected, whySelected], [now, whyNow]] as const) {
      await expect(card.getByRole('listitem')).toHaveCount(items.length);
      for (const item of items) {
        const row = card.getByRole('listitem').filter({ has: page.getByText(item.text, { exact: true }) })
          .filter({ has: page.getByText(`来源：${item.source} · 质量：${item.quality}`, { exact: true }) });
        await expect(row).toHaveCount(1);
        await expect(row).toBeVisible();
      }
    }
    await expect(selected.getByText(`综合质量：${candidate.explanation_quality.why_selected}`, { exact: true })).toBeVisible();
    await expect(now.getByText(`综合质量：${candidate.explanation_quality.why_now}`, { exact: true })).toBeVisible();
    if (state === 'complete' || state === 'inferred') {
      await expect(selected).toContainText('post_analyzer:dsa');
      await expect(selected).toContainText('llm');
    } else {
      await expect(now).not.toContainText('涨跌幅：');
    }
    const section = page.locator('section').filter({ has: page.getByRole('heading', { name: '选股结果', exact: true }) });
    const screenshot = testInfo.outputPath(`screening-${state}-1440.png`);
    await section.screenshot({ path: screenshot, animations: 'disabled' });
    await testInfo.attach(state, { path: screenshot, contentType: 'image/png' });
    await page.getByRole('button', { name: '收起', exact: true }).click();
    await expect(selected).toHaveCount(0);
    await page.getByRole('button', { name: '展开查看', exact: true }).click();
    await expect(selected).toContainText(whySelected[0].text);
  });
}

test('legacy history restores a summary without inventing provenance', async ({ page }, testInfo) => {
  let taskRequests = 0;
  const summary = { run_id: 'legacy-run', strategy: 'quality_value', market: 'cn', candidate_count: 1 };
  await page.addInitScript(() => {
    sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'legacy-task', runId: 'legacy-run', strategy: 'quality_value', market: 'cn', maxResults: 3,
    }));
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    let json: unknown = { items: [], total: 0 };
    if (path.endsWith('/auth/status')) json = { authEnabled: false, loggedIn: true, setupState: 'no_password' };
    else if (path.endsWith('/screening/status')) json = { enabled: true, available: true };
    else if (path.endsWith('/screening/strategies')) json = {
      enabled: true, strategy_count: 1, strategies: [{ id: 'quality_value', name: 'Quality Value', description: '历史结果兼容', market_scope: ['cn'] }],
    };
    else if (path.endsWith('/screening/hotspots')) json = { enabled: true, hotspots: [], hotspot_count: 0 };
    else if (path.endsWith('/screening/history')) json = { enabled: true, runs: [summary], run_count: 1 };
    else if (path.endsWith('/screening/history/legacy-run')) json = {
      ...summary, enabled: true, result: {
        ...summary, enabled: true, candidates: [{
          rank: 1, code: '600519', name: '旧版候选', reason: '旧版保存的估值理由', score: 88,
          factor_scores: { topic_alignment: 99 }, change_pct: 0, amount: 0, raw: {},
        }],
      },
    };
    else if (path.includes('/screening/screen/tasks')) taskRequests += 1;
    await route.fulfill({ json });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/screening');
  const selected = page.getByText('为什么入选', { exact: true }).locator('..');
  const now = page.getByText('为什么现在', { exact: true }).locator('..');
  await expect(selected).toContainText('历史摘要（来源未记录）：旧版保存的估值理由');
  await expect(selected).toContainText('来源：legacy_result · 质量：unknown');
  await expect(selected).not.toContainText('核心因子');
  await expect(now).toContainText('暂无带来源的价格、消息或事件证据');
  await expect(now).not.toContainText('涨跌幅：');
  expect(taskRequests).toBe(0);
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: '选股结果', exact: true }) });
  const screenshot = testInfo.outputPath('screening-legacy-history-1440.png');
  await section.screenshot({ path: screenshot, animations: 'disabled' });
  await testInfo.attach('legacy-history', { path: screenshot, contentType: 'image/png' });
});
