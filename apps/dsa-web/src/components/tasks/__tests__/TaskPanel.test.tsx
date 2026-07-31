import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TaskPanel } from '../TaskPanel';
import type { TaskInfo } from '../../../types/analysis';

const baseTask: TaskInfo = {
  taskId: 'task-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  status: 'processing',
  progress: 40,
  message: '正在抓取最新行情',
  reportType: 'detailed',
  createdAt: '2026-03-21T08:00:00Z',
};

describe('TaskPanel', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('renders requested analysis phase badges for active tasks', () => {
    render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            analysisPhase: 'intraday',
          },
          {
            ...baseTask,
            taskId: 'task-2',
            stockCode: 'AAPL',
            stockName: 'Apple',
            status: 'pending',
            analysisPhase: 'auto',
          },
        ]}
      />,
    );

    expect(screen.getByLabelText('请求阶段: 盘中')).toBeInTheDocument();
    expect(screen.getByLabelText('请求阶段: 自动阶段')).toBeInTheDocument();
  });

  it('renders active tasks with preserved dashboard panel styling', () => {
    const { container } = render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            traceId: 'trace-task-1',
          },
          {
            ...baseTask,
            taskId: 'task-2',
            stockCode: 'AAPL',
            stockName: 'Apple',
            status: 'pending',
            message: '等待分析队列',
          },
        ]}
      />,
    );

    expect(screen.getByText('分析任务')).toBeInTheDocument();
    expect(screen.getByText('1 进行中')).toBeInTheDocument();
    expect(screen.getByText('1 等待中')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByLabelText('任务状态：分析中')).toBeInTheDocument();
    expect(screen.getByText('运行诊断')).toBeInTheDocument();
    expect(screen.getAllByText('trace-task-1')).toHaveLength(2);
    expect(screen.queryByText(/请求阶段:/)).not.toBeInTheDocument();
    expect(container.querySelector('.home-panel-card')).toBeTruthy();
    expect(container.querySelector('.home-subpanel')).toBeTruthy();
  });

  it('keeps narrow sidebar task metadata in rows instead of squeezing diagnostics vertically', () => {
    render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            stockCode: '601869.SH',
            stockName: '长飞光纤',
            progress: 32,
            message: '长飞光纤: 请求阶段: 自动阶段',
            analysisPhase: 'auto',
            traceId: 'c5b9665a64e3b9f42ad9f',
          },
        ]}
        onOpenRunFlow={vi.fn()}
      />,
    );

    const item = screen.getByTestId('task-panel-item');
    expect(item).toHaveClass('grid');
    expect(item).not.toHaveClass('flex');
    expect(screen.getByText('长飞光纤')).toHaveClass('truncate');
    expect(screen.getByText('601869.SH')).toHaveClass('shrink-0');
    expect(screen.getByText('32%')).toBeInTheDocument();

    const diagnosticsSummary = screen.getByTestId('task-panel-diagnostics-summary');
    expect(diagnosticsSummary).toHaveClass('grid-cols-[auto_minmax(0,1fr)_auto]');
    expect(screen.getByText('运行诊断')).toHaveClass('whitespace-nowrap');
    expect(screen.getByText('c5b9665a64...')).toHaveClass('truncate');
    expect(screen.getByRole('button', { name: '查看 长飞光纤 运行流' })).toBeInTheDocument();
  });

  it('opens the run-flow view from an active task icon button', () => {
    const onOpenRunFlow = vi.fn();
    render(
      <TaskPanel
        tasks={[baseTask]}
        onOpenRunFlow={onOpenRunFlow}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '查看 贵州茅台 运行流' }));

    expect(onOpenRunFlow).toHaveBeenCalledWith(baseTask);
  });

  it('collapses to a task summary and keeps the state for the page session', () => {
    const tasks: TaskInfo[] = [
      baseTask,
      {
        ...baseTask,
        taskId: 'task-2',
        stockCode: 'AAPL',
        stockName: 'Apple',
        status: 'pending',
        progress: 0,
      },
    ];
    const { unmount } = render(<TaskPanel tasks={tasks} />);

    const collapseButton = screen.getByRole('button', { name: '折叠分析任务' });
    expect(collapseButton).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(collapseButton);

    expect(screen.queryByTestId('task-panel-item')).not.toBeInTheDocument();
    expect(screen.getByTestId('task-panel-collapsed-summary')).toHaveTextContent('1 进行中');
    expect(screen.getByTestId('task-panel-collapsed-summary')).toHaveTextContent('1 等待中');
    expect(screen.getByTestId('task-panel-collapsed-summary')).toHaveTextContent('总体 20%');
    expect(screen.getByRole('button', { name: '展开分析任务' })).toHaveAttribute('aria-expanded', 'false');

    unmount();
    render(<TaskPanel tasks={tasks} />);

    expect(screen.getByTestId('task-panel-collapsed-summary')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '展开分析任务' }));
    expect(screen.getAllByTestId('task-panel-item')).toHaveLength(2);
  });

  it('keeps cancel-requested tasks visible without rendering them as failed', () => {
    render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            status: 'cancel_requested',
            message: '正在请求取消',
          },
        ]}
      />,
    );

    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getByLabelText('任务状态：请求取消')).toBeInTheDocument();
    expect(screen.queryByText('失败')).not.toBeInTheDocument();
  });

  it('does not keep cancelled terminal tasks in the active task panel', () => {
    const { container } = render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            status: 'cancelled',
          },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('does not render when there are no active tasks', () => {
    const { container } = render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            status: 'completed',
          },
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
