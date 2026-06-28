import React, { useEffect, useState, useCallback } from 'react';
import { agentApi, type ContextStoreData } from '../../api/agent';
import { Collapsible } from '../common/Collapsible';
import { Badge } from '../common/Badge';

interface ToolDataPanelProps {
  sessionId: string | null;
}

export const ToolDataPanel: React.FC<ToolDataPanelProps> = ({ sessionId }) => {
  const [data, setData] = useState<ContextStoreData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!sessionId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await agentApi.getContextStore(sessionId);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (!sessionId) return null;

  return (
    <Collapsible title={`关键数据保护 ${loading ? '...' : data?.has_data ? `(${data.tool_count}项)` : '(空)'}`}>
      <div className="space-y-2 p-2 text-xs">
        {loading && <div className="text-muted-text">加载中...</div>}
        {error && <div className="text-danger-text">错误: {error}</div>}
        {data && !data.has_data && (
          <div className="text-muted-text">当前会话暂无受保护的工具调用数据</div>
        )}
        {data?.tools.map((tool, i) => (
          <div key={i} className="rounded border border-border/50 bg-surface/50 p-1.5">
            <pre className="text-[10px] text-muted-text overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(tool, null, 1)}
            </pre>
          </div>
        ))}
        {data?.context_preview && (
          <div className="mt-1">
            <Badge variant="info">上下文预览</Badge>
            <pre className="text-[10px] text-muted-text mt-1 whitespace-pre-wrap line-clamp-3">
              {data.context_preview}
            </pre>
          </div>
        )}
        <button
          onClick={fetchData}
          className="text-xs text-accent hover:text-accent-hover transition-colors"
        >
          ⟳ 刷新
        </button>
      </div>
    </Collapsible>
  );
};
