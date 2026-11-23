import type { AnalysisReport } from '../types/analysis';
import type { UiLanguage } from '../i18n/uiText';

export function getSampleAnalysisReport(language: UiLanguage): AnalysisReport {
  if (language === 'en') {
    return {
      meta: {
        queryId: 'sample-demo',
        stockCode: 'AAPL',
        stockName: 'Apple Inc. (Sample)',
        reportType: 'detailed',
        reportLanguage: 'en',
        createdAt: '2026-11-20T08:00:00Z',
        currentPrice: 228.45,
        changePct: 1.42,
        assetType: 'stock',
      },
      summary: {
        analysisSummary:
          'Sample report preview (demo data): Trend remains constructive above short-term moving averages with balanced volume; wait for pullbacks near support rather than chasing breakouts.',
        operationAdvice: 'Watch / Scale in on pullback',
        action: 'watch',
        actionLabel: 'Watch (Sample)',
        trendPrediction: 'Constructive consolidation above key support',
        sentimentScore: 68,
        sentimentLabel: 'Neutral',
      },
      strategy: {
        idealBuy: '$221.50',
        secondaryBuy: '$216.00',
        stopLoss: '$210.00',
        takeProfit: '$242.00',
      },
      details: {
        belongBoards: [
          { name: 'Consumer Tech (Demo)', type: 'industry' },
          { name: 'On-Device AI (Demo)', type: 'concept' },
        ],
      },
    };
  }

  return {
    meta: {
      queryId: 'sample-demo',
      stockCode: '600519',
      stockName: '贵州茅台（示例报告）',
      reportType: 'detailed',
      reportLanguage: 'zh',
      createdAt: '2026-11-20T08:00:00Z',
      currentPrice: 1528.0,
      changePct: 1.35,
      assetType: 'stock',
    },
    summary: {
      analysisSummary:
        '示例报告预览（静态演示数据）：均线系统呈震荡修复结构，缩量回踩短期均线附近承接较好；延续严进纪律，不追高乖离，关注支撑区分批低吸与止损边界。',
      operationAdvice: '震荡观察，回踩支撑区再轻仓关注',
      action: 'watch',
      actionLabel: '观望（示例）',
      trendPrediction: '短期震荡筑底，中期等待放量确认',
      sentimentScore: 66,
      sentimentLabel: '乐观',
    },
    strategy: {
      idealBuy: '1495.00元',
      secondaryBuy: '1460.00元',
      stopLoss: '1425.00元',
      takeProfit: '1620.00元',
    },
    details: {
      belongBoards: [
        { name: '白酒（示例）', type: '行业' },
        { name: '消费龙头（示例）', type: '概念' },
      ],
    },
  };
}
