import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { AlertRuleForm } from '../AlertRuleForm';

const { getAccounts } = vi.hoisted(() => ({
  getAccounts: vi.fn(),
}));

vi.mock('../../../api/portfolio', () => ({
  portfolioApi: {
    getAccounts,
  },
}));

describe('AlertRuleForm', () => {
  const onSubmit = vi.fn();

  beforeEach(() => {
    onSubmit.mockReset();
    onSubmit.mockResolvedValue(undefined);
    getAccounts.mockReset();
    window.localStorage.clear();
    getAccounts.mockResolvedValue({ accounts: [{ id: 9, name: 'Main', market: 'us', baseCurrency: 'USD', isActive: true }] });
  });

  function renderEnglishForm() {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <AlertRuleForm onSubmit={onSubmit} />
      </UiLanguageProvider>,
    );
  }

  it('submits a price_cross rule payload', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('规则名称'), { target: { value: '茅台价格突破' } });
    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '1800' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        name: '茅台价格突破',
        targetScope: 'single_symbol',
        target: '600519',
        alertType: 'price_cross',
        parameters: { direction: 'above', price: 1800 },
        severity: 'warning',
        enabled: true,
      });
    });
  });

  it('submits a price_change_percent rule payload', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'price_change_percent' } });
    fireEvent.change(screen.getByLabelText('方向'), { target: { value: 'down' } });
    fireEvent.change(screen.getByLabelText('涨跌幅阈值（%）'), { target: { value: '3.5' } });
    fireEvent.change(screen.getByLabelText('严重级别'), { target: { value: 'critical' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        target: 'AAPL',
        alertType: 'price_change_percent',
        parameters: { direction: 'down', changePct: 3.5 },
        severity: 'critical',
      }));
    });
  });

  it('submits a volume_spike rule payload and supports disabled creation', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'msft' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'volume_spike' } });
    fireEvent.change(screen.getByLabelText('成交量放大倍数'), { target: { value: '2.5' } });
    fireEvent.click(screen.getByLabelText('创建后立即启用'));
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        target: 'MSFT',
        alertType: 'volume_spike',
        parameters: { multiplier: 2.5 },
        enabled: false,
      }));
    });
  });

  it('submits technical indicator rule payloads', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'macd_cross' } });
    fireEvent.change(screen.getByLabelText('交叉方向'), { target: { value: 'bearish_cross' } });
    fireEvent.change(screen.getByLabelText('快线周期'), { target: { value: '6' } });
    fireEvent.change(screen.getByLabelText('慢线周期'), { target: { value: '13' } });
    fireEvent.change(screen.getByLabelText('信号周期'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        target: '600519',
        alertType: 'macd_cross',
        parameters: {
          direction: 'bearish_cross',
          fastPeriod: 6,
          slowPeriod: 13,
          signalPeriod: 5,
        },
      }));
    });
  });

  it('rejects invalid technical indicator boundaries before submit', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'rsi_threshold' } });
    fireEvent.change(screen.getByLabelText('RSI 阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('RSI 阈值必须在 0 到 100 之间');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects indicator period combinations that exceed fetchable history', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'macd_cross' } });
    fireEvent.change(screen.getByLabelText('快线周期'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('慢线周期'), { target: { value: '250' } });
    fireEvent.change(screen.getByLabelText('信号周期'), { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('MACD 周期组合需要 501 根日线，最多支持 365 根');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects empty required technical indicator thresholds before submit', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'rsi_threshold' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('RSI 阈值不能为空');
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'cci_threshold' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('CCI 阈值不能为空');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects invalid numeric thresholds before submit', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('价格阈值必须是大于 0 的数字');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects invalid stock code format before submit', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl-2026' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(screen.getByRole('alert')).toHaveTextContent('股票代码格式不正确');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('filters alert types and submits a watchlist rule payload', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'watchlist' } });
    expect(screen.queryByText('组合止损')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        targetScope: 'watchlist',
        target: 'default',
        alertType: 'price_cross',
        parameters: { direction: 'above', price: 10 },
      }));
    });
  });

  it('loads accounts and submits portfolio stop-loss mode', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'portfolio_account' } });
    await waitFor(() => expect(getAccounts).toHaveBeenCalledWith(false));
    expect(screen.queryByText('价格突破')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('账户'), { target: { value: '9' } });
    fireEvent.change(screen.getByLabelText('止损模式'), { target: { value: 'breach' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        targetScope: 'portfolio_account',
        target: '9',
        alertType: 'portfolio_stop_loss',
        parameters: { mode: 'breach' },
      }));
    });
  });

  it('renders portfolio alert type options in English UI mode', async () => {
    renderEnglishForm();

    fireEvent.change(screen.getByLabelText('Target scope'), { target: { value: 'portfolio_account' } });

    await waitFor(() => expect(getAccounts).toHaveBeenCalledWith(false));
    expect(screen.getByRole('option', { name: 'Portfolio drawdown' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Portfolio stop loss' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Info' })).toBeInTheDocument();
    expect(screen.queryByText('组合回撤')).not.toBeInTheDocument();
  });

  it('keeps JP/KR out of market light options in Chinese UI mode', () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'market' } });

    expect(screen.getByRole('option', { name: 'A 股（cn）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '港股（hk）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '美股（us）' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '日股（jp）' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '韩股（kr）' })).not.toBeInTheDocument();
  });

  it('submits a market light status rule payload', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'market' } });
    expect(screen.getByRole('option', { name: 'A 股（cn）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '港股（hk）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '美股（us）' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '日股（jp）' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '韩股（kr）' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('市场区域'), { target: { value: 'hk' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        targetScope: 'market',
        target: 'hk',
        alertType: 'market_light_status',
        parameters: { statuses: ['red', 'yellow'] },
      }));
    });
  });

  it('keeps JP/KR out of market light options in English UI mode', () => {
    renderEnglishForm();

    fireEvent.change(screen.getByLabelText('Target scope'), { target: { value: 'market' } });

    expect(screen.getByRole('option', { name: 'A-shares (cn)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Hong Kong (hk)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'US (us)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Japan (jp)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Korea (kr)' })).not.toBeInTheDocument();
  });

  it('submits a market light score-drop rule payload', async () => {
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'market' } });
    fireEvent.change(screen.getByLabelText('市场区域'), { target: { value: 'us' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'market_light_score_drop' } });
    fireEvent.change(screen.getByLabelText('Score 下降阈值'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        targetScope: 'market',
        target: 'us',
        alertType: 'market_light_score_drop',
        parameters: { minDrop: 12 },
      }));
    });
  });

  it('keeps all account option when account loading fails', async () => {
    getAccounts.mockRejectedValueOnce(new Error('boom'));
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('目标范围'), { target: { value: 'portfolio_holdings' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
    expect(screen.getByLabelText('账户')).toHaveValue('all');
  });

  it('keeps form values when submit reports failure', async () => {
    onSubmit.mockResolvedValueOnce(false);
    render(<AlertRuleForm onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(screen.getByLabelText('标的代码')).toHaveValue('aapl');
    expect(screen.getByLabelText('价格阈值')).toHaveValue(200);
  });
});
