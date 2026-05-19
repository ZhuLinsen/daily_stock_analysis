import { fireEvent, render, screen } from '@testing-library/react';
import type React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertRuleList } from '../AlertRuleList';
import type { AlertRuleItem } from '../../../types/alerts';

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

  it('renders rules, filters, and pagination', () => {
    renderList();

    expect(screen.getByText('茅台价格突破')).toBeInTheDocument();
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.getAllByText('价格突破').length).toBeGreaterThan(0);
    expect(screen.getByText('上破 1800')).toBeInTheDocument();
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

  it('runs test and toggles enabled state', () => {
    renderList();

    fireEvent.click(screen.getByRole('button', { name: '测试' }));
    fireEvent.click(screen.getByRole('button', { name: '停用' }));

    expect(onTest).toHaveBeenCalledWith(rules[0]);
    expect(onToggleEnabled).toHaveBeenCalledWith(rules[0]);
  });

  it('shows loading text only for the active rule operation', () => {
    renderList({ busyRule: { id: 1, action: 'toggle' } });

    expect(screen.getByRole('button', { name: '测试' })).toBeDisabled();
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
