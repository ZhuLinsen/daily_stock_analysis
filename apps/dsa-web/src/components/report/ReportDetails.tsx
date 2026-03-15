import type React from 'react';
import { useState } from 'react';
import type { ReportDetails as ReportDetailsType } from '../../types/analysis';
import { Card } from '../common';

interface ReportDetailsProps {
  details?: ReportDetailsType;
  recordId?: number;  // 分析历史记录主键 ID
}

/**
 * 透明度与追溯区组件 - 终端风格
 */
export const ReportDetails: React.FC<ReportDetailsProps> = ({
  details,
  recordId,
}) => {
  const [showRaw, setShowRaw] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!details?.rawResult && !details?.contextSnapshot && !recordId) {
    return null;
  }

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const renderJson = (data: unknown) => {
    const jsonStr = JSON.stringify(data, null, 2);
    return (
      <div className="relative overflow-hidden">
        <button
          type="button"
          onClick={() => copyToClipboard(jsonStr)}
          className="absolute top-2 right-2 text-xs text-muted hover:text-cyan transition-colors"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <pre className="text-xs text-secondary font-mono overflow-x-auto p-3 bg-base rounded-lg max-h-80 overflow-y-auto text-left w-0 min-w-full">
          {jsonStr}
        </pre>
      </div>
    );
  };

  return (
    <Card variant="bordered" padding="md" className="text-left">
      <div className="mb-3 flex items-baseline gap-2">
        <span className="label-uppercase">TRANSPARENCY</span>
        <h3 className="text-base font-semibold text-white mt-0.5">数据追溯</h3>
      </div>

      {/* Record ID */}
      {recordId && (
        <div className="flex items-center gap-2 text-xs text-muted mb-3 pb-3 border-b border-white/5">
          <span>Record ID:</span>
          <code className="font-mono text-xs text-cyan bg-cyan/10 px-1.5 py-0.5 rounded">
            {recordId}
          </code>
        </div>
      )}

      {/* 折叠区域 */}
      <div className="space-y-2">
        {/* 原始分析结果 */}
        {details?.rawResult && (
          <div>
            <button
              type="button"
              onClick={() => setShowRaw(!showRaw)}
              className="w-full flex items-center justify-between p-2.5 rounded-lg bg-elevated hover:bg-hover transition-colors"
            >
              <span className="text-xs text-white">原始分析结果</span>
              <svg
                className={`w-3.5 h-3.5 text-muted transition-transform ${showRaw ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showRaw && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(details.rawResult)}
              </div>
            )}
          </div>
        )}

        {/* 分析快照 */}
        {details?.contextSnapshot && (
          <div>
            <button
              type="button"
              onClick={() => setShowSnapshot(!showSnapshot)}
              className="w-full flex items-center justify-between p-2.5 rounded-lg bg-elevated hover:bg-hover transition-colors"
            >
              <span className="text-xs text-white">分析快照</span>
              <svg
                className={`w-3.5 h-3.5 text-muted transition-transform ${showSnapshot ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showSnapshot && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(details.contextSnapshot)}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};
