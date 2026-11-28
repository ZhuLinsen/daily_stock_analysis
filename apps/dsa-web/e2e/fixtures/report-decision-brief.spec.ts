import { expect, test } from '@playwright/test';

test('renders decision brief, strategy synthesis, price range ruler and standalone HTML export controls', async ({ page }, testInfo) => {
  const report = {
    id: 1,
    stock_code: '600519',
    stock_name: '贵州茅台',
    query_id: 'q-brief-1',
    report_type: 'detailed',
    report_language: 'zh',
    created_at: '2026-11-23T09:30:00Z',
    current_price: 1525,
    change_pct: 1.65,
  };

  let exportHtmlRequests = 0;

  await page.addInitScript(() => {
    localStorage.setItem('dsa.uiLanguage', 'zh');
    localStorage.setItem('theme', 'light');
  });

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    switch (url.pathname) {
      case '/api/v1/auth/status':
        return route.fulfill({ json: { authEnabled: false, loggedIn: true, setupState: 'no_password' } });
      case '/api/v1/system/config/setup/status':
        return route.fulfill({ json: { ready: true, checks: [] } });
      case '/api/v1/history': {
        const items = url.searchParams.get('report_type') === 'market_review' ? [] : [report];
        return route.fulfill({ json: { items, total: items.length, page: 1, limit: 20 } });
      }
      case '/api/v1/history/1':
        return route.fulfill({
          json: {
            meta: report,
            summary: {
              analysis_summary: '均线多头排列，业绩稳健增长',
              operation_advice: '买入',
              action: 'buy',
              trend_prediction: '看多',
              sentiment_score: 84,
            },
            strategy: {
              ideal_buy: '1500.00',
              secondary_buy: '1460.00',
              stop_loss: '1420.00',
              take_profit: '1680.00',
            },
            details: {
              context_snapshot: {
                enhanced_context: {
                  realtime: {
                    open: 1505,
                    high: 1532,
                    low: 1498,
                    amplitude: 2.26,
                    volume_ratio: 1.38,
                    turnover_rate: 0.42,
                    pe_ratio: 24.5,
                    pb_ratio: 7.12,
                  },
                },
              },
              raw_result: {
                dashboard: {
                  core_conclusion: {
                    one_sentence: '站稳 20 日均线支撑，回踩理想买点具性价比',
                    time_sensitivity: '本周内有效',
                    position_advice: {
                      no_position: '在 1500 附近分批低吸，跌破止损退出',
                      has_position: '依托 5 日均线持有，目标位分批止盈',
                    },
                  },
                  intelligence: {
                    risk_alerts: ['短期估值波动需防回撤'],
                    positive_catalysts: ['回购方案落地', '渠道库存改善'],
                    earnings_outlook: '季度营收预期稳健',
                    sentiment_summary: '机构关注度回升',
                  },
                  battle_plan: {
                    position_strategy: {
                      suggested_position: '30% 仓位',
                    },
                    action_checklist: [
                      '✅ 均线保持多头排列',
                      '⚠️ 关注成交量能否持续放大',
                    ],
                  },
                  signal_attribution: {
                    technical_indicators: 45,
                    news_sentiment: 20,
                    fundamentals: 25,
                    market_conditions: 10,
                    strongest_bullish_signal: '放量突破 20 日均线',
                    strongest_bearish_signal: '上方前高存在抛压',
                  },
                  strategy_synthesis: {
                    final_signal: 'buy',
                    consensus_level: 'medium',
                    conflict_severity: 'medium',
                    conflict_count: 1,
                    confidence: 0.78,
                    supporting_skills: [
                      { skill_id: 'bull_trend', signal: 'buy', confidence: 0.85 },
                    ],
                    opposing_skills: [
                      { skill_id: 'shrink_pullback', signal: 'sell', confidence: 0.76 },
                    ],
                    summary_params: {
                      opinion_count: 2,
                      invalid_opinion_count: 0,
                    },
                    deliberation: {
                      summary: {
                        minority_view_preserved: true,
                      },
                    },
                  },
                },
              },
            },
          },
        });
      case '/api/v1/history/1/export-html':
        exportHtmlRequests += 1;
        return route.fulfill({
          status: 200,
          contentType: 'text/html; charset=utf-8',
          body: '<!doctype html><html><body>OK</body></html>',
        });
      case '/api/v1/history/1/markdown':
        return route.fulfill({
          json: { content: '# 贵州茅台 (600519)\n\n## 核心结论\n\n站稳均线支撑。' },
        });
      default:
        return route.fulfill({ json: { items: [], accounts: [], tasks: [], skills: [], total: 0 } });
    }
  });

  await page.setViewportSize({ width: 1280, height: 960 });
  await page.goto('/');

  // Overview snapshot, Copy Brief & Export HTML
  const snapshotRegion = page.getByRole('region', { name: '行情与估值快照' });
  await expect(snapshotRegion).toBeVisible({ timeout: 25_000 });
  const titleBox = await page.getByRole('heading', { name: '贵州茅台' }).boundingBox();
  expect(titleBox?.height ?? 999).toBeLessThan(60);
  await expect(snapshotRegion).toContainText('1505.00');
  await expect(snapshotRegion).toContainText('24.5');
  await expect(page.getByRole('button', { name: '复制要点' })).toBeVisible();

  const exportBtn = page.getByRole('button', { name: '导出 HTML' });
  await expect(exportBtn).toBeVisible();

  // Decision Brief + Alert-First + Strategy Synthesis (#2071)
  await expect(page.getByText('决策研报要点')).toBeVisible();
  const riskRegion = page.getByRole('region', { name: '风险预警' });
  await expect(riskRegion).toBeVisible();
  await expect(riskRegion).toContainText('短期估值波动需防回撤');

  const synthesisRegion = page.getByRole('region', { name: '多策略综合' });
  await expect(synthesisRegion).toBeVisible();
  await expect(synthesisRegion).toContainText('综合信号: 买入');
  await expect(synthesisRegion).toContainText('默认多头趋势');
  await expect(synthesisRegion).toContainText('缩量回踩');
  await expect(synthesisRegion).toContainText('已保留高置信度少数派异议');

  // Strategy Price Range Ruler
  const ruler = page.getByRole('img', { name: '价位区间标尺' });
  await expect(ruler).toBeVisible();
  await expect(ruler).toContainText('盈亏比 1:2.25');

  const overviewShot = testInfo.outputPath('report-decision-brief-overview.png');
  await page.screenshot({ path: overviewShot, fullPage: true, animations: 'disabled' });
  await testInfo.attach('Report decision brief overview', { path: overviewShot, contentType: 'image/png' });

  // Export HTML download check
  await exportBtn.click();
  await expect.poll(() => exportHtmlRequests).toBe(1);
  await expect(page.getByRole('button', { name: '已导出' })).toBeVisible();

  // Full Markdown Report Drawer controls
  await page.getByRole('button', { name: '完整分析报告' }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('button', { name: '导出 HTML' })).toBeVisible({ timeout: 10_000 });
  await expect(drawer.getByRole('button', { name: '打印报告' })).toBeVisible();

  const drawerShot = testInfo.outputPath('report-decision-brief-drawer.png');
  await drawer.screenshot({ path: drawerShot, animations: 'disabled' });
  await testInfo.attach('Report markdown drawer controls', { path: drawerShot, contentType: 'image/png' });
});
