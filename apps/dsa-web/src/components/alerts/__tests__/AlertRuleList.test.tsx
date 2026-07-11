import { fireEvent, render, screen } from '@testing-library/react';
import type React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertRuleList } from '../AlertRuleList';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { AlertRuleItem } from '../../../types/alerts';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

const rules: AlertRuleItem[] = [
  {
    id: 1,
    name: '茅台价格突破',
    targetScope: 'single_symbol',
    target: '600519',
    alertType: 'price_cross',
    parameters: { direction: 'above', price: 1800 },
    severity: 'warning',
    enabled: true,
    source: 'api',
    cooldownUntil: '2099-05-18T10:30:00',
    cooldownActive: true,
    createdAt: '2026-05-18T09:00:00',
    updatedAt: '2026-05-18T09:30:00',
  },
  {
    id: 2,
    name: 'MACD 金叉',
    targetScope: 'single_symbol',
    target: '300750',
    alertType: 'macd_cross',
    parameters: { direction: 'bullish_cross', fastPeriod: 12, slowPeriod: 26, signalPeriod: 9 },
    severity: 'info',
    enabled: true,
    source: 'api',
    cooldownActive: false,
    createdAt: '2026-05-18T09:00:00',
    updatedAt: '2026-05-18T09:30:00',
  },
  {
    id: 3,
    name: 'KDJ 死叉',
    targetScope: 'single_symbol',
    target: '000001',
    alertType: 'kdj_cross',
    parameters: { direction: 'bearish_cross', period: 9, kPeriod: 3, dPeriod: 3 },
    severity: 'warning',
    enabled: true,
    source: 'api',
    cooldownActive: false,
    createdAt: '2026-05-18T09:00:00',
    updatedAt: '2026-05-18T09:30:00',
  },
];

