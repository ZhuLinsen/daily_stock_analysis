import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AnalysisReport, MarketReviewPayload } from '../../../types/analysis';
import { MarketReviewReportView } from '../MarketReviewReportView';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

const englishMarketReviewReport: AnalysisReport = {
  meta: {
    queryId: 'market-review-q-1',
    stockCode: 'MARKET',
    stockName: 'Market Review',
    reportType: 'market_review',
    reportLanguage: 'en',
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '',
    operationAdvice: '',
    trendPrediction: '',
    sentimentScore: undefined as unknown as number,
  },
};

const combinedMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'cn,hk',
  language: 'zh',
  rootTitle: '大盘复盘',
  markets: {
    cn: {
      title: 'A股市场',
      breadth: {
        upCount: 3120,
        downCount: 1420,
        limitUpCount: 72,
        limitDownCount: 4,
        totalAmount: 9600,
        turnoverUnit: '亿元',
      },
      indices: [{
        code: '000300',
        name: '沪深300',
        current: 3920.2,
        changePct: 1.2,
        high: 3940.5,
        low: 3860.1,
      }],
      sectors: {
        top: [{ name: '半导体', changePct: 2.35 }],
        bottom: [{ name: '煤炭', changePct: -1.1 }],
      },
      concepts: {
        top: [{ name: '机器人概念', changePct: 4.2 }],
        bottom: [{ name: '转基因', changePct: -2.05 }],
      },
    },
    hk: {
      title: '港股市场',
      breadth: {
        upCount: 680,
        downCount: 410,
        limitUpCount: 0,
        limitDownCount: 0,
        totalAmount: 1180,
        turnoverUnit: '亿港元',
      },
      indices: [{
        code: 'HSI',
        name: '恒生指数',
        current: 18920.4,
        changePct: -0.5,
        high: 19050.2,
        low: 18780.3,
      }],
    },
  },
};

const noBreadthMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'us',
  language: 'en',
  title: 'Market Review',
  rootTitle: 'Market Review',
  indices: [{
    code: 'SPX',
    name: 'S&P 500',
    current: 5200,
    changePct: 0.68,
    high: 5235.2,
    low: 5170.4,
  }],
  sectors: {
    top: [{ name: 'Technology', changePct: 1.9 }],
    bottom: [{ name: 'Energy', changePct: -0.8 }],
  },
  news: [],
  sections: [],
};

