import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import type { ReportDetails as ReportDetailsType, ReportLanguage } from '../../types/analysis';
import type { QuantIndicatorReading, QuantSignalEvent } from '../../types/analysis';
import { Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportDetailsProps {
  details?: ReportDetailsType;
  recordId?: number;  // 分析历史记录主键 ID
  language?: ReportLanguage;
}

/**
 * 透明度与追溯区组件 - 终端风格
 */
export const ReportDetails: React.FC<ReportDetailsProps> = ({
  details,
  recordId,
  language = 'zh',
}) => {
  type JsonPanel = 'raw' | 'snapshot';
  type CopiedPanelState = Record<JsonPanel, boolean>;

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const [showRaw, setShowRaw] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [copiedPanels, setCopiedPanels] = useState<CopiedPanelState>({
    raw: false,
    snapshot: false,
  });
  const copyResetTimerRef = useRef<Partial<Record<JsonPanel, number>>>({});

  useEffect(() => {
    return () => {
      Object.values(copyResetTimerRef.current).forEach((timerId) => {
        if (timerId !== undefined) {
          window.clearTimeout(timerId);
        }
      });
      copyResetTimerRef.current = {};
    };
  }, []);

  if (!details?.rawResult && !details?.contextSnapshot && !details?.quantEnrichment && !recordId) {
    return null;
  }

  const copyToClipboard = async (content: string, panel: JsonPanel) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedPanels((prev) => ({
        ...prev,
        [panel]: true,
      }));
      const existingTimer = copyResetTimerRef.current[panel];
      if (existingTimer !== undefined) {
        window.clearTimeout(existingTimer);
      }
      copyResetTimerRef.current[panel] = window.setTimeout(() => {
        setCopiedPanels((prev) => ({
          ...prev,
          [panel]: false,
        }));
        delete copyResetTimerRef.current[panel];
      }, 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const renderJson = (data: unknown, panel: JsonPanel) => {
    const jsonStr = JSON.stringify(data, null, 2);
    return (
      <div className="relative overflow-hidden">
        <span className="absolute top-2 right-2 z-10 inline-flex">
          <button
            type="button"
            onClick={() => copyToClipboard(jsonStr, panel)}
            className="home-accent-link text-xs text-muted-text"
            aria-label={copiedPanels[panel] ? text.copied : text.copy}
          >
            {copiedPanels[panel] ? text.copied : text.copy}
          </button>
        </span>
        <pre className="home-trace-pre home-trace-pre-content text-xs text-foreground font-mono overflow-x-auto p-3 bg-base rounded-lg max-h-80 overflow-y-auto text-left w-0 min-w-full">
          {jsonStr}
        </pre>
      </div>
    );
  };

  const directionLabel = (direction?: string) => direction === 'bullish' ? '偏多' : direction === 'bearish' ? '偏空' : '中性';
  const directionClass = (direction?: string) => direction === 'bullish' ? 'text-success' : direction === 'bearish' ? 'text-danger' : 'text-secondary-text';
  const renderReadings = (readings: QuantIndicatorReading[] = []) => readings.length ? (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="min-w-[920px] w-full text-xs">
        <thead className="bg-base/60 text-left text-muted-text"><tr>
          <th className="p-2">类别</th><th className="p-2">指标与参数</th><th className="p-2">当前值</th>
          <th className="p-2">状态</th><th className="p-2">判断依据</th>
        </tr></thead>
        <tbody className="divide-y divide-border">{readings.map((reading, index) => (
          <tr key={`${reading.indicator || 'indicator'}-${index}`}>
            <td className="p-2 text-secondary-text">{reading.category || '-'}</td>
            <td className="p-2"><p className="font-medium text-foreground">{reading.indicator || '-'}</p><p className="mt-0.5 text-muted-text">{reading.parameters || '-'}</p></td>
            <td className="p-2 font-mono text-foreground">{reading.values || '-'}</td>
            <td className={`p-2 font-medium ${directionClass(reading.direction)}`}>{directionLabel(reading.direction)} · {reading.status || '-'}</td>
            <td className="p-2 text-secondary-text">{reading.rationale || '-'}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  ) : <p className="text-sm text-muted-text">暂无指标明细</p>;

  const renderEvents = (events: QuantSignalEvent[] = []) => events.length ? (
    <div className="space-y-2">{events.map((event, index) => (
      <div key={event.eventId || `${event.date}-${event.name}-${index}`} className="rounded-lg border border-border px-3 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-muted-text">{event.date || '-'}</span>
          <span className="home-accent-chip px-1.5 py-0.5">{event.timeframe === '1w' ? '周线' : '日线'}</span>
          <span className={`font-semibold ${directionClass(event.direction)}`}>{directionLabel(event.direction)} · {event.name || '-'}</span>
        </div>
        <p className="mt-1 text-secondary-text">{event.detail || '-'}</p>
      </div>
    ))}</div>
  ) : <p className="text-sm text-muted-text">所选时间窗口内没有新信号</p>;

  return (
    <div className="space-y-4">
    {details?.quantEnrichment && (
      <Card variant="bordered" padding="md" className="home-panel-card text-left">
        <DashboardPanelHeader eyebrow="ABU · Kronos · vn.py" title="量化增强分析" className="mb-3" />
        {details.quantEnrichment.status !== 'ok' ? (
          <p className="text-sm text-warning">量化增强不可用：{details.quantEnrichment.error || '未知原因'}</p>
        ) : (() => {
          const quant = details.quantEnrichment;
          const technical = quant.technical;
          const events = technical?.events || [];
          const recentDays = technical?.recentDays || 7;
          const asOf = quant.asOf ? new Date(`${quant.asOf}T00:00:00`).getTime() : 0;
          const recentEvents = events.filter((event) => {
            if (!event.date) return false;
            if (event.timeframe === '1w') return true;
            return !asOf || asOf - new Date(`${event.date}T00:00:00`).getTime() <= recentDays * 86400000;
          }).slice(-30).reverse();
          const newIds = new Set(technical?.newEventIds || []);
          const newEvents = events.filter((event) => event.eventId && newIds.has(event.eventId)).reverse();
          const positiveRatio = quant.kronos?.positivePathRatio ?? 0;
          return <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-text">ABU 规则信号</p>
              <p className="mt-1 text-sm font-medium">{quant.dataQuality?.status || '未检查'} · {quant.asOf || 'N/A'}</p>
              <p className="mt-1 text-xs text-muted-text">近期规则偏向：{quant.kronos?.abuBias || '中性'}</p>
              <p className="mt-1 text-xs text-muted-text">{quant.dataQuality?.summary || quant.source || ''}</p>
            </div>
            <div className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-text">Kronos 概率预测</p>
              {quant.kronos ? <>
                <p className="mt-1 text-sm font-medium">{quant.kronos.points?.length || 0}日中位收益 {(quant.kronos.endReturnPct ?? 0).toFixed(2)}%</p>
                <p className="mt-1 text-xs text-muted-text">上涨路径 {(positiveRatio * 100).toFixed(0)}% · 下跌路径 {((1 - positiveRatio) * 100).toFixed(0)}% · {quant.kronos.pathCount || 0}条</p>
                <p className="mt-1 text-xs text-muted-text">终点区间 {(quant.kronos.endReturnLowPct ?? 0).toFixed(2)}% ～ {(quant.kronos.endReturnHighPct ?? 0).toFixed(2)}%</p>
              </> : <p className="mt-1 text-sm text-muted-text">未启用</p>}
            </div>
            <div className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-text">vn.py 历史评价</p>
              {quant.validation?.status === 'ok' ? <>
                <p className="mt-1 text-sm font-medium">样本 {quant.validation.sampleCount || 0} · 胜率 {((quant.validation.directionWinRate ?? 0) * 100).toFixed(1)}%</p>
                <p className="mt-1 text-xs text-muted-text">{quant.validation.horizonDays || 5}日收益中位数 {((quant.validation.medianDirectionalReturn ?? 0) * 100).toFixed(2)}% · 最大不利波动 {((quant.validation.maxAdverseExcursion ?? 0) * 100).toFixed(2)}%</p>
                <p className="mt-1 text-xs text-muted-text">可信度 {quant.validation.confidence || 'low'}</p>
              </> : <p className="mt-1 text-sm text-muted-text">{quant.validation?.message || '样本不足'}</p>}
            </div>
          </div>
          {quant.kronos?.combinedView && <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-foreground"><span className="font-semibold">综合判断：</span>{quant.kronos.combinedView}</div>}
          {!!quant.adjustments?.length && <div><h4 className="mb-2 text-sm font-semibold text-foreground">数据与复权说明</h4>{quant.adjustments.map((item) => <p key={item} className="text-xs text-warning">{item}</p>)}</div>}
          <details open className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-semibold text-foreground">日线当前状态与完整指标</summary><div className="mt-3 space-y-3"><div className="grid gap-1 sm:grid-cols-2">{(technical?.states || []).map((state) => <p className="text-xs text-secondary-text" key={state}>{state}</p>)}</div>{renderReadings(technical?.indicatorReadings)}</div></details>
          <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-semibold text-foreground">周线当前状态与完整指标</summary><div className="mt-3 space-y-3"><div className="grid gap-1 sm:grid-cols-2">{(technical?.weeklyStates || []).map((state) => <p className="text-xs text-secondary-text" key={state}>{state}</p>)}</div>{renderReadings(technical?.weeklyIndicatorReadings)}</div></details>
          <details open className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-semibold text-foreground">本次首次发现与近期信号</summary><div className="mt-3 space-y-4">{!!newEvents.length && <div><h5 className="mb-2 text-xs font-semibold text-foreground">本次首次发现</h5>{renderEvents(newEvents)}</div>}<div><h5 className="mb-2 text-xs font-semibold text-foreground">最近 {recentDays} 日及 8 周信号</h5>{renderEvents(recentEvents)}</div></div></details>
          {!!quant.kronos?.points?.length && <details open className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-semibold text-foreground">Kronos 五日预测路径明细</summary><div className="mt-3 overflow-x-auto"><table className="min-w-[720px] w-full text-xs"><thead className="text-left text-muted-text"><tr><th className="p-2">日期</th><th className="p-2">预测开盘</th><th className="p-2">预测最高</th><th className="p-2">预测最低</th><th className="p-2">预测收盘中位</th><th className="p-2">收盘区间</th></tr></thead><tbody className="divide-y divide-border">{quant.kronos.points.map((point) => <tr key={point.date}><td className="p-2">{point.date}</td><td className="p-2 font-mono">{point.open?.toFixed(3)}</td><td className="p-2 font-mono">{point.high?.toFixed(3)}</td><td className="p-2 font-mono">{point.low?.toFixed(3)}</td><td className="p-2 font-mono">{point.close?.toFixed(3)}</td><td className="p-2 font-mono">{point.closeLow?.toFixed(3)} ～ {point.closeHigh?.toFixed(3)}</td></tr>)}</tbody></table></div></details>}
          {!!quant.validation?.signalSignatures?.length && <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm font-semibold text-foreground">vn.py 匹配的历史信号组合</summary><div className="mt-3 flex flex-wrap gap-2">{quant.validation.signalSignatures.map((item) => <span key={item} className="home-accent-chip px-2 py-1 text-xs">{item}</span>)}</div></details>}
          </div>;
        })()}
        <p className="mt-3 text-xs text-muted-text">ABU展示规则信号，Kronos展示概率路径；vn.py只评价历史结果，不是另一项预测。</p>
      </Card>
    )}
    {(details?.rawResult || details?.contextSnapshot || recordId) && (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <DashboardPanelHeader
        eyebrow={text.transparency}
        title={text.traceability}
        className="mb-3"
      />

      {/* Record ID */}
      {recordId && (
        <div className="home-divider mb-3 flex items-center gap-2 border-b pb-3 text-xs text-muted-text">
          <span>{text.recordId}:</span>
          <code className="home-accent-chip px-1.5 py-0.5 font-mono text-xs">
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
              className="home-surface-button home-trace-toggle flex w-full items-center justify-between rounded-lg p-2.5"
            >
              <span className="text-xs text-foreground">{text.rawResult}</span>
              <svg
                className={`w-3.5 h-3.5 text-muted-text transition-transform ${showRaw ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showRaw && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(details.rawResult, 'raw')}
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
              className="home-surface-button home-trace-toggle flex w-full items-center justify-between rounded-lg p-2.5"
            >
              <span className="text-xs text-foreground">{text.analysisSnapshot}</span>
              <svg
                className={`w-3.5 h-3.5 text-muted-text transition-transform ${showSnapshot ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showSnapshot && (
              <div className="mt-2 animate-fade-in min-w-0 overflow-hidden">
                {renderJson(details.contextSnapshot, 'snapshot')}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
    )}
    </div>
  );
};
