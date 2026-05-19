import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertRuleForm } from '../AlertRuleForm';

describe('AlertRuleForm', () => {
  const onSubmit = vi.fn();

  beforeEach(() => {
    onSubmit.mockReset();
    onSubmit.mockResolvedValue(undefined);
  });

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
