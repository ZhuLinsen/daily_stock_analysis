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
});
