import { fireEvent, render, screen, within } from '@testing-library/react';
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

// 复盘工作台（Issue #1584）：结构化字段可选扩展，旧 payload 渲染保持不变
const workbenchPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'cn',
  language: 'zh',
  title: 'A股市场复盘',
  breadth: {
    upCount: 1800,
    downCount: 3200,
    limitUpCount: 30,
    limitDownCount: 8,
    totalAmount: 15000,
    turnoverUnit: '亿元',
    divergenceDiagnosis: '指数上行但上涨家数占比仅 36%，宽度不足。',
  },
  indices: [{
    code: 'sh000016',
    name: '上证50',
    current: 2700,
    changePct: 0.6,
    high: 2712,
    low: 2680,
    ma5: 2690.5,
    maStatus: { ma5: 'above', ma10: 'above', ma20: 'below' },
    technicalStatus: '站上MA5/MA10，MA20 之下',
    comment: '权重护盘明显',
  }],
  sectors: {
    top: [{ name: '煤炭', changePct: 3.2, leader: '中国神华', leaderChangePct: 5.6, persistence: '强' }],
    bottom: [{ name: '半导体', changePct: -2.8 }],
  },
  summary: {
    temperatureScore: 45,
    temperatureLabel: '震荡',
    marketState: '指数强但个股弱',
    suggestedPosition: '3-5成',
    coreConclusion: '权重护盘、成长杀跌的结构性调整日。',
    structureNote: '上证50明显强于创业板指，权重风格占优。',
  },
  styleRotation: { strong: ['资源'], weak: ['半导体'], comment: '资金切向防御。' },
  catalysts: [{
    newsIndex: 0,
    title: '关税政策调整影响出口',
    nature: '利空',
    scope: '出口链',
    duration: '中期',
    digestion: '部分消化',
  }],
  nextSessionPlan: {
    positionAdvice: '维持3-5成，反弹不加仓',
    focusSectors: ['资源', '电力'],
    avoidSectors: ['高位半导体'],
    keyLevels: ['上证3400得失'],
    riskTriggers: ['宽度回落至40%以下则减仓'],
  },
  dataQuality: { notes: ['指数历史K线缺失（sh000688），均线状态省略。'] },
  sections: [
    { key: 'review_workbench', title: '复盘工作台', markdown: '重复的工作台 markdown 内容' },
    { key: 'section_1', title: '一、盘面总览', markdown: '正文A' },
  ],
};

