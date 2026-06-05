import { render, screen } from '@testing-library/react';
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
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
    expect(screen.queryByText('Decliners')).not.toBeInTheDocument();
  });
});
