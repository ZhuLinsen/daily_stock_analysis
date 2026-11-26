import React, { useEffect, useRef, useState } from 'react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { copyTextToClipboard } from '../../utils/clipboard';

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
  const jsonString = data ? JSON.stringify(data, null, 2) : '';
  const [copyState, setCopyState] = useState<{ key: string; status: 'idle' | 'copied' | 'failed' }>({
    key: jsonString,
    status: 'idle',
  });
  const [prevJsonString, setPrevJsonString] = useState(jsonString);
  if (prevJsonString !== jsonString) {
    setPrevJsonString(jsonString);
    setCopyState({ key: jsonString, status: 'idle' });
  }
  const resetTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const copyTokenRef = useRef(0);
  const { t } = useUiLanguage();

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      copyTokenRef.current += 1;
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    copyTokenRef.current += 1;
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, [jsonString]);

  if (!data) {
    return (
      <div className="text-gray-500 italic py-4 text-center">{t('common.noData')}</div>
    );
  }

  const handleCopy = async () => {
    const token = ++copyTokenRef.current;
    const targetKey = jsonString;
    const ok = await copyTextToClipboard(jsonString, {
      shouldFallback: () => mountedRef.current && copyTokenRef.current === token,
    });
    if (!mountedRef.current || copyTokenRef.current !== token) {
      return;
    }
    setCopyState({ key: targetKey, status: ok ? 'copied' : 'failed' });
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    resetTimerRef.current = window.setTimeout(() => {
      resetTimerRef.current = null;
      if (!mountedRef.current || copyTokenRef.current !== token) {
        return;
      }
      setCopyState({ key: targetKey, status: 'idle' });
    }, 2000);
  };

  const copyStatus = copyState.key === jsonString ? copyState.status : 'idle';
  const copyLabel =
    copyStatus === 'copied'
      ? t('common.copied')
      : copyStatus === 'failed'
        ? t('common.copyFailed')
        : t('common.copy');

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
        type="button"
        onClick={() => void handleCopy()}
        aria-label={copyLabel}
        className={`absolute top-2 right-2 px-2 py-1 text-xs rounded
          bg-slate-700 hover:bg-slate-600 transition-colors z-10 ${
            copyStatus === 'failed' ? 'text-rose-300' : 'text-gray-300'
          }`}
      >
        {copyLabel}
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
