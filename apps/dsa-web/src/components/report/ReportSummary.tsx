import React from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
}

/**
 * 完整报告展示组件
 * 整合概览、策略、资讯、详情四个区域
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  // 使用 report id，因为 queryId 在批量分析时可能重复，且历史报告详情接口需要 recordId 来获取关联资讯和详情数据
  const recordId = report.meta.id;

  const { meta, summary, strategy, details } = report;
  const reportLanguage = normalizeReportLanguage(meta.reportLanguage);
  const text = getReportText(reportLanguage);
  const modelUsed = (meta.modelUsed || '').trim();
  const shouldShowModel = Boolean(
    modelUsed && !['unknown', 'error', 'none', 'null', 'n/a'].includes(modelUsed.toLowerCase()),
  );

  return (
    <div className="space-y-5 pb-8 animate-fade-in">
      {/* 概览区（首屏） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        details={details}
        isHistory={isHistory}
      />

      {/* 策略点位区 */}
      <ReportStrategy strategy={strategy} language={reportLanguage} />

      {/* 资讯区 */}
      <ReportNews recordId={recordId} limit={8} language={reportLanguage} />

      {/* 透明度与追溯区 */}
      <ReportDetails details={details} recordId={recordId} language={reportLanguage} />

      {/* 分析模型标记（Issue #528）— 报告末尾 */}
      {shouldShowModel && (
        <p className="px-1 text-xs text-muted-text">
          {text.analysisModel}: {modelUsed}
        </p>
      )}
    </div>
  );
};