describe('AlertRuleList', () => {
  const onEnabledFilterChange = vi.fn();
  const onAlertTypeFilterChange = vi.fn();
  const onPageChange = vi.fn();
  const onToggleEnabled = vi.fn();
  const onDelete = vi.fn();
  const onTest = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  function renderList(overrides: Partial<React.ComponentProps<typeof AlertRuleList>> = {}) {
    render(
      <AlertRuleList
        rules={rules}
        total={40}
        page={1}
        pageSize={20}
        enabledFilter="all"
        alertTypeFilter="all"
        onEnabledFilterChange={onEnabledFilterChange}
        onAlertTypeFilterChange={onAlertTypeFilterChange}
        onPageChange={onPageChange}
        onToggleEnabled={onToggleEnabled}
        onDelete={onDelete}
        onTest={onTest}
        {...overrides}
      />,
    );
  }

  function renderEnglishList(overrides: Partial<React.ComponentProps<typeof AlertRuleList>> = {}) {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <AlertRuleList
          rules={rules}
          total={40}
          page={1}
          pageSize={20}
          enabledFilter="all"
          alertTypeFilter="all"
          onEnabledFilterChange={onEnabledFilterChange}
          onAlertTypeFilterChange={onAlertTypeFilterChange}
          onPageChange={onPageChange}
          onToggleEnabled={onToggleEnabled}
          onDelete={onDelete}
          onTest={onTest}
          {...overrides}
        />
      </UiLanguageProvider>,
    );
  }

  it('renders rules, filters, and pagination', () => {
    renderList();

    expect(screen.getByText('茅台价格突破')).toBeInTheDocument();
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.getAllByText('价格突破').length).toBeGreaterThan(0);
    expect(screen.getByText('上破 1800')).toBeInTheDocument();
    expect(screen.getAllByText('MACD 金叉/死叉').length).toBeGreaterThan(0);
    expect(screen.getByText('MACD(12,26,9) 金叉')).toBeInTheDocument();
    expect(screen.getByText('KDJ(9,3,3) 死叉')).toBeInTheDocument();
    expect(screen.getByText('冷却中')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('启停状态'), { target: { value: 'enabled' } });
    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'price_cross' } });
    fireEvent.click(screen.getByRole('button', { name: '2' }));

    expect(onEnabledFilterChange).toHaveBeenCalledWith('enabled');
    expect(onAlertTypeFilterChange).toHaveBeenCalledWith('price_cross');
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('uses backend cooldownActive instead of parsing cooldownUntil locally', () => {
    renderList({
      rules: [
        {
          ...rules[0],
          cooldownUntil: '2099-05-18T10:30:00',
          cooldownActive: false,
        },
      ],
    });

    expect(screen.getByText('未冷却')).toBeInTheDocument();
  });

  it('renders portfolio scope labels and child-target cooldown hint', () => {
    renderList({
      rules: [
        {
          id: 4,
          name: '持仓 RSI',
          targetScope: 'portfolio_holdings',
          target: 'all',
          alertType: 'rsi_threshold',
          parameters: { direction: 'below', period: 12, threshold: 30 },
          severity: 'warning',
          enabled: true,
          source: 'api',
          cooldownActive: false,
        },
        {
          id: 5,
          name: '组合止损',
          targetScope: 'portfolio_account',
          target: '9',
          alertType: 'portfolio_stop_loss',
          parameters: { mode: 'breach' },
          severity: 'critical',
          enabled: true,
          source: 'api',
          cooldownActive: false,
        },
      ],
    });

    expect(screen.getByText('持仓标的')).toBeInTheDocument();
    expect(screen.getByText('子目标见触发历史')).toBeInTheDocument();
    expect(screen.getByText('账户 9')).toBeInTheDocument();
    expect(screen.getAllByText('组合止损').length).toBeGreaterThan(0);
    expect(screen.getByText('已触发止损')).toBeInTheDocument();
  });

  it('renders portfolio drawdown alert labels in English UI mode', () => {
    renderEnglishList({
      rules: [
        {
          id: 8,
          name: 'Drawdown rule',
          targetScope: 'portfolio_account',
          target: 'all',
          alertType: 'portfolio_drawdown',
          parameters: {},
          severity: 'warning',
          enabled: true,
          source: 'api',
          cooldownActive: false,
        },
      ],
    });

    expect(screen.getByText('Alert rules')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'All statuses' })).toBeInTheDocument();
    expect(screen.getAllByText('Portfolio drawdown').length).toBeGreaterThan(0);
    expect(screen.getByText('Portfolio account')).toBeInTheDocument();
    expect(screen.getAllByText('Enabled').length).toBeGreaterThan(0);
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.queryByText('组合回撤')).not.toBeInTheDocument();
  });

  it('renders market scope labels, filters, and parameters', () => {
    renderList({
      rules: [
        {
          id: 6,
          name: 'A 股红黄灯',
          targetScope: 'market',
          target: 'cn',
          alertType: 'market_light_status',
          parameters: { statuses: ['red', 'yellow'] },
          severity: 'critical',
          enabled: true,
          source: 'api',
          cooldownActive: false,
        },
        {
          id: 7,
          name: '美股分数下降',
          targetScope: 'market',
          target: 'us',
          alertType: 'market_light_score_drop',
          parameters: { minDrop: 15 },
          severity: 'warning',
          enabled: true,
          source: 'api',
          cooldownActive: false,
        },
      ],
    });

    expect(screen.getByText('A 股')).toBeInTheDocument();
    expect(screen.getByText('美股')).toBeInTheDocument();
    expect(screen.getAllByText('大盘市场').length).toBeGreaterThan(0);
    expect(screen.getAllByText('大盘红绿灯状态').length).toBeGreaterThan(0);
    expect(screen.getByText('红灯 / 黄灯')).toBeInTheDocument();
    expect(screen.getByText('Score 下降 >= 15')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('规则类型'), { target: { value: 'market_light_score_drop' } });

    expect(onAlertTypeFilterChange).toHaveBeenCalledWith('market_light_score_drop');
  });

  it('runs test and toggles enabled state', () => {
    renderList();

    fireEvent.click(screen.getAllByRole('button', { name: '测试' })[0]);
    fireEvent.click(screen.getAllByRole('button', { name: '停用' })[0]);

    expect(onTest).toHaveBeenCalledWith(rules[0]);
    expect(onToggleEnabled).toHaveBeenCalledWith(rules[0]);
  });

  it('shows loading text only for the active rule operation', () => {
    renderList({ busyRule: { id: 1, action: 'toggle' } });

    expect(screen.getAllByRole('button', { name: '测试' })[0]).toBeDisabled();
    expect(screen.getByRole('button', { name: '停用中' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByRole('button', { name: '测试中' })).not.toBeInTheDocument();
  });

  it('confirms deletion before calling onDelete', async () => {
    renderList();

    fireEvent.click(screen.getByLabelText('删除 茅台价格突破'));
    expect(await screen.findByRole('heading', { name: '删除告警规则' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    expect(onDelete).toHaveBeenCalledWith(rules[0]);
  });

  it('shows an empty state for no rules', () => {
    renderList({ rules: [], total: 0 });

    expect(screen.getByText('暂无告警规则')).toBeInTheDocument();
  });
});
