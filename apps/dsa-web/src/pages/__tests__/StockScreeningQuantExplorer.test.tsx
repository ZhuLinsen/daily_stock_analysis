import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import { toCamelCase } from '../../api/utils';
import type { ScreeningStrategiesResponse } from '../../api/screening';
import { escapeCsvCell } from '../../utils/screeningQuant';
import StockScreeningPage from '../StockScreeningPage';

const {
  enableScreening,
  getHistory,
  getRun,
  getScreeningStatus,
  getHotspotDetail,
  getHotspots,
  getStrategies,
  getScreenTask,
  navigate,
  screenStocks,
  startScreenTask,
} = vi.hoisted(() => {
  let lastScreenResult: unknown = null;
  const screenStocks = vi.fn();
  const startScreenTask = vi.fn(async (payload: unknown) => {
    lastScreenResult = await screenStocks(payload);
    return {
      taskId: 'quant-task-1',
      traceId: 'quant-task-1',
      status: 'pending',
      message: '选股任务已提交',
      strategy: 'momentum_quality',
      market: 'cn',
      maxResults: 5,
    };
  });
  const getScreenTask = vi.fn(async () => ({
    taskId: 'quant-task-1',
    traceId: 'quant-task-1',
    status: 'completed',
    progress: 100,
    message: '任务执行完成',
    result: lastScreenResult,
  }));
  return {
    enableScreening: vi.fn(),
    getHistory: vi.fn(),
    getRun: vi.fn(),
    getScreeningStatus: vi.fn(),
    getHotspotDetail: vi.fn(),
    getHotspots: vi.fn(),
    getStrategies: vi.fn(),
    getScreenTask,
    navigate: vi.fn(),
    screenStocks,
    startScreenTask,
  };
});

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('../../api/screening', () => ({
  screeningApi: {
    enable: () => enableScreening(),
    getStatus: () => getScreeningStatus(),
    getHotspotDetail: (payload: unknown) => getHotspotDetail(payload),
    getHotspots: (payload: unknown) => getHotspots(payload),
    getHistory: (payload: unknown) => getHistory(payload),
    getRun: (runId: string) => getRun(runId),
    getStrategies: () => getStrategies(),
    getScreenTask: () => getScreenTask(),
    screen: (payload: unknown) => screenStocks(payload),
    startScreen: (payload: unknown) => startScreenTask(payload),
  },
}));

const rawSnakeStrategies = {
  enabled: true,
  strategies: [
    {
      id: 'momentum_quality',
      name: '趋势质量',
      title: '趋势质量',
      description: '兼顾趋势确认与基本面质量',
      category: 'framework',
      tag: '趋势',
      tags: ['momentum', 'quality'],
      market_scope: ['cn'],
      requires_daily_features: true,
      active_filters: ['exclude_st', 'amount_min', 'pe_ttm_max', 'volatility_20d_pct_max'],
      factor_weights: {
        momentum: 0.45,
        value: 0.25,
        liquidity: 0.2,
        theme_heat: 0.1,
      },
      style: {
        risk_profile: 'balanced',
        holding_period: 'swing',
      },
    },
  ],
  strategy_count: 1,
};

const sampleScreenResult = {
  enabled: true,
  candidateCount: 2,
  strategy: 'momentum_quality',
  market: 'cn',
  rankingMode: 'factor',
  llmRanked: false,
  candidates: [
    {
      rank: 1,
      code: '600519',
      name: '贵州茅台',
      industry: '白酒',
      price: 1520.0,
      changePct: 1.85,
      amount: 3_500_000_000,
      score: 86.4,
      llmScore: 91.2,
      riskLevel: 'low',
      reason: '稳健现金流与价值低波共震',
      factorScores: {
        momentum: 68.0,
        value: 92.5,
        stability: 90.0,
        liquidity: 94.0,
      },
      raw: {},
    },
    {
      rank: 2,
      code: '300750',
      name: '宁德时代',
      industry: '新能源',
      price: 215.6,
      changePct: 4.35,
      amount: 4_800_000_000,
      score: 82.1,
      llmScore: 84.5,
      riskLevel: 'medium',
      reason: '动量放量走强',
      factorScores: {
        momentum: 95.0,
        value: 70.0,
        stability: 74.0,
        liquidity: 96.0,
      },
      raw: {},
    },
  ],
};