describe('MarketReviewReportView', () => {
  it('uses localized summary card labels and fallbacks for English reports', () => {
    render(
      <MarketReviewReportView
        report={englishMarketReviewReport}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Review Summary')).toBeInTheDocument();
    expect(screen.getByText('No review summary yet')).toBeInTheDocument();
    expect(screen.getByText('Market Sentiment')).toBeInTheDocument();
    expect(screen.getByText('No score yet')).toBeInTheDocument();
    expect(screen.getByText('Rotation & Funds')).toBeInTheDocument();
    expect(screen.getByText('No rotation view yet')).toBeInTheDocument();
    expect(screen.getByText('Risks & Watchlist')).toBeInTheDocument();
    expect(screen.getByText('No key observations yet')).toBeInTheDocument();
    expect(screen.queryByText('复盘摘要')).not.toBeInTheDocument();
    expect(screen.queryByText('暂无摘要')).not.toBeInTheDocument();
  });

  it('renders structured data for every market in a combined market review payload', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('A股市场')).toBeInTheDocument();
    expect(screen.getByText('港股市场')).toBeInTheDocument();
    expect(screen.getByText('沪深300')).toBeInTheDocument();
    expect(screen.getByText('恒生指数')).toBeInTheDocument();
    expect(screen.getByText('3120')).toBeInTheDocument();
    expect(screen.getByText('680')).toBeInTheDocument();
  });

  it('renders industry and concept rankings from structured market review payloads', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getAllByText('行业板块')).toHaveLength(2);
    expect(screen.getAllByText('概念板块')).toHaveLength(2);
    expect(screen.getByText('半导体')).toBeInTheDocument();
    expect(screen.getByText('机器人概念')).toBeInTheDocument();
    expect(screen.getByText('+4.20%')).toBeInTheDocument();
    expect(screen.getByText('-2.05%')).toBeInTheDocument();
  });

  it('localizes structured market data labels for Chinese reports', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('结构化大盘数据')).toBeInTheDocument();
    expect(screen.getAllByText('上涨家数')).toHaveLength(2);
    expect(screen.getAllByText('下跌家数')).toHaveLength(2);
    expect(screen.getAllByText('涨停/跌停')).toHaveLength(2);
    expect(screen.getAllByText('成交额')).toHaveLength(2);
    expect(screen.getAllByText('指数')).toHaveLength(2);
    expect(screen.getAllByText('最新')).toHaveLength(2);
    expect(screen.getAllByText('涨跌幅')).toHaveLength(2);
    expect(screen.getAllByText('高/低')).toHaveLength(2);
    expect(screen.queryByText('Structured Market Data')).not.toBeInTheDocument();
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
    expect(screen.queryByText('Index')).not.toBeInTheDocument();
  });

  it('shows "No data" when breadth is not available for a market review payload', () => {
    render(
      <MarketReviewReportView
        payload={noBreadthMarketReviewPayload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Structured Market Data')).toBeInTheDocument();
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByText('S&P 500')).toBeInTheDocument();
    expect(screen.getAllByText('Industry Sectors').length).toBeGreaterThan(0);
    expect(screen.getByText('Technology')).toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
    expect(screen.queryByText('Decliners')).not.toBeInTheDocument();
  });

  it('formats structured market numbers to two decimal places', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: 4327,
        downCount: 1145,
        limitUpCount: 222,
        limitDownCount: 12,
        totalAmount: 36822.49698199988,
        turnoverUnit: 'bn',
      },
      indices: [{
        code: '000001',
        name: 'Shanghai Composite',
        current: 4112.446,
        changePct: 0.44079750937683315,
        high: 4143.314,
        low: 4087.536,
      }],
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('36822.50 bn')).toBeInTheDocument();
    expect(screen.getByText('4112.45')).toBeInTheDocument();
    expect(screen.getByText('0.44%')).toBeInTheDocument();
    expect(screen.getByText('4143.31 / 4087.54')).toBeInTheDocument();
    expect(screen.queryByText(/36822\.496/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.440797/)).not.toBeInTheDocument();
  });

  it('formats string-backed market numbers and hides missing high/low zeros', () => {
    const payload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: '4,327',
        downCount: '1,145',
        limitUpCount: '0',
        limitDownCount: '12',
        totalAmount: '36,822.49698199988',
        turnoverUnit: 'bn',
      },
      indices: [{
        code: '000001',
        name: 'Shanghai Composite',
        current: '4,112.446',
        changePct: '0.44079750937683315%',
        high: 0,
        low: '0',
      }],
    } as unknown as MarketReviewPayload;

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('4327')).toBeInTheDocument();
    expect(screen.getByText('36822.50 bn')).toBeInTheDocument();
    expect(screen.getByText('4112.45')).toBeInTheDocument();
    expect(screen.getByText('0.44%')).toBeInTheDocument();
    expect(screen.queryByText('0.00 / 0.00')).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.440797/)).not.toBeInTheDocument();
  });

  it('opens run flow for historical market review records', () => {
    const onOpenRunFlow = vi.fn();

    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        recordId={7}
        reportLanguage="zh"
        onOpenRunFlow={onOpenRunFlow}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '查看历史记录 7 运行流' }));

    expect(onOpenRunFlow).toHaveBeenCalledWith(7);
  });
});

