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

const positionedStyleFor = (testId: string): CSSStyleDeclaration => {
  return screen.getByTestId(`${testId}-wrapper`).style;
};

const nodeStyleFor = (testId: string): CSSStyleDeclaration => {
  return screen.getByTestId(testId).style;
};

const layoutRowFor = (testId: string): number => (
  Number(screen.getByTestId(testId).dataset.layoutRow)
);

const topFor = (testId: string): number => (
  parseFloat(positionedStyleFor(testId).top)
);

const heightFor = (testId: string): number => (
  parseFloat(positionedStyleFor(testId).height)
);

describe('RunFlowGraph', () => {
  it('renders auto-layered lanes, edge legend labels, and clickable nodes', () => {
    const onSelectNode = vi.fn();
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={nodes}
        edges={edges}
        onSelectNode={onSelectNode}
      />,
    );

    expect(screen.getByText('入口')).toBeInTheDocument();
    expect(screen.getByText('数据来源')).toBeInTheDocument();
    expect(screen.getAllByText('降级回退').length).toBeGreaterThan(0);
    expect(screen.getByText('降级输入')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-node-news')).toHaveTextContent('开始');
    expect(screen.getByTestId('run-flow-node-news')).toHaveTextContent('2026');
    expect(screen.getByRole('button', { name: '新闻舆情 节点，状态 降级回退' })).toBeInTheDocument();
    const marker = container.querySelector('marker');
    expect(marker).toHaveAttribute('markerWidth', '4');
    expect(marker).toHaveAttribute('markerHeight', '4');
    expect(marker).toHaveAttribute('refX', '3.5');
    expect(marker?.querySelector('path')).toHaveAttribute('d', 'M 0 0 L 4 2 L 0 4 z');
    fireEvent.mouseEnter(screen.getByTestId('run-flow-node-news'));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '新闻舆情 节点，状态 降级回退' }));

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

    const opacities = paths.map((path) => path.getAttribute('opacity'));
    expect(opacities.filter((opacity) => opacity === '0.82')).toHaveLength(1);
    expect(opacities.filter((opacity) => opacity === '0.18')).toHaveLength(2);
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

  it('keeps entry lane nodes at the standard height with roomier vertical rhythm', () => {
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={[
          {
            id: 'request',
            lane: 'entry',
            kind: 'entry',
            label: '用户请求',
            status: 'success',
          },
          {
            id: 'task_queue',
            lane: 'entry',
            kind: 'queue',
            label: '任务队列',
            status: 'success',
          },
        ]}
        edges={[]}
      />,
    );

    expect(heightFor('run-flow-node-request')).toBe(112);
    expect(heightFor('run-flow-node-task_queue')).toBe(112);
    expect(topFor('run-flow-node-task_queue')).toBe(topFor('run-flow-node-request') + 152);
    expect(nodeStyleFor('run-flow-node-request').height).toBe('112px');
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
        label: '详情',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={verticalNodes}
        edges={verticalEdges}
        selectedNodeId="daily"
      />,
    );

    const pathData = container.querySelector('svg g path')?.getAttribute('d') || '';
    const pathNumbers = pathData.match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
    const [startX, startY, endY] = pathNumbers;
    const dailyStyle = positionedStyleFor('run-flow-node-daily');
    const quoteStyle = positionedStyleFor('run-flow-node-quote');
    const dailyCenterX = parseFloat(dailyStyle.left) + parseFloat(dailyStyle.width) / 2;
    const dailyBottom = parseFloat(dailyStyle.top) + parseFloat(dailyStyle.height);
    const quoteTop = parseFloat(quoteStyle.top);

    expect(pathData).toContain('V');
    expect(pathData).not.toContain('C');
    expect(startX).toBe(dailyCenterX);
    expect(startY).toBeLessThan(endY);
    expect(startY).toBe(dailyBottom);
    expect(endY).toBe(quoteTop);
    const label = screen.getByText('详情');
    expect(label).toHaveAttribute('text-anchor', 'start');
    expect(parseFloat(label.getAttribute('x') || '0')).toBeGreaterThan(startX);
    expect(parseFloat(label.getAttribute('y') || '0')).toBeGreaterThan((startY + endY) / 2);
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
        label: '跨泳道',
      },
    ];
    const { container } = render(
      <RunFlowGraph
        lanes={lanes}
        nodes={crossLaneNodes}
        edges={crossLaneEdges}
        selectedNodeId="request"
      />,
    );

    const pathData = container.querySelector('svg g path')?.getAttribute('d') || '';
    const pathNumbers = pathData.match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
    const [startX, startY, , endY, endX] = pathNumbers;
    const requestStyle = positionedStyleFor('run-flow-node-request');
    const llmStyle = positionedStyleFor('run-flow-node-llm');
    const requestRight = parseFloat(requestStyle.left) + parseFloat(requestStyle.width);
    const requestCenterY = parseFloat(requestStyle.top) + parseFloat(requestStyle.height) / 2;
    const llmLeft = parseFloat(llmStyle.left);
    const llmCenterY = parseFloat(llmStyle.top) + parseFloat(llmStyle.height) / 2;

    expect(pathData).toContain('H');
    expect(pathData).toContain('V');
    expect(pathData).not.toContain('C');
    expect(startX).toBe(requestRight);
    expect(startY).toBe(requestCenterY);
    expect(endX).toBe(llmLeft);
    expect(endY).toBe(llmCenterY);
    const label = screen.getByText('跨泳道');
    expect(label).toHaveAttribute('text-anchor', 'middle');
    expect(parseFloat(label.getAttribute('y') || '0')).toBeLessThan((startY + endY) / 2);
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

  it('keeps compact lane and card widths consistent across lanes', () => {
    const laneWidthNodes: RunFlowNode[] = [
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
        status: 'success',
        provider: 'TushareFetcher -> AkshareFetcher -> TushareFetcher -> AkshareFetcher',
      },
      {
        id: 'save',
        lane: 'artifact',
        kind: 'artifact',
        label: '保存报告',
        status: 'success',
      },
      {
        id: 'notification',
        lane: 'artifact',
        kind: 'notification',
        label: '推送通知 · report',
        status: 'skipped',
      },
    ];
    render(
      <RunFlowGraph
        lanes={[
          ...lanes,
          { id: 'artifact', label: '产物', order: 4 },
        ]}
        nodes={laneWidthNodes}
        edges={[]}
      />,
    );

    expect(positionedStyleFor('run-flow-node-request').width).toBe('188px');
    expect(positionedStyleFor('run-flow-node-news').width).toBe('244px');
    expect(nodeStyleFor('run-flow-node-news').width).toBe('244px');
    expect(positionedStyleFor('run-flow-node-save').width).toBe('188px');
    expect(nodeStyleFor('run-flow-node-save').width).toBe('188px');
    expect(positionedStyleFor('run-flow-node-notification').width).toBe('188px');
    expect(nodeStyleFor('run-flow-node-notification').width).toBe('188px');
  });

  it('shows an inline expand control for expandable topology groups without selecting the node', () => {
    const onSelectNode = vi.fn();
    const onToggleExpanded = vi.fn();
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={[
          {
            id: 'topology_data_news_search',
            lane: 'data_source',
            kind: 'data_source',
            label: '新闻舆情',
            status: 'fallback',
            metadata: { topologyGroup: 'provider_attempts' },
          },
        ]}
        edges={[]}
        onSelectNode={onSelectNode}
        onToggleExpanded={onToggleExpanded}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '展开 新闻舆情 运行尝试' }));

    expect(screen.getByTestId('run-flow-node-topology_data_news_search')).toHaveClass('pb-8');
    expect(onToggleExpanded).toHaveBeenCalledWith('topology_data_news_search');
    expect(onSelectNode).not.toHaveBeenCalled();
  });

  it('uses clearer default and selected card states without changing border width', () => {
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={nodes}
        edges={edges}
        selectedNodeId="news"
      />,
    );

    expect(screen.getByTestId('run-flow-node-request')).toHaveClass(
      'border-2',
      'border-subtle/80',
      'ring-1',
      'ring-white/5',
    );
    expect(screen.getByTestId('run-flow-node-news')).toHaveClass(
      'border-2',
      'border-primary/85',
      'bg-primary/8',
      'ring-2',
      'ring-primary/25',
    );
  });

  it('emphasizes selected provider group paths including internal fallback attempts', () => {
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={[
          {
            id: 'task_queue',
            lane: 'entry',
            kind: 'queue',
            label: '任务队列',
            status: 'success',
          },
          {
            id: 'topology_data_realtime_quote',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情',
            status: 'fallback',
            metadata: { topologyGroup: 'provider_attempts', data_type: 'realtime_quote', expanded: true },
          },
          {
            id: 'provider_realtime_tushare_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · TushareFetcher',
            provider: 'TushareFetcher',
            status: 'success',
            metadata: { data_type: 'realtime_quote' },
          },
          {
            id: 'provider_realtime_akshare_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher',
            provider: 'AkshareFetcher',
            status: 'success',
            metadata: { data_type: 'realtime_quote' },
          },
          {
            id: 'daily',
            lane: 'data_source',
            kind: 'data_source',
            label: '日线K线',
            status: 'success',
          },
          {
            id: 'llm',
            lane: 'analysis',
            kind: 'model',
            label: 'LLM 生成',
            status: 'success',
          },
        ]}
        edges={[
          {
            id: 'task-realtime',
            from: 'task_queue',
            to: 'topology_data_realtime_quote',
            kind: 'control',
            status: 'fallback',
          },
          {
            id: 'realtime-first',
            from: 'topology_data_realtime_quote',
            to: 'provider_realtime_tushare_1',
            kind: 'control',
            status: 'success',
          },
          {
            id: 'realtime-fallback',
            from: 'provider_realtime_tushare_1',
            to: 'provider_realtime_akshare_2',
            kind: 'fallback',
            status: 'fallback',
          },
          {
            id: 'daily-llm',
            from: 'daily',
            to: 'llm',
            kind: 'data',
            status: 'success',
          },
        ]}
        selectedNodeId="topology_data_realtime_quote"
        expandedNodeIds={new Set(['topology_data_realtime_quote'])}
      />,
    );

    expect(screen.getByTestId('run-flow-edge-task-realtime')).toHaveAttribute('stroke-width', '2.4');
    expect(screen.getByTestId('run-flow-edge-task-realtime')).toHaveAttribute('opacity', '0.82');
    expect(screen.getByTestId('run-flow-edge-realtime-first')).toHaveAttribute('stroke-width', '3');
    expect(screen.getByTestId('run-flow-edge-realtime-first')).toHaveAttribute('opacity', '0.95');
    expect(screen.getByTestId('run-flow-edge-realtime-fallback')).toHaveAttribute('stroke-width', '3.5');
    expect(screen.getByTestId('run-flow-edge-realtime-fallback')).toHaveAttribute('opacity', '0.95');
    expect(screen.getByTestId('run-flow-edge-daily-llm')).toHaveAttribute('stroke-width', '1.75');
    expect(screen.getByTestId('run-flow-edge-daily-llm')).toHaveAttribute('opacity', '0.18');
  });

  it('keeps expanded provider attempts grouped under their parent in compact cards', () => {
    const onToggleExpanded = vi.fn();
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={[
          {
            id: 'topology_data_realtime_quote',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情',
            status: 'fallback',
            startedAt: '2026-06-08T10:00:00',
            metadata: { topologyGroup: 'provider_attempts', data_type: 'realtime_quote', expanded: true },
          },
          {
            id: 'daily',
            lane: 'data_source',
            kind: 'data_source',
            label: '日线K线',
            status: 'success',
            startedAt: '2026-06-08T10:00:01',
          },
          {
            id: 'provider_realtime_tushare_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · TushareFetcher',
            provider: 'TushareFetcher',
            status: 'success',
            startedAt: '2026-06-08T10:00:02',
            metadata: { data_type: 'realtime_quote' },
          },
          {
            id: 'provider_realtime_akshare_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher',
            provider: 'AkshareFetcher',
            status: 'success',
            startedAt: '2026-06-08T10:00:03',
            metadata: { data_type: 'realtime_quote' },
          },
        ]}
        edges={[]}
        expandedNodeIds={new Set(['topology_data_realtime_quote'])}
        onToggleExpanded={onToggleExpanded}
      />,
    );

    expect(layoutRowFor('run-flow-node-provider_realtime_tushare_1')).toBe(
      layoutRowFor('run-flow-node-topology_data_realtime_quote') + 1,
    );
    expect(layoutRowFor('run-flow-node-provider_realtime_akshare_2')).toBe(
      layoutRowFor('run-flow-node-provider_realtime_tushare_1') + 1,
    );
    expect(layoutRowFor('run-flow-node-daily')).toBeGreaterThan(
      layoutRowFor('run-flow-node-provider_realtime_akshare_2'),
    );
    expect(topFor('run-flow-node-topology_data_realtime_quote')).toBeLessThan(
      topFor('run-flow-node-provider_realtime_tushare_1'),
    );
    expect(heightFor('run-flow-node-topology_data_realtime_quote')).toBe(112);
    expect(heightFor('run-flow-node-provider_realtime_tushare_1')).toBe(96);
    expect(topFor('run-flow-node-provider_realtime_tushare_1')).toBe(
      topFor('run-flow-node-topology_data_realtime_quote') + 112 + 42,
    );
    expect(topFor('run-flow-node-provider_realtime_akshare_2')).toBe(
      topFor('run-flow-node-provider_realtime_tushare_1') + 96 + 42,
    );
    expect(topFor('run-flow-node-daily')).toBe(
      topFor('run-flow-node-provider_realtime_akshare_2') + 96 + 40,
    );
    const groupBackground = screen.getByTestId('run-flow-expanded-group-topology_data_realtime_quote');
    const groupBackgroundTop = parseFloat(groupBackground.style.top);
    const groupBackgroundBottom = groupBackgroundTop + parseFloat(groupBackground.style.height);
    expect(groupBackgroundTop).toBe(topFor('run-flow-node-topology_data_realtime_quote') - 18);
    expect(groupBackgroundBottom).toBe(
      topFor('run-flow-node-provider_realtime_akshare_2') + heightFor('run-flow-node-provider_realtime_akshare_2') + 18,
    );
    const canvasMinHeight = parseFloat((groupBackground.parentElement as HTMLElement).style.minHeight);
    expect(canvasMinHeight).toBeGreaterThan(groupBackgroundBottom);
    expect(screen.getByTestId('run-flow-node-provider_realtime_tushare_1')).toHaveClass(
      'bg-base/70',
      'shadow-none',
    );
    expect(nodeStyleFor('run-flow-node-provider_realtime_tushare_1').width).toBe('244px');
    expect(nodeStyleFor('run-flow-node-provider_realtime_tushare_1').height).toBe('96px');
    const toggle = screen.getByTestId('run-flow-node-topology_data_realtime_quote-toggle');
    expect(toggle).toHaveClass('h-[18px]', 'gap-0.5', 'px-1', 'text-[9px]', 'leading-none');
    expect(toggle.querySelector('svg')).toHaveClass('h-2', 'w-2');
  });

  it('keeps multiple expanded provider groups as non-interleaving layout blocks', () => {
    render(
      <RunFlowGraph
        lanes={lanes}
        nodes={[
          {
            id: 'topology_data_realtime_quote',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情',
            status: 'fallback',
            startedAt: '2026-06-08T10:00:00',
            metadata: {
              topologyGroup: 'provider_attempts',
              topologyRole: 'provider_group',
              data_type: 'realtime_quote',
              expanded: true,
            },
          },
          {
            id: 'topology_data_news_search',
            lane: 'data_source',
            kind: 'data_source',
            label: '新闻舆情',
            status: 'fallback',
            startedAt: '2026-06-08T10:00:01',
            metadata: {
              topologyGroup: 'provider_attempts',
              topologyRole: 'provider_group',
              data_type: 'news_search',
              expanded: true,
            },
          },
          {
            id: 'daily',
            lane: 'data_source',
            kind: 'data_source',
            label: '日线K线',
            status: 'success',
            startedAt: '2026-06-08T10:00:02',
          },
          {
            id: 'provider_realtime_tushare_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · TushareFetcher',
            status: 'success',
            startedAt: '2026-06-08T10:00:03',
            metadata: {
              data_type: 'realtime_quote',
              topologyParentId: 'topology_data_realtime_quote',
              topologyRole: 'provider_attempt',
              topologyOrder: 1,
            },
          },
          {
            id: 'provider_news_tavily_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '新闻舆情 · Tavily',
            status: 'success',
            startedAt: '2026-06-08T10:00:04',
            metadata: {
              data_type: 'news_search',
              topologyParentId: 'topology_data_news_search',
              topologyRole: 'provider_attempt',
              topologyOrder: 1,
            },
          },
          {
            id: 'provider_realtime_akshare_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher',
            status: 'success',
            startedAt: '2026-06-08T10:00:05',
            metadata: {
              data_type: 'realtime_quote',
              topologyParentId: 'topology_data_realtime_quote',
              topologyRole: 'provider_attempt',
              topologyOrder: 2,
            },
          },
          {
            id: 'provider_news_searxng_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '新闻舆情 · SearXNG',
            status: 'failed',
            startedAt: '2026-06-08T10:00:06',
            metadata: {
              data_type: 'news_search',
              topologyParentId: 'topology_data_news_search',
              topologyRole: 'provider_attempt',
              topologyOrder: 2,
            },
          },
        ]}
        edges={[]}
        expandedNodeIds={new Set(['topology_data_realtime_quote', 'topology_data_news_search'])}
      />,
    );

    expect(layoutRowFor('run-flow-node-provider_realtime_tushare_1')).toBe(
      layoutRowFor('run-flow-node-topology_data_realtime_quote') + 1,
    );
    expect(layoutRowFor('run-flow-node-provider_realtime_akshare_2')).toBe(
      layoutRowFor('run-flow-node-provider_realtime_tushare_1') + 1,
    );
    expect(layoutRowFor('run-flow-node-topology_data_news_search')).toBeGreaterThan(
      layoutRowFor('run-flow-node-provider_realtime_akshare_2'),
    );
    expect(layoutRowFor('run-flow-node-provider_news_tavily_1')).toBe(
      layoutRowFor('run-flow-node-topology_data_news_search') + 1,
    );
    expect(layoutRowFor('run-flow-node-provider_news_searxng_2')).toBe(
      layoutRowFor('run-flow-node-provider_news_tavily_1') + 1,
    );
    expect(layoutRowFor('run-flow-node-daily')).toBeGreaterThan(
      layoutRowFor('run-flow-node-provider_news_searxng_2'),
    );
    expect(screen.getByTestId('run-flow-expanded-group-topology_data_realtime_quote')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-expanded-group-topology_data_news_search')).toBeInTheDocument();
  });
});