describe('MarketReviewReportView workbench (Issue #1584)', () => {
  it('renders workbench summary with temperature, state, position and conclusion', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByTestId('workbench-summary')).toBeInTheDocument();
    expect(screen.getByText(/市场温度 45\/100/)).toBeInTheDocument();
    expect(screen.getByText(/市场状态 指数强但个股弱/)).toBeInTheDocument();
    expect(screen.getByText(/建议仓位 3-5成/)).toBeInTheDocument();
    expect(screen.getByText('权重护盘、成长杀跌的结构性调整日。')).toBeInTheDocument();
    expect(screen.getByText(/指数上行但上涨家数占比仅 36%/)).toBeInTheDocument();
    expect(screen.getByText(/走强 资源/)).toBeInTheDocument();
  });

  it('renders MA and comment columns only when indices carry workbench fields', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByText('均线状态')).toBeInTheDocument();
    expect(screen.getByText('站上MA5/MA10，MA20 之下')).toBeInTheDocument();
    expect(screen.getByText('权重护盘明显')).toBeInTheDocument();
  });

  it('renders catalysts table with nature, scope, duration and digestion', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByTestId('workbench-catalysts')).toBeInTheDocument();
    expect(screen.getByText('关税政策调整影响出口')).toBeInTheDocument();
    expect(screen.getByText('利空')).toBeInTheDocument();
    expect(screen.getByText('出口链')).toBeInTheDocument();
    expect(screen.getByText('中期')).toBeInTheDocument();
    expect(screen.getByText('部分消化')).toBeInTheDocument();
  });

  it('renders next session plan and data quality notes', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByTestId('workbench-next-session-plan')).toBeInTheDocument();
    expect(screen.getByText(/维持3-5成，反弹不加仓/)).toBeInTheDocument();
    expect(screen.getByText('资源')).toBeInTheDocument();
    expect(screen.getByText('高位半导体')).toBeInTheDocument();
    expect(screen.getByText('上证3400得失')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-data-quality')).toBeInTheDocument();
    expect(screen.getByText(/指数历史K线缺失/)).toBeInTheDocument();
  });

  it('shows sector leader and persistence in the reference-style sector table', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    const sectorsModule = screen.getByTestId('module-sectors');
    // 强/弱两张表各有一组表头
    expect(within(sectorsModule).getAllByText('板块').length).toBeGreaterThan(0);
    expect(within(sectorsModule).getAllByText('领涨股').length).toBeGreaterThan(0);
    expect(within(sectorsModule).getAllByText('持续性').length).toBeGreaterThan(0);
    expect(within(sectorsModule).getByText('中国神华 +5.60%')).toBeInTheDocument();
    expect(within(sectorsModule).getByText('强')).toBeInTheDocument();
  });

  it('hides the injected workbench markdown section when structured fields exist', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    // 结构化字段存在时，注入的 markdown 工作台段被过滤，避免重复展示
    expect(screen.queryByText('重复的工作台 markdown 内容')).not.toBeInTheDocument();
    expect(screen.getByText('正文A')).toBeInTheDocument();
  });

  it('keeps the injected workbench markdown section on the pure-markdown fallback path', () => {
    const markdownOnlyPayload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'zh',
      title: 'A股市场复盘',
      sections: [
        { key: 'review_workbench', title: '复盘工作台', markdown: '工作台降级 markdown 内容' },
        { key: 'section_1', title: '一、盘面总览', markdown: '正文A' },
      ],
    };

    render(
      <MarketReviewReportView payload={markdownOnlyPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByText('工作台降级 markdown 内容')).toBeInTheDocument();
  });

  it('renders workbench modules once per market for combined payloads', () => {
    const combinedWorkbenchPayload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn,us',
      language: 'zh',
      rootTitle: '大盘复盘',
      markets: {
        cn: {
          title: 'A股市场',
          summary: { temperatureScore: 45, marketState: '震荡分化' },
        },
        us: {
          title: '美股市场',
          summary: { temperatureScore: 72, marketState: '指数强但个股弱' },
        },
      },
    };

    render(
      <MarketReviewReportView payload={combinedWorkbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getAllByTestId('workbench-summary')).toHaveLength(2);
    expect(screen.getByText(/市场温度 45\/100/)).toBeInTheDocument();
    expect(screen.getByText(/市场温度 72\/100/)).toBeInTheDocument();
  });

  it('legacy payload without workbench fields renders exactly as before', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    // 兼容性验收：旧 payload 不出现任何工作台模块与新表头，旧大卡照常渲染
    expect(screen.getByText('结构化大盘数据')).toBeInTheDocument();
    expect(screen.queryByTestId('market-review-modules')).not.toBeInTheDocument();
    expect(screen.queryByTestId('workbench-summary')).not.toBeInTheDocument();
    expect(screen.queryByTestId('workbench-catalysts')).not.toBeInTheDocument();
    expect(screen.queryByTestId('workbench-next-session-plan')).not.toBeInTheDocument();
    expect(screen.queryByTestId('workbench-data-quality')).not.toBeInTheDocument();
    expect(screen.queryByText('均线状态')).not.toBeInTheDocument();
    expect(screen.queryByText('市场温度')).not.toBeInTheDocument();
  });
});