describe('MarketReviewReportView enhanced structured fields (issue #1584)', () => {
  const enhancedPayload: MarketReviewPayload = {
    version: 1,
    kind: 'market_review',
    region: 'cn',
    language: 'zh',
    title: 'A股大盘复盘',
    rootTitle: '大盘复盘',
    summary: {
      temperature: 45,
      marketStatus: '震荡分化',
      positionAdvice: '0-3成',
      coreConclusion: '权重护盘、成长杀跌，风险偏好回落',
    },
    breadth: {
      upCount: 1500,
      downCount: 3600,
      limitUpCount: 28,
      limitDownCount: 9,
      totalAmount: 11400,
      turnoverUnit: '亿元',
      divergenceDiagnosis: '指数与个股宽度背离，权重护盘特征明显',
    },
    indices: [{
      code: '000001',
      name: '上证指数',
      current: 3372.4,
      changePct: 0.9,
      maStatus: { ma5: 'above', ma10: 'below', ma20: 'above' },
      comment: '上证受MA10压制',
    }],
    styleRotation: { signal: '成长→防御', comment: '银行煤炭获避险资金' },
    catalysts: [
      { title: '降准落地', direction: 'bullish', scope: '全市场', persistence: '中期', digested: true },
      { title: '外围大跌', direction: 'bearish', digested: false },
      { title: '中性事件', direction: 'neutral', digested: null },
    ],
    nextDayPlan: {
      watchlist: ['上证3350支撑', '成交额能否回到1.2万亿'],
      positionAdvice: '维持0-3成，等待宽度修复',
      invalidation: '若上证放量收复MA10则可加至4-5成',
    },
    crossMarketNote: '隔夜美股纳指期货走弱，明日开盘承压概率较高',
    sections: [{ key: 'overview', title: '盘面总览', markdown: '市场震荡分化。' }],
  };

  it('renders enhanced structured fields when present', () => {
    render(
      <MarketReviewReportView
        payload={enhancedPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('市场温度')).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('震荡分化')).toBeInTheDocument();
    expect(screen.getByText('0-3成')).toBeInTheDocument();
    expect(screen.getByText('权重护盘、成长杀跌，风险偏好回落')).toBeInTheDocument();
    expect(screen.getByText('指数与个股宽度背离，权重护盘特征明显')).toBeInTheDocument();
    expect(screen.getByText('5↑ 10↓ 20↑')).toBeInTheDocument();
    expect(screen.getByText('上证受MA10压制')).toBeInTheDocument();
    expect(screen.getByText('成长→防御')).toBeInTheDocument();
    expect(screen.getByText('银行煤炭获避险资金')).toBeInTheDocument();
    expect(screen.getByText('降准落地')).toBeInTheDocument();
    expect(screen.getAllByText('已消化').length).toBeGreaterThan(0);
    expect(screen.getAllByText('未消化').length).toBeGreaterThan(0);
    expect(screen.getByText('上证3350支撑')).toBeInTheDocument();
    expect(screen.getByText('维持0-3成，等待宽度修复')).toBeInTheDocument();
    expect(screen.getByText('若上证放量收复MA10则可加至4-5成')).toBeInTheDocument();
    expect(screen.getByText('隔夜美股纳指期货走弱，明日开盘承压概率较高')).toBeInTheDocument();
  });

  it('keeps legacy rendering untouched when enhanced fields are absent', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('结构化大盘数据')).toBeInTheDocument();
    expect(screen.getByText('3120')).toBeInTheDocument();
    expect(screen.queryByText('市场温度')).not.toBeInTheDocument();
    expect(screen.queryByText('宽度分化诊断')).not.toBeInTheDocument();
    expect(screen.queryByText('消息催化')).not.toBeInTheDocument();
    expect(screen.queryByText('明日计划')).not.toBeInTheDocument();
    expect(screen.queryByText('风格轮动')).not.toBeInTheDocument();
    expect(screen.queryByText('跨市场参考')).not.toBeInTheDocument();
  });

  it('omits the digested badge when the catalyst has no digested flag', () => {
    const { container } = render(
      <MarketReviewReportView
        payload={{
          ...enhancedPayload,
          catalysts: [{ title: '中性事件', direction: 'neutral', digested: null }],
        }}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('中性事件')).toBeInTheDocument();
    expect(screen.queryByText('已消化')).not.toBeInTheDocument();
    expect(screen.queryByText('未消化')).not.toBeInTheDocument();
    expect(container).toBeTruthy();
  });

  it('renders english labels for enhanced structured fields', () => {
    render(
      <MarketReviewReportView
        payload={{
          ...enhancedPayload,
          language: 'en',
          summary: { temperature: 45, marketStatus: 'choppy divergence' },
        }}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Market Temperature')).toBeInTheDocument();
    expect(screen.getByText('Market Status')).toBeInTheDocument();
    expect(screen.getByText('Breadth Divergence')).toBeInTheDocument();
    expect(screen.getByText('Style Rotation')).toBeInTheDocument();
    expect(screen.getByText('News Catalysts')).toBeInTheDocument();
    expect(screen.getByText('Next-Day Plan')).toBeInTheDocument();
    expect(screen.getByText('Cross-Market Note')).toBeInTheDocument();
  });
});
