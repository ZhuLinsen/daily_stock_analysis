import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsField } from '../SettingsField';

describe('SettingsField', () => {
  it('renders sensitive field metadata and validation errors', () => {
    const onChange = vi.fn();

    render(
      <SettingsField
        item={{
          key: 'OPENAI_API_KEY',
          value: 'secret',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'OPENAI_API_KEY',
            category: 'ai_model',
            dataType: 'string',
            uiControl: 'password',
            isSensitive: true,
            isRequired: true,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        }}
        value="secret"
        onChange={onChange}
        issues={[
          {
            key: 'OPENAI_API_KEY',
            code: 'required',
            message: 'API Key 必填',
            severity: 'error',
          },
        ]}
      />
    );

    expect(screen.getByText('敏感')).toBeInTheDocument();
    expect(screen.getByText('API Key 必填')).toBeInTheDocument();

    const input = screen.getByLabelText('OpenAI API Key');
    fireEvent.focus(input);
    fireEvent.change(input, {
      target: { value: 'updated-secret' },
    });

    expect(onChange).toHaveBeenCalledWith('OPENAI_API_KEY', 'updated-secret');
  });

  it('renders multi-value sensitive fields with external delete actions', () => {
    const onChange = vi.fn();

    render(
      <SettingsField
        item={{
          key: 'OPENAI_API_KEYS',
          value: 'secret-a,secret-b',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'OPENAI_API_KEYS',
            category: 'ai_model',
            dataType: 'string',
            uiControl: 'password',
            isSensitive: true,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: { multiValue: true },
            displayOrder: 1,
          },
        }}
        value="secret-a,secret-b"
        onChange={onChange}
      />
    );

    expect(screen.getAllByRole('button', { name: '显示内容' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: '删除' })).toHaveLength(2);
  });

  it('allows optional select fields to be cleared when schema provides an empty option', () => {
    const onChange = vi.fn();

    render(
      <SettingsField
        item={{
          key: 'NOTIFICATION_MIN_SEVERITY',
          value: 'warning',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'NOTIFICATION_MIN_SEVERITY',
            title: 'Notification Minimum Severity',
            category: 'notification',
            dataType: 'string',
            uiControl: 'select',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [
              { label: 'Not set', value: '' },
              { label: 'info', value: 'info' },
              { label: 'warning', value: 'warning' },
              { label: 'error', value: 'error' },
              { label: 'critical', value: 'critical' },
            ],
            validation: { enum: ['', 'info', 'warning', 'error', 'critical'] },
            displayOrder: 69,
          },
        }}
        value="warning"
        onChange={onChange}
      />
    );

    const select = screen.getByLabelText('NOTIFICATION_MIN_SEVERITY');
    expect(screen.getByRole('option', { name: 'Not set' })).not.toBeDisabled();
    expect(screen.queryByRole('option', { name: '请选择' })).not.toBeInTheDocument();

    fireEvent.change(select, { target: { value: '' } });

    expect(onChange).toHaveBeenCalledWith('NOTIFICATION_MIN_SEVERITY', '');
  });

  it('renders localized custom webhook body template guidance', () => {
    const onChange = vi.fn();

    render(
      <SettingsField
        item={{
          key: 'CUSTOM_WEBHOOK_BODY_TEMPLATE',
          value: '',
          rawValueExists: false,
          isMasked: false,
          schema: {
            key: 'CUSTOM_WEBHOOK_BODY_TEMPLATE',
            category: 'notification',
            dataType: 'string',
            uiControl: 'textarea',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 52,
          },
        }}
        value=""
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText('自定义 Webhook Body 模板')).toBeInTheDocument();
    expect(screen.getByText(/会先于 Bark、Slack、Discord 等自动 payload 生效/)).toBeInTheDocument();
    expect(screen.getByText(/裸 \$content \/ \$title 不做 JSON 转义/)).toBeInTheDocument();
  });

  it('opens detailed field help when help metadata is available', () => {
    render(
      <SettingsField
        item={{
          key: 'STOCK_LIST',
          value: '600519,300750',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'STOCK_LIST',
            category: 'base',
            dataType: 'array',
            uiControl: 'textarea',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
            helpKey: 'settings.base.STOCK_LIST',
            examples: ['STOCK_LIST=600519,300750,002594'],
            docs: [
              {
                label: '完整指南',
                href: 'https://example.com/full-guide',
              },
            ],
            warningCodes: [],
          },
        }}
        value="600519,300750"
        onChange={() => undefined}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: '查看 自选股列表 配置说明' }));

    expect(screen.getByRole('dialog', { name: '自选股列表' })).toBeInTheDocument();
    expect(screen.getByText('STOCK_LIST=600519,300750,002594')).toBeInTheDocument();
    const docLink = screen.getByRole('link', { name: /完整指南/ });
    expect(docLink).toHaveAttribute('href', 'https://example.com/full-guide');

    const closeButtons = screen.getAllByRole('button', { name: '关闭配置说明' });
    expect(closeButtons[0].tabIndex).toBe(-1);
    const closeButton = closeButtons.find((button) => button.tabIndex !== -1);
    expect(closeButton).toBeDefined();

    closeButton?.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(docLink).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Tab' });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '自选股列表' })).not.toBeInTheDocument();
  });
});