describe('StockScreeningPage Quant Factor Explorer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
    getScreeningStatus.mockResolvedValue({ enabled: true, available: true });
    getStrategies.mockResolvedValue(toCamelCase<ScreeningStrategiesResponse>(rawSnakeStrategies));
    getHotspots.mockResolvedValue({ enabled: true, provider: 'akshare', hotspots: [], hotspotCount: 0 });
    getHistory.mockResolvedValue({ enabled: true, runs: [], runCount: 0 });
    screenStocks.mockResolvedValue(sampleScreenResult);
  });

  it('renders strategy factor weights blueprint, supports search/risk/sort, candidate comparison matrix, and CSV export', async () => {
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-csv');
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      render(<StockScreeningPage />);

      expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
      expect(screen.getByText('日K量化特征增强')).toBeInTheDocument();
      expect(screen.getByText('45%')).toBeInTheDocument();
      expect(screen.getByText('4 项风控/阈值门槛')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
      expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
      expect(screen.getByText('宁德时代')).toBeInTheDocument();

      // Sort by momentum descending -> 300750 (95.0) rises above 600519 (68.0)
      fireEvent.change(screen.getByLabelText('候选排序'), {
        target: { value: 'momentum_desc' },
      });
      const tableRows = screen.getAllByRole('row');
      expect(within(tableRows[1]).getByText('300750')).toBeInTheDocument();

      // Pin first candidate -> compact 1/3 tray appears before full matrix on 2nd pin
      const compareButtons = screen.getAllByRole('button', { name: '+ 对比' });
      fireEvent.click(compareButtons[0]);
      expect(await screen.findByText('已选 1/3 只对比，再选 1 只展开因子矩阵')).toBeInTheDocument();
      fireEvent.click(compareButtons[1]);
      expect(await screen.findByText('候选量化多因子横向对比矩阵')).toBeInTheDocument();
      expect(screen.getByText('AI 重排分')).toBeInTheDocument();
      expect(screen.getByText('91.20')).toBeInTheDocument();
      expect(screen.getByText('95.0')).toBeInTheDocument();

      // Clear comparison cleanly
      fireEvent.click(screen.getByRole('button', { name: '清空对比' }));
      expect(screen.queryByText('候选量化多因子横向对比矩阵')).not.toBeInTheDocument();

      // Filter by risk level & keyword -> updates filtered header count pill
      fireEvent.click(screen.getByRole('button', { name: '仅低风险' }));
      expect(screen.getByText('显示 1 / 2 只候选')).toBeInTheDocument();
      expect(screen.getByText('贵州茅台')).toBeInTheDocument();
      expect(screen.queryByText('宁德时代')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '全部风险' }));
      expect(screen.queryByText('显示 1 / 2 只候选')).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText('按代码、名称或行业过滤候选'), {
        target: { value: '新能源' },
      });
      expect(screen.getByText('显示 1 / 2 只候选')).toBeInTheDocument();
      expect(screen.getByText('宁德时代')).toBeInTheDocument();
      expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();

      // Export CSV
      fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
      await waitFor(() => {
        expect(createObjectUrlSpy).toHaveBeenCalledTimes(1);
        expect(anchorClickSpy).toHaveBeenCalledTimes(1);
        expect(revokeObjectUrlSpy).toHaveBeenCalledWith('blob:mock-csv');
      });
    } finally {
      createObjectUrlSpy.mockRestore();
      revokeObjectUrlSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('localizes quant blueprint, toolbar, comparison matrix, and export controls in English UI mode', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <StockScreeningPage />
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('Strategy Factor Weights & Profile Blueprint')).toBeInTheDocument();
    expect(screen.getByText('Daily-Bar Quant Enriched')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Run screening/i }));
    expect(await screen.findByText('600519')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeInTheDocument();

    const compareButtons = screen.getAllByRole('button', { name: '+ Compare' });
    fireEvent.click(compareButtons[0]);
    fireEvent.click(compareButtons[1]);
    expect(await screen.findByText('Multi-Candidate Quant Factor Comparison Matrix')).toBeInTheDocument();
  });

  it('sanitizes exported CSV filename using displayed run strategy metadata', async () => {
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-csv');
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    let capturedDownload = '';
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        capturedDownload = this.download;
      });

    screenStocks.mockResolvedValueOnce({
      ...sampleScreenResult,
      strategy: 'custom/alpha strategy',
    });

    try {
      render(<StockScreeningPage />);
      expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
      expect(await screen.findByText('贵州茅台')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
      await waitFor(() => {
        expect(capturedDownload).toBe('screening-custom_alpha_strategy-2.csv');
      });
    } finally {
      createObjectUrlSpy.mockRestore();
      revokeObjectUrlSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('escapes formula injection in CSV export while preserving plain signed numbers', () => {
    expect(escapeCsvCell('-2.35')).toBe('"-2.35"');
    expect(escapeCsvCell('+1.85')).toBe('"+1.85"');
    expect(escapeCsvCell('=SUM(A1:A2)')).toBe('"\'=SUM(A1:A2)"');
    expect(escapeCsvCell('-cmd|calc')).toBe('"\'-cmd|calc"');
    expect(escapeCsvCell('@SUM(1,2)')).toBe('"\'@SUM(1,2)"');
  });

  it('sorts score_desc by screenScore (factor composite) rather than blended score and exports matching CSV rows', async () => {
    let capturedBlob: Blob | null = null;
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockImplementation((obj: Blob | MediaSource) => {
      capturedBlob = obj as Blob;
      return 'blob:mock-factor-csv';
    });
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidateCount: 2,
      strategy: 'momentum_quality',
      market: 'cn',
      rankingMode: 'llm',
      llmRanked: true,
      candidates: [
        {
          rank: 1,
          code: '600519',
          name: '贵州茅台',
          industry: '白酒',
          price: 1520.0,
          changePct: 1.0,
          score: 90.0,
          screenScore: 84.0,
          llmScore: 99.0,
          riskLevel: 'low',
          reason: '模型高分领先',
          factorScores: { momentum: 84.0, value: 84.0 },
          raw: {},
        },
        {
          rank: 2,
          code: '300750',
          name: '宁德时代',
          industry: '新能源',
          price: 215.6,
          changePct: 2.0,
          score: 75.0,
          screenScore: 85.0,
          llmScore: 60.0,
          riskLevel: 'medium',
          reason: '因子总分更高',
          factorScores: { momentum: 85.0, value: 85.0 },
          raw: {},
        },
      ],
    });

    try {
      render(<StockScreeningPage />);
      expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
      expect(await screen.findByText('贵州茅台')).toBeInTheDocument();

      // Default rank keeps rank 1 (600519, final score 90) first
      let rows = screen.getAllByRole('row');
      expect(within(rows[1]).getByText('600519')).toBeInTheDocument();

      // Switch to 综合因子分 ↓ (score_desc) -> 300750 (screenScore 85) overtakes 600519 (screenScore 84)
      fireEvent.change(screen.getByLabelText('候选排序'), {
        target: { value: 'score_desc' },
      });
      rows = screen.getAllByRole('row');
      expect(within(rows[1]).getByText('300750')).toBeInTheDocument();
      expect(within(rows[1]).getByText('综合因子分 85.00')).toBeInTheDocument();
      expect(within(rows[2]).getByText('600519')).toBeInTheDocument();
      expect(within(rows[2]).getByText('综合因子分 84.00')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
      await waitFor(() => {
        expect(capturedBlob).not.toBeNull();
        expect(anchorClickSpy).toHaveBeenCalledTimes(1);
      });

      const csvText = await (capturedBlob as unknown as Blob).text();
      const lines = csvText.replace(/^\uFEFF/, '').split('\r\n');
      expect(lines).toHaveLength(3);
      expect(lines[0]).toContain('"评分","综合因子分","AI 重排分"');
      // Row 1 in exported CSV must match sorted order (300750 with original rank 2, score 75.00, screenScore 85.00)
      expect(lines[1]).toContain('"2","300750","宁德时代","新能源","215.60","2.00","75.00","85.00","60.00"');
      expect(lines[2]).toContain('"1","600519","贵州茅台","白酒","1520.00","1.00","90.00","84.00","99.00"');
    } finally {
      createObjectUrlSpy.mockRestore();
      revokeObjectUrlSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('preserves blank Factor Score CSV cell when screenScore is absent without copying blended score', async () => {
    let capturedBlob: Blob | null = null;
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockImplementation((obj: Blob | MediaSource) => {
      capturedBlob = obj as Blob;
      return 'blob:mock-missing-factor-csv';
    });
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidateCount: 1,
      strategy: 'momentum_quality',
      market: 'cn',
      rankingMode: 'llm',
      llmRanked: true,
      candidates: [
        {
          rank: 1,
          code: '600519',
          name: '贵州茅台',
          industry: '白酒',
          price: 1520.0,
          changePct: 1.0,
          score: 90.0,
          llmScore: 99.0,
          riskLevel: 'low',
          reason: '仅含混合终分与AI分',
          factorScores: { momentum: 84.0 },
          raw: {},
        },
      ],
    });

    try {
      render(<StockScreeningPage />);
      expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
      expect(await screen.findByText('贵州茅台')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
      await waitFor(() => {
        expect(capturedBlob).not.toBeNull();
        expect(anchorClickSpy).toHaveBeenCalledTimes(1);
      });

      const csvText = await (capturedBlob as unknown as Blob).text();
      const lines = csvText.replace(/^\uFEFF/, '').split('\r\n');
      expect(lines).toHaveLength(2);
      expect(lines[1]).toContain('"1","600519","贵州茅台","白酒","1520.00","1.00","90.00","","99.00"');
    } finally {
      createObjectUrlSpy.mockRestore();
      revokeObjectUrlSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('mounts cleanly in ZH and EN when auto-selected strategy uses Object.prototype collision keys in style and category', async () => {
    getStrategies.mockResolvedValue(
      toCamelCase<ScreeningStrategiesResponse>({
        enabled: true,
        strategies: [
          {
            id: 'proto_style_strategy',
            name: '原型防护策略',
            title: '原型防护策略',
            description: 'custom style prototype collision regression',
            category: '__proto__',
            market_scope: ['cn'],
            requires_daily_features: false,
            active_filters: [],
            factor_weights: { constructor: 0.6, toString: 0.4 },
            style: {
              risk_profile: '__proto__',
              holding_period: '__proto__',
              market_regime: ['__proto__'],
            },
          },
        ],
        strategy_count: 1,
      }),
    );

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    const { unmount } = render(
      <UiLanguageProvider>
        <StockScreeningPage />
      </UiLanguageProvider>,
    );
    expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
    expect(screen.getAllByText('__proto__').length).toBeGreaterThanOrEqual(3);

    unmount();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <StockScreeningPage />
      </UiLanguageProvider>,
    );
    expect(await screen.findByText('Strategy Factor Weights & Profile Blueprint')).toBeInTheDocument();
    expect(screen.getAllByText('__proto__').length).toBeGreaterThanOrEqual(3);
  });

  it('sorts candidates missing screenScore stably after scored candidates in score_desc without falling back to blended score', async () => {
    let capturedBlob: Blob | null = null;
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL').mockImplementation((obj: Blob | MediaSource) => {
      capturedBlob = obj as Blob;
      return 'blob:mock-partial-factor-csv';
    });
    const revokeObjectUrlSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidateCount: 2,
      strategy: 'momentum_quality',
      market: 'cn',
      rankingMode: 'llm',
      llmRanked: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '平安银行',
          industry: '银行',
          price: 11.2,
          changePct: 0.5,
          score: 90.0,
          llmScore: 95.0,
          riskLevel: 'low',
          reason: '仅有混合终分，无纯因子分',
          factorScores: {},
          raw: {},
        },
        {
          rank: 2,
          code: '300750',
          name: '宁德时代',
          industry: '新能源',
          price: 215.6,
          changePct: 2.0,
          score: 75.0,
          screenScore: 85.0,
          llmScore: 60.0,
          riskLevel: 'medium',
          reason: '有显式纯因子分',
          factorScores: { momentum: 85.0 },
          raw: {},
        },
      ],
    });

    try {
      render(<StockScreeningPage />);
      expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
      expect(await screen.findByText('平安银行')).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText('候选排序'), {
        target: { value: 'score_desc' },
      });

      const rows = screen.getAllByRole('row');
      expect(within(rows[1]).getByText('300750')).toBeInTheDocument();
      expect(within(rows[1]).getByText('综合因子分 85.00')).toBeInTheDocument();
      expect(within(rows[2]).getByText('000001')).toBeInTheDocument();
      expect(within(rows[2]).queryByText(/综合因子分/)).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));
      await waitFor(() => {
        expect(capturedBlob).not.toBeNull();
        expect(anchorClickSpy).toHaveBeenCalledTimes(1);
      });

      const csvText = await (capturedBlob as unknown as Blob).text();
      const lines = csvText.replace(/^\uFEFF/, '').split('\r\n');
      expect(lines).toHaveLength(3);
      expect(lines[1]).toContain('"2","300750","宁德时代","新能源","215.60","2.00","75.00","85.00","60.00"');
      expect(lines[2]).toContain('"1","000001","平安银行","银行","11.20","0.50","90.00","","95.00"');
    } finally {
      createObjectUrlSpy.mockRestore();
      revokeObjectUrlSpy.mockRestore();
      anchorClickSpy.mockRestore();
    }
  });

  it('preserves original candidate order in score_desc when all candidates lack explicit screenScore', async () => {
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidateCount: 2,
      strategy: 'momentum_quality',
      market: 'cn',
      rankingMode: 'llm',
      llmRanked: true,
      candidates: [
        {
          rank: 1,
          code: '000002',
          name: '万科A',
          industry: '地产',
          price: 8.5,
          changePct: 0.2,
          score: 70.0,
          llmScore: 80.0,
          riskLevel: 'medium',
          reason: '无 screenScore 第一行',
          factorScores: {},
          raw: {},
        },
        {
          rank: 2,
          code: '600519',
          name: '贵州茅台',
          industry: '白酒',
          price: 1520.0,
          changePct: 1.0,
          score: 95.0,
          llmScore: 99.0,
          riskLevel: 'low',
          reason: '无 screenScore 第二行',
          factorScores: {},
          raw: {},
        },
      ],
    });

    render(<StockScreeningPage />);
    expect(await screen.findByText('策略因子权重与画像蓝图')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
    expect(await screen.findByText('万科A')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('候选排序'), {
      target: { value: 'score_desc' },
    });

    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('000002')).toBeInTheDocument();
    // Row 2 is the expanded detail row of the auto-expanded first candidate (000002).
    expect(within(rows[3]).getByText('600519')).toBeInTheDocument();
  });
});
