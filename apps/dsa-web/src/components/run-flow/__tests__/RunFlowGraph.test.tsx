import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RunFlowEdge, RunFlowLane, RunFlowNode } from '../../../types/runFlow';
import { RunFlowGraph } from '../RunFlowGraph';

const lanes: RunFlowLane[] = [
  { id: 'entry', label: '入口', order: 1 },
  { id: 'data_source', label: '数据来源', order: 2 },
  { id: 'analysis', label: '分析引擎', order: 3 },
];

const nodes: RunFlowNode[] = [
  {
    id: 'request',
    lane: 'entry',
    kind: 'entry',
    label: '用户请求',
    status: 'success',
  },
  {
    id: 'news',
    lane: 'data_source',
    kind: 'data_source',
    label: '新闻舆情',
    status: 'fallback',
    provider: 'AkShare',
    startedAt: '2026-06-08T10:00:00',
  },
];

const edges: RunFlowEdge[] = [
  {
    id: 'request-news',
    from: 'request',
    to: 'news',
    kind: 'fallback',
    status: 'fallback',
    label: '降级输入',
  },
];

describe('RunFlowGraph', () => {
  it('renders auto-layered lanes, edge legend labels, and clickable nodes', () => {
    const onSelectNode = vi.fn();
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={nodes}
        edges={edges}
        onSelectNode={onSelectNode}
      />,
    );

    expect(screen.getByText('入口')).toBeInTheDocument();
    expect(screen.getByText('数据来源')).toBeInTheDocument();
    expect(screen.getByText('降级')).toBeInTheDocument();
    expect(screen.getByText('降级输入')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-node-news')).toHaveTextContent('开始');
    expect(screen.getByTestId('run-flow-node-news')).toHaveTextContent('2026');
    expect(screen.getByRole('button', { name: '新闻舆情 节点，状态 Fallback' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '新闻舆情 节点，状态 Fallback' }));

    expect(onSelectNode).toHaveBeenCalledWith(expect.objectContaining({ id: 'news' }));
  });

  it('dims unrelated edges while keeping fallback and retry labels visible when a node is selected', () => {
    const selectionNodes: RunFlowNode[] = [
      ...nodes,
      {
        id: 'llm',
        lane: 'analysis',
        kind: 'model',
        label: 'LLM 生成',
        status: 'success',
      },
      {
        id: 'artifact',
        lane: 'analysis',
        kind: 'artifact',
        label: '报告产物',
        status: 'success',
      },
    ];
    const selectionEdges: RunFlowEdge[] = [
      {
        id: 'request-news',
        from: 'request',
        to: 'news',
        kind: 'control',
        status: 'success',
        label: '调度输入',
      },
      {
        id: 'llm-artifact',
        from: 'llm',
        to: 'artifact',
        kind: 'data',
        status: 'success',
        label: '报告输出',
      },
      {
        id: 'llm-artifact-fallback',
        from: 'llm',
        to: 'artifact',
        kind: 'fallback',
        status: 'fallback',
        label: '降级输出',
      },
    ];

    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={selectionNodes}
        edges={selectionEdges}
        selectedNodeId="news"
      />,
    );

    const paths = Array.from(container.querySelectorAll('svg g path'));

    expect(paths.map((path) => path.getAttribute('opacity'))).toEqual(['0.9', '0.22', '0.22']);
    expect(screen.getByText('调度输入')).toBeInTheDocument();
    expect(screen.queryByText('报告输出')).not.toBeInTheDocument();
    expect(screen.getByText('降级输出')).toBeInTheDocument();
  });

  it('distributes fan-out edge anchors instead of routing every line through the node center', () => {
    const fanOutNodes: RunFlowNode[] = [
      {
        id: 'request',
        lane: 'entry',
        kind: 'entry',
        label: '用户请求',
        status: 'success',
      },
      {
        id: 'daily',
        lane: 'data_source',
        kind: 'data_source',
        label: '日线K线',
        status: 'success',
      },
      {
        id: 'quote',
        lane: 'data_source',
        kind: 'data_source',
        label: '实时行情',
        status: 'success',
      },
      {
        id: 'llm',
        lane: 'analysis',
        kind: 'model',
        label: 'LLM 生成',
        status: 'success',
      },
    ];
    const fanOutEdges: RunFlowEdge[] = [
      {
        id: 'request-daily',
        from: 'request',
        to: 'daily',
        kind: 'control',
        status: 'success',
      },
      {
        id: 'request-quote',
        from: 'request',
        to: 'quote',
        kind: 'control',
        status: 'success',
      },
      {
        id: 'daily-llm',
        from: 'daily',
        to: 'llm',
        kind: 'data',
        status: 'success',
      },
      {
        id: 'quote-llm',
        from: 'quote',
        to: 'llm',
        kind: 'data',
        status: 'success',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={fanOutNodes}
        edges={fanOutEdges}
      />,
    );

    const pathData = Array.from(container.querySelectorAll('svg g path'))
      .map((path) => path.getAttribute('d') || '');
    const fanOutStartYs = pathData
      .slice(0, 2)
      .map((path) => Number(path.match(/^M\s+\S+\s+(\S+)/)?.[1]));

    expect(new Set(fanOutStartYs).size).toBe(2);
    expect(screen.getByTestId('run-flow-node-daily')).toHaveAttribute('data-layout-row');
    expect(screen.getByTestId('run-flow-node-quote')).toHaveAttribute('data-layout-row');
  });

  it('routes same-lane vertical edges from card bottom to the next card top', () => {
    const verticalNodes: RunFlowNode[] = [
      {
        id: 'daily',
        lane: 'data_source',
        kind: 'data_source',
        label: '日线K线',
        status: 'success',
      },
      {
        id: 'quote',
        lane: 'data_source',
        kind: 'data_source',
        label: '实时行情',
        status: 'success',
      },
    ];
    const verticalEdges: RunFlowEdge[] = [
      {
        id: 'daily-quote',
        from: 'daily',
        to: 'quote',
        kind: 'control',
        status: 'success',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={verticalNodes}
        edges={verticalEdges}
      />,
    );

    const pathData = container.querySelector('svg g path')?.getAttribute('d') || '';
    const pathNumbers = pathData.match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
    const [startX, startY, endY] = pathNumbers;
    const dailyNode = screen.getByTestId('run-flow-node-daily');
    const quoteNode = screen.getByTestId('run-flow-node-quote');
    const dailyCenterX = parseFloat(dailyNode.style.left) + parseFloat(dailyNode.style.width) / 2;
    const dailyBottom = parseFloat(dailyNode.style.top) + parseFloat(dailyNode.style.minHeight);
    const quoteTop = parseFloat(quoteNode.style.top);

    expect(pathData).toContain('V');
    expect(pathData).not.toContain('C');
    expect(startX).toBe(dailyCenterX);
    expect(startY).toBeLessThan(endY);
    expect(startY).toBe(dailyBottom);
    expect(endY).toBe(quoteTop);
  });

  it('routes cross-lane flow edges through side ports with orthogonal segments', () => {
    const crossLaneNodes: RunFlowNode[] = [
      {
        id: 'request',
        lane: 'entry',
        kind: 'entry',
        label: '用户请求',
        status: 'success',
      },
      {
        id: 'llm',
        lane: 'analysis',
        kind: 'model',
        label: 'LLM 生成',
        status: 'success',
      },
    ];
    const crossLaneEdges: RunFlowEdge[] = [
      {
        id: 'request-llm',
        from: 'request',
        to: 'llm',
        kind: 'data',
        status: 'success',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={crossLaneNodes}
        edges={crossLaneEdges}
      />,
    );

    const pathData = container.querySelector('svg g path')?.getAttribute('d') || '';
    const pathNumbers = pathData.match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
    const [startX, startY, , endY, endX] = pathNumbers;
    const requestNode = screen.getByTestId('run-flow-node-request');
    const llmNode = screen.getByTestId('run-flow-node-llm');
    const requestRight = parseFloat(requestNode.style.left) + parseFloat(requestNode.style.width);
    const requestCenterY = parseFloat(requestNode.style.top) + parseFloat(requestNode.style.minHeight) / 2;
    const llmLeft = parseFloat(llmNode.style.left);
    const llmCenterY = parseFloat(llmNode.style.top) + parseFloat(llmNode.style.minHeight) / 2;

    expect(pathData).toContain('H');
    expect(pathData).toContain('V');
    expect(pathData).not.toContain('C');
    expect(startX).toBe(requestRight);
    expect(startY).toBe(requestCenterY);
    expect(endX).toBe(llmLeft);
    expect(endY).toBe(llmCenterY);
  });

  it('orders data-source lane cards by their observed timestamps', () => {
    const timeOrderedNodes: RunFlowNode[] = [
      {
        id: 'late-news',
        lane: 'data_source',
        kind: 'data_source',
        label: '新闻舆情',
        status: 'success',
        startedAt: '2026-06-08T10:00:05',
      },
      {
        id: 'early-quote',
        lane: 'data_source',
        kind: 'data_source',
        label: '实时行情',
        status: 'success',
        startedAt: '2026-06-08T10:00:01',
      },
      {
        id: 'middle-daily',
        lane: 'data_source',
        kind: 'data_source',
        label: '日线K线',
        status: 'success',
        endedAt: '2026-06-08T10:00:03',
      },
    ];

    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={timeOrderedNodes}
        edges={[]}
      />,
    );

    expect(Number(screen.getByTestId('run-flow-node-early-quote').dataset.layoutRow)).toBeLessThan(
      Number(screen.getByTestId('run-flow-node-middle-daily').dataset.layoutRow),
    );
    expect(Number(screen.getByTestId('run-flow-node-middle-daily').dataset.layoutRow)).toBeLessThan(
      Number(screen.getByTestId('run-flow-node-late-news').dataset.layoutRow),
    );
  });
});
