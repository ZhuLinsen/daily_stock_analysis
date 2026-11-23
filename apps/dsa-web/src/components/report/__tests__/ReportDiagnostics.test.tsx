import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import type { RunDiagnosticSummary } from '../../../types/analysis';
import { ReportDiagnostics } from '../ReportDiagnostics';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getDiagnostics: vi.fn(),
  },
}));

const diagnosticSummary: RunDiagnosticSummary = {
  traceId: 'trace-1234567890abcdef',
  taskId: 'task-1',
  queryId: 'query-1',
  stockCode: '600519',
  triggerSource: 'web',
  status: 'degraded',
  statusLabel: '部分降级',
  reason: '实时行情 baostock 成功，前置数据源失败后已继续',
  copyText: 'trace_id: trace-1234567890abcdef\ndata_status: degraded',
  components: {
    realtimeQuote: {
      key: 'realtime_quote',
      label: '实时行情',
      status: 'degraded',
      message: '实时行情 baostock 成功，前置数据源失败后已继续',
      details: {
        provider: 'baostock',
        attempts: 2,
      },
    },
    notification: {
      key: 'notification',
      label: '通知',
      status: 'not_configured',
      message: '通知未配置或本次跳过',
    },
  },
};

describe('ReportDiagnostics', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it('loads historical diagnostics in a collapsed panel and copies sanitized text', async () => {
    vi.mocked(historyApi.getDiagnostics).mockResolvedValue(diagnosticSummary);

    render(<ReportDiagnostics recordId={1} />);

    expect(historyApi.getDiagnostics).toHaveBeenCalledWith(1);
    expect(await screen.findByText('运行状态')).toBeInTheDocument();
    const panel = screen.getByTestId('run-diagnostics');
    expect(panel).not.toHaveAttribute('open');
    expect(screen.getByText('部分降级')).toBeInTheDocument();

    fireEvent.click(screen.getByText('运行状态'));

    expect(panel).toHaveAttribute('open');
    expect(screen.getByText('最近失败后已降级')).toBeInTheDocument();
    expect(screen.getByText('未配置')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '复制排障信息' }));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(diagnosticSummary.copyText);
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    });
  });

  it('uses the provided summary without fetching history diagnostics', () => {
    render(<ReportDiagnostics summary={diagnosticSummary} language="en" />);

    expect(historyApi.getDiagnostics).not.toHaveBeenCalled();
    expect(screen.getByText('Run Status')).toBeInTheDocument();
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('Fetch / LLM / save / notification path')).toBeInTheDocument();
  });

  it('opens historical run flow from the diagnostics body', async () => {
    const onOpenRunFlow = vi.fn();
    vi.mocked(historyApi.getDiagnostics).mockResolvedValue(diagnosticSummary);

    render(<ReportDiagnostics recordId={1} onOpenRunFlow={onOpenRunFlow} />);

    fireEvent.click(await screen.findByText('运行状态'));
    fireEvent.click(screen.getByRole('button', { name: '查看历史记录 1 运行流' }));

    expect(onOpenRunFlow).toHaveBeenCalledWith(1);
  });

  it('refetches diagnostics after StrictMode cleans up the first effect run', async () => {
    vi.mocked(historyApi.getDiagnostics).mockResolvedValue(diagnosticSummary);

    render(
      <StrictMode>
        <ReportDiagnostics recordId={1} />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(historyApi.getDiagnostics).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText('运行状态')).toBeInTheDocument();
  });
});
