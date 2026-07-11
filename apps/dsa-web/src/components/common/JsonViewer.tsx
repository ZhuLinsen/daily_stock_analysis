import React, { useState } from 'react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface JsonViewerProps {
  data: Record<string, unknown> | unknown[] | null | undefined;
  maxHeight?: string;
  className?: string;
}

const JSON_TOKEN_PATTERN = /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|true|false|null/g;

function getTokenClassName(token: string, remainingLine: string): string {
  if (token.startsWith('"')) {
    return /^\s*:/.test(remainingLine) ? 'text-cyan-400' : 'text-emerald-400';
  }
  if (token === 'true' || token === 'false' || token === 'null') {
    return 'text-purple-400';
  }
  return 'text-amber-400';
}

function renderHighlightedLine(line: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const matcher = new RegExp(JSON_TOKEN_PATTERN);
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = matcher.exec(line)) !== null) {
    if (match.index > lastIndex) {
      parts.push(line.slice(lastIndex, match.index));
    }

    const token = match[0];
    const nextIndex = match.index + token.length;
    parts.push(
      <span key={`${match.index}-${token}`} className={getTokenClassName(token, line.slice(nextIndex))}>
        {token}
      </span>,
    );
    lastIndex = nextIndex;
  }

  if (lastIndex < line.length) {
    parts.push(line.slice(lastIndex));
  }

  return parts;
}

/**
 * JSON 结构化展示组件
 * 支持语法高亮和折叠
 */
export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  maxHeight = '400px',
  className = '',
}) => {
  const [copied, setCopied] = useState(false);
  const { t } = useUiLanguage();

  if (!data) {
    return (
      <div className="text-gray-500 italic py-4 text-center">{t('common.noData')}</div>
    );
  }

  const jsonString = JSON.stringify(data, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const highlightJson = (json: string): React.ReactNode => {
    return json.split('\n').map((line, index) => {
      return (
        <div key={index} className="leading-relaxed">
          {renderHighlightedLine(line)}
        </div>
      );
    });
  };

  return (
    <div className={`relative ${className}`}>
      {/* 复制按钮 */}
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs rounded
          bg-slate-700 hover:bg-slate-600 text-gray-300
          transition-colors z-10"
      >
        {copied ? t('common.copied') : t('common.copy')}
      </button>

      {/* JSON 内容 */}
      <div
        className="bg-slate-900/80 rounded-lg p-4 overflow-auto custom-scrollbar
          border border-slate-700/50 font-mono text-sm text-gray-300"
        style={{ maxHeight }}
      >
        <pre className="whitespace-pre-wrap break-words">
          {highlightJson(jsonString)}
        </pre>
      </div>
    </div>
  );
};
