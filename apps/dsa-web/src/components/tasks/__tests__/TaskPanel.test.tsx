import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TaskPanel } from '../TaskPanel';
import { useTaskPanelCollapsed } from '../../../hooks/useTaskPanelCollapsed';
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

  it('collapses active task list when toggle is clicked and persists to localStorage', () => {
    localStorage.removeItem('dsa.taskPanel.collapsed');

    render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            stockCode: '600519',
            stockName: '贵州茅台',
          },
          {
            ...baseTask,
            taskId: 'task-2',
            stockCode: 'AAPL',
            stockName: 'Apple',
            status: 'pending',
          },
        ]}
      />,
    );

    // 折叠按钮存在 + aria-expanded=true（展开态）
    const toggle = screen.getByTestId('task-panel-collapse-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    // 任务卡可见，折叠摘要不可见
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.queryByTestId('task-panel-collapsed-summary')).not.toBeInTheDocument();

    // 点击折叠
    fireEvent.click(toggle);

    // 折叠态：摘要可见，任务卡不可见
    const summary = screen.getByTestId('task-panel-collapsed-summary');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    // localStorage 在 useEffect 写入，新增 key=dsa.taskPanel.collapsed, value='1'
    expect(localStorage.getItem('dsa.taskPanel.collapsed')).toBe('1');

    // 点击摘要恢复展开
    fireEvent.click(summary);
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.queryByTestId('task-panel-collapsed-summary')).not.toBeInTheDocument();
    expect(localStorage.getItem('dsa.taskPanel.collapsed')).toBe('0');

    localStorage.removeItem('dsa.taskPanel.collapsed');
  });

  it('restores collapsed state from localStorage on mount', () => {
    localStorage.setItem('dsa.taskPanel.collapsed', '1');

    render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
          },
        ]}
      />,
    );

    // 初始即折叠：摘要可见，任务卡名不可见
    expect(screen.getByTestId('task-panel-collapsed-summary')).toBeInTheDocument();
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();

    localStorage.removeItem('dsa.taskPanel.collapsed');
  });

  it('keeps collapsed state stable across re-renders from parent (issue #2115 requirement)', () => {
    localStorage.removeItem('dsa.taskPanel.collapsed');

    const { rerender } = render(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            stockName: '贵州茅台',
          },
        ]}
      />,
    );

    // 折叠
    fireEvent.click(screen.getByTestId('task-panel-collapse-toggle'));
    expect(screen.getByTestId('task-panel-collapsed-summary')).toBeInTheDocument();

    // 父组件触发重渲染（同样 tasks prop 数组新引用）
    rerender(
      <TaskPanel
        tasks={[
          {
            ...baseTask,
            stockName: '贵州茅台',
          },
        ]}
      />,
    );

    // 折叠态保留：摘要仍可见
    expect(screen.getByTestId('task-panel-collapsed-summary')).toBeInTheDocument();

    localStorage.removeItem('dsa.taskPanel.collapsed');
  });

  it('synchronizes collapsed state across dual instances through the controlled hook (PR #2144 OR-COR-1fd4ac89)', () => {
    // 模拟 HomePage 同时挂载桌面侧栏 + 移动抽屉两个 TaskPanel 实例，
    // 它们应共享同一份 hook state，任一实例折叠后另一实例同步切换。
    localStorage.removeItem('dsa.taskPanel.collapsed');

    function DualInstanceHarness() {
      const collapsed = useTaskPanelCollapsed();
      const tasks = [{ ...baseTask }];
      return (
        <div>
          {/* 桌面侧栏实例（始终挂载） */}
          <div data-testid="desktop-sidebar">
            <TaskPanel
              tasks={tasks}
              isCollapsed={collapsed.isCollapsed}
              onCollapsedChange={collapsed.setCollapsed}
            />
          </div>
          {/* 移动抽屉实例（同样挂载在测试里以验证同步） */}
          <div data-testid="mobile-drawer">
            <TaskPanel
              tasks={tasks}
              isCollapsed={collapsed.isCollapsed}
              onCollapsedChange={collapsed.setCollapsed}
            />
          </div>
        </div>
      );
    }

    render(<DualInstanceHarness />);

    // 两个实例初始都展开
    const desktopToggle = screen
      .getAllByTestId('task-panel-collapse-toggle')[0];
    const drawerToggle = screen
      .getAllByTestId('task-panel-collapse-toggle')[1];
    expect(desktopToggle).toHaveAttribute('aria-expanded', 'true');
    expect(drawerToggle).toHaveAttribute('aria-expanded', 'true');

    // 在移动抽屉实例里点击折叠
    fireEvent.click(drawerToggle);
    // 桌面侧栏实例的 toggle 应同步变为折叠态，体现提升后的单一来源
    expect(desktopToggle).toHaveAttribute('aria-expanded', 'false');
    expect(drawerToggle).toHaveAttribute('aria-expanded', 'false');

    // 在桌面侧栏实例里再点击恢复展开
    fireEvent.click(desktopToggle);
    expect(desktopToggle).toHaveAttribute('aria-expanded', 'true');
    expect(drawerToggle).toHaveAttribute('aria-expanded', 'true');

    localStorage.removeItem('dsa.taskPanel.collapsed');
  });
});
