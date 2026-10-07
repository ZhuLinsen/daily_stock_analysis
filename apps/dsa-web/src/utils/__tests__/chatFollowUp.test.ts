import { describe, expect, test } from 'vitest';

import { buildChatFollowUpContext } from '../chatFollowUp';
import type { AnalysisReport } from '../../types/analysis';

describe('chat follow-up context', () => {
  test.each([
    ['600519', '300750', undefined, undefined, false],
    ['005930.KS', '005930.KQ', undefined, undefined, false],
    ['sh000001', '000001', undefined, 'stock', false],
    ['sh000001', 'sh000001', 'index', 'stock', false],
    ['sh000001', 'SH000001', 'index', 'index', true],
    ['005930.KS', '005930.KS', 'stock', 'stock', true],
    ['600519', '600519', undefined, undefined, true],
  ] as const)('only attaches the report for matching identity %s / %s', (code, reportCode, type, reportType, matches) => {
    const report = { meta: { stockCode: reportCode, assetType: reportType },
      summary: { analysisSummary: 'report for this identity' },
      strategy: { buyPrice: 'controlled' }, details: { marketStructure: { status: 'ok' } },
    } as unknown as AnalysisReport;
    const context = buildChatFollowUpContext(code, null, report, [], type);
    expect('previous_analysis_summary' in context).toBe(matches);
    expect('previous_strategy' in context).toBe(matches);
    expect('market_structure_context' in context).toBe(matches);
  });

  test('uses exact registry identity aliases without conflating SH and SZ stocks', () => {
    const index = [{ canonicalCode: '000001.SZ', displayCode: '000001', assetType: 'stock' as const }];
    const report = { meta: { stockCode: '000001.SZ', assetType: 'stock' },
      summary: { analysisSummary: 'stock report' } } as AnalysisReport;
    expect(buildChatFollowUpContext('000001', null, report, index)).toHaveProperty('previous_analysis_summary');
    expect(buildChatFollowUpContext('SZ000001', null, report, index)).toHaveProperty('previous_analysis_summary');
    expect(buildChatFollowUpContext('SH000001', null, report, index)).not.toHaveProperty('previous_analysis_summary');
  });
  test('includes market_structure_context in snake_case for history follow-up', () => {
    const report = {
      meta: {
        queryId: 'q-123',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'full',
        createdAt: '2026-07-05T00:00:00Z',
      },
      summary: {
        analysisSummary: 'summary',
        operationAdvice: '持有',
        trendPrediction: '中性',
        sentimentScore: 55,
      },
      details: {
        marketStructure: {
          schemaVersion: 'market-structure-v1',
          status: 'ok',
          market: 'A股',
          tradeDate: '2026-07-04',
          marketThemeContext: {
            schemaVersion: 'market-theme-v1',
            status: 'ok',
            market: 'A股',
            activeThemes: [{ name: 'AI', changePct: 1.2 }],
            leadingIndustries: [{ name: '白酒', changePct: 0.8 }],
          },
          stockMarketPosition: {
            schemaVersion: 'stock-market-position-v1',
            status: 'ok',
            stockCode: '600519',
            stockRole: 'leader',
            themePhase: 'warming',
            primaryTheme: {
              name: 'AI',
              phase: 'warming',
            },
          },
        },
      },
    } as AnalysisReport;

    const context = buildChatFollowUpContext('600519', '贵州茅台', report);

    expect(context).toMatchObject({
      stock_code: '600519',
      stock_name: '贵州茅台',
      market_structure_context: expect.objectContaining({
        schema_version: 'market-structure-v1',
        market: 'A股',
        trade_date: '2026-07-04',
        status: 'ok',
        market_theme_context: expect.objectContaining({
          schema_version: 'market-theme-v1',
          status: 'ok',
          market: 'A股',
          active_themes: [{ name: 'AI', change_pct: 1.2 }],
          leading_industries: [{ name: '白酒', change_pct: 0.8 }],
        }),
        stock_market_position: expect.objectContaining({
          schema_version: 'stock-market-position-v1',
          status: 'ok',
          stock_code: '600519',
          stock_role: 'leader',
          theme_phase: 'warming',
          primary_theme: expect.objectContaining({
            name: 'AI',
            phase: 'warming',
          }),
        }),
      }),
    });
  });

  test('omits market_structure_context when history report has none', () => {
    const report = {
      meta: {
        queryId: 'q-456',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'full',
        createdAt: '2026-07-05T00:00:00Z',
      },
      summary: {
        analysisSummary: 'summary',
        operationAdvice: '持有',
        trendPrediction: '中性',
        sentimentScore: 55,
      },
      details: {},
    } as AnalysisReport;

    const context = buildChatFollowUpContext('600519', '贵州茅台', report);

    expect(context).not.toHaveProperty('market_structure_context');
  });
});
