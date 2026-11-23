import { render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsPanelErrorBoundary } from '../SettingsPanelErrorBoundary';

function ThrowingPanel({ message = 'mock settings panel crash' }: { message?: string }): ReactElement {
  throw new Error(message);
}

describe('SettingsPanelErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a configurable desktop-log diagnostic fallback when a settings panel throws', () => {
    render(
      <SettingsPanelErrorBoundary
        title="通知设置"
        resetKey="notification"
        diagnosticHint={(
          <>
            请查看并提供桌面端日志
            <code>desktop.log</code>
            ，同时补充 release 版本、Windows 版本和触发入口。
          </>
        )}
      >
        <ThrowingPanel />
      </SettingsPanelErrorBoundary>
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('通知设置加载失败')).toBeInTheDocument();
    expect(screen.getByText('desktop.log')).toBeInTheDocument();
    expect(screen.getByText(/release 版本、Windows 版本和触发入口/)).toBeInTheDocument();
    expect(screen.getByText(/错误摘要：mock settings panel crash/)).toBeInTheDocument();
  });

  it('redacts and truncates sensitive error summary text', () => {
    render(
      <SettingsPanelErrorBoundary title="通知设置" resetKey="notification">
        <ThrowingPanel
          message={`Webhook failed: https://hooks.slack.com/services/T000/B000/path-secret?token=super-secret-token&foo=bar OPENAI_API_KEY=sk-supersecretvalue123456 ${'x'.repeat(220)}`}
        />
      </SettingsPanelErrorBoundary>
    );

    const summary = screen.getByText(/错误摘要：/).textContent ?? '';

    expect(summary).toContain('https://hooks.slack.com/[redacted]?[redacted]');
    expect(summary).toContain('?[redacted]');
    expect(summary).toContain('OPENAI_API_KEY=[redacted]');
    expect(summary).not.toContain('/services/T000/B000/path-secret');
    expect(summary).not.toContain('path-secret');
    expect(summary).not.toContain('super-secret-token');
    expect(summary).not.toContain('sk-supersecretvalue123456');
    expect(summary.length).toBeLessThanOrEqual('错误摘要：'.length + 183);
  });

  it('resets after resetKey changes so the panel can render again', async () => {
    const { rerender } = render(
      <SettingsPanelErrorBoundary title="Agent 设置" resetKey="agent:v1">
        <ThrowingPanel />
      </SettingsPanelErrorBoundary>
    );

    expect(screen.getByText('Agent 设置加载失败')).toBeInTheDocument();

    rerender(
      <SettingsPanelErrorBoundary title="Agent 设置" resetKey="agent:v2">
        <div>Agent 设置已恢复</div>
      </SettingsPanelErrorBoundary>
    );

    await waitFor(() => {
      expect(screen.getByText('Agent 设置已恢复')).toBeInTheDocument();
    });
    expect(screen.queryByText('Agent 设置加载失败')).not.toBeInTheDocument();
  });
});