describe('MarketReviewReportView module presentation (Issue #1584)', () => {
  it('renders module cards and hides the legacy mega card for workbench payloads', () => {
    render(
      <MarketReviewReportView payload={workbenchPayload} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByTestId('market-review-modules')).toBeInTheDocument();
    expect(screen.queryByText('结构化大盘数据')).not.toBeInTheDocument();
    for (const testId of ['module-conclusion', 'module-indices', 'module-breadth', 'module-sectors', 'module-catalysts', 'module-plan']) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
    // 模块标题带连续序号（参考截图形态）
    expect(screen.getByText('一、一句话结论')).toBeInTheDocument();
    expect(screen.getByText('二、核心指数表现')).toBeInTheDocument();
    expect(screen.getByText('三、市场宽度与分化')).toBeInTheDocument();
    expect(screen.getByText('五、消息面与政策催化')).toBeInTheDocument();
    expect(screen.getByText('六、明日交易计划')).toBeInTheDocument();
  });

  it('renumbers sequentially when a module is absent', () => {
    const noBreadth: MarketReviewPayload = { ...workbenchPayload, breadth: undefined };
    render(
      <MarketReviewReportView payload={noBreadth} content="# 大盘复盘" reportLanguage="zh" />,
    );

    // 无宽度模块：板块主线顺延为 三、消息催化为 四、明日计划为 五
    expect(screen.queryByTestId('module-breadth')).not.toBeInTheDocument();
    expect(screen.getByText('三、行业板块与题材主线')).toBeInTheDocument();
    expect(screen.getByText('四、消息面与政策催化')).toBeInTheDocument();
    expect(screen.getByText('五、明日交易计划')).toBeInTheDocument();
  });

  it('renders only the conclusion module for a summary-only payload', () => {
    const summaryOnly: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'jp',
      language: 'zh',
      title: '日股大盘复盘',
      indices: [],
      sections: [],
      summary: { marketState: '外围回暖带动修复', marketStateSource: 'llm' },
    };
    render(
      <MarketReviewReportView payload={summaryOnly} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(screen.getByTestId('module-conclusion')).toBeInTheDocument();
    for (const testId of ['module-indices', 'module-breadth', 'module-sectors', 'module-catalysts', 'module-plan']) {
      expect(screen.queryByTestId(testId)).not.toBeInTheDocument();
    }
  });

  it('renders data quality notes for a notes-only payload without summary fields', () => {
    // PR #1888 评审回归：market_light 缺失 + 判读失败的降级形态，
    // 数据说明必须独立于 summary 展示（缺失原因不可丢）
    const notesOnly: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'jp',
      language: 'zh',
      title: '日股大盘复盘',
      indices: [],
      sections: [],
      dataQuality: { notes: ['市场温度缺失', '指数历史K线缺失（^N225）'] },
    };
    render(
      <MarketReviewReportView payload={notesOnly} content="# 大盘复盘" reportLanguage="zh" />,
    );

    const conclusion = screen.getByTestId('module-conclusion');
    expect(within(conclusion).getByTestId('workbench-data-quality')).toBeInTheDocument();
    expect(within(conclusion).getByText('市场温度缺失')).toBeInTheDocument();
    expect(screen.queryByText('结构化大盘数据')).not.toBeInTheDocument();
  });

  it('absorbs matched narrative sections into module cards and keeps unmatched as narrative cards', () => {
    const payloadWithSections: MarketReviewPayload = {
      ...workbenchPayload,
      sections: [
        { key: 'overview', title: 'Overview', markdown: '> 引言判断。' },
        { key: 's1', title: '一、盘面总览', markdown: '总览叙事。' },
        { key: 's2', title: '二、指数结构', markdown: '指数叙事。' },
        { key: 's3', title: '三、板块主线', markdown: '板块叙事。' },
        { key: 's7', title: '七、风险提示', markdown: '风险叙事。' },
      ],
    };
    render(
      <MarketReviewReportView payload={payloadWithSections} content="# 大盘复盘" reportLanguage="zh" />,
    );

    expect(within(screen.getByTestId('module-conclusion')).getByText(/总览叙事/)).toBeInTheDocument();
    expect(within(screen.getByTestId('module-indices')).getByText(/指数叙事/)).toBeInTheDocument();
    expect(within(screen.getByTestId('module-sectors')).getByText(/板块叙事/)).toBeInTheDocument();
    // 未匹配 section 落为叙事卡（模块之外）
    expect(screen.getByText('七、风险提示')).toBeInTheDocument();
    expect(screen.getByText(/风险叙事/)).toBeInTheDocument();
  });

  it('strips transitional injected tables from absorbed prose', () => {
    const transitional: MarketReviewPayload = {
      ...workbenchPayload,
      sections: [
        {
          key: 's2',
          title: '二、指数结构',
          markdown: '指数叙事。\n\n| 指数 | 最新 | 涨跌幅 |\n|--|--|--|\n| 上证指数 | 3400 | -1% |',
        },
      ],
    };
    render(
      <MarketReviewReportView payload={transitional} content="# 大盘复盘" reportLanguage="zh" />,
    );

    const indicesModule = screen.getByTestId('module-indices');
    expect(within(indicesModule).getByText(/指数叙事/)).toBeInTheDocument();
    // 过渡记录中的注入表被剥离，不与模块表重复
    expect(within(indicesModule).queryByText('最新')).not.toBeInTheDocument();
  });

  it('renders per-market module groups in region order for combined payloads', () => {
    const combined: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn,us',
      language: 'zh',
      rootTitle: '大盘复盘',
      markets: {
        us: { title: '美股市场', summary: { temperatureScore: 72, marketState: '指数强但个股弱' } },
        cn: { title: 'A股市场', summary: { temperatureScore: 45, marketState: '震荡分化' } },
      },
    };
    render(
      <MarketReviewReportView payload={combined} content="# 大盘复盘" reportLanguage="zh" />,
    );

    const summaries = screen.getAllByTestId('workbench-summary');
    expect(summaries).toHaveLength(2);
    // cn 组先于 us 组（后端区域顺序，而非对象插入顺序）
    const headings = screen.getAllByText(/A股市场|美股市场/).map((el) => el.textContent);
    expect(headings.indexOf('A股市场')).toBeLessThan(headings.indexOf('美股市场'));
  });

  it('keeps narrative content for a legacy-shaped market inside a mixed multi-market payload', () => {
    // PR #1888 二轮评审回归（防御加固）：一个市场携带工作台字段、另一个
    // 市场只有旧 sections/markdown 形态时，后者的正文不得被静默丢弃
    const mixed: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn,us',
      language: 'zh',
      rootTitle: '大盘复盘',
      markets: {
        cn: { title: 'A股市场', summary: { temperatureScore: 45, marketState: '震荡分化' } },
        us: {
          title: '美股市场',
          sections: [
            { key: 'risk', title: '风险提示', markdown: '美股叙事正文不能丢。' },
            {
              key: 'idx',
              title: '指数点评',
              markdown: '指数走势叙事。\n\n| 指数 | 收盘 |\n|--|--|\n| 标普500 | 6100 |',
            },
          ],
        },
      },
    };
    render(
      <MarketReviewReportView payload={mixed} content="# 大盘复盘" reportLanguage="zh" />,
    );

    // cn 市场按模块渲染
    expect(screen.getByTestId('workbench-summary')).toBeInTheDocument();
    // us 市场（无任何结构化/工作台字段）以叙事卡兜底渲染，标题与正文都在
    expect(screen.getByText('美股市场')).toBeInTheDocument();
    expect(screen.getByText('美股叙事正文不能丢。')).toBeInTheDocument();
    // 兜底市场没有模块数据表，叙事中的表格是唯一载体——不得被剥表逻辑删除
    expect(screen.getByText('标普500')).toBeInTheDocument();
  });

  it('hides insight cards in workbench mode to avoid conflicting scores', () => {
    const report: AnalysisReport = {
      meta: {
        queryId: 'market-review-q-2',
        stockCode: 'MARKET',
        stockName: '大盘复盘',
        reportType: 'market_review',
        reportLanguage: 'zh',
        createdAt: '2026-07-02T08:00:00Z',
      },
      summary: {
        analysisSummary: '整份 markdown 原文……',
        operationAdvice: '',
        trendPrediction: '',
        sentimentScore: 50,
      },
      details: {
        contextSnapshot: { marketReviewPayload: workbenchPayload },
      } as AnalysisReport['details'],
    };
    render(<MarketReviewReportView report={report} reportLanguage="zh" />);

    // 洞察卡（复盘摘要/50 分）不出现；模块①温度是唯一分数
    expect(screen.queryByText('复盘摘要')).not.toBeInTheDocument();
    expect(screen.queryByText('50 / 100')).not.toBeInTheDocument();
    expect(screen.getByText(/市场温度 45\/100/)).toBeInTheDocument();
  });
});
