import type React from 'react';
import type {
  MarketReviewCatalyst,
  MarketReviewNextSessionPlan,
  MarketReviewWorkbenchSummary,
} from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { hasNextSessionPlanContent } from './marketReviewModuleMatching';

/**
 * 复盘工作台展示子组件（Issue #1584），由模块卡（MarketReviewModules.tsx）复用。
 *
 * 所有字段均为可选：字段缺失时对应模块整体不渲染，由父组件按 presence 控制，
 * 保证旧 payload（无工作台字段）的渲染结果与历史版本完全一致。
 * 文案标签由父组件按报告语言传入，本文件不维护自己的 i18n 表。
 */
export interface WorkbenchLabels {
  temperature: string;
  marketState: string;
  suggestedPosition: string;
  structureNote: string;
  weightNote: string;
  divergence: string;
  rotationStrong: string;
  rotationWeak: string;
  catalystTitle: string;
  nature: string;
  scope: string;
  duration: string;
  digestion: string;
  catalystComment: string;
  positionAdvice: string;
  focus: string;
  avoid: string;
  keyLevels: string;
  riskTriggers: string;
  dataQualityNotes: string;
  moduleConclusion: string;
  moduleIndices: string;
  moduleBreadth: string;
  moduleSectors: string;
  moduleCatalysts: string;
  modulePlan: string;
  close: string;
  amountHeader: string;
  indexHeader: string;
  changeHeader: string;
  maStatusHeader: string;
  sectorHeader: string;
  leaderHeader: string;
  persistenceHeader: string;
  commentHeader: string;
  rotationJudgment: string;
  leading: string;
  lagging: string;
}

const natureBadgeClass = (nature?: string): string => {
  const value = (nature || '').toLowerCase();
  if (value.includes('利好') || value.includes('bull') || value.includes('positive')) {
    return 'bg-success/10 text-success';
  }
  if (value.includes('利空') || value.includes('bear') || value.includes('negative')) {
    return 'bg-danger/10 text-danger';
  }
  return 'bg-primary/10 text-secondary-text';
};

interface WorkbenchSummaryProps {
  summary?: MarketReviewWorkbenchSummary;
  labels: WorkbenchLabels;
  /** 模块卡形态：结论句放大展示 */
  emphasizeConclusion?: boolean;
}

export const WorkbenchSummaryBody: React.FC<WorkbenchSummaryProps> = ({
  summary,
  labels,
  emphasizeConclusion = false,
}) => {
  if (!summary) {
    return null;
  }
  const noteRows: Array<{ label: string; value: string }> = [];
  if (summary?.structureNote) {
    noteRows.push({ label: labels.structureNote, value: summary.structureNote });
  }
  if (summary?.weightStockNote) {
    noteRows.push({ label: labels.weightNote, value: summary.weightStockNote });
  }

  return (
    <div data-testid="workbench-summary">
      {summary?.coreConclusion ? (
        <p
          className={
            emphasizeConclusion
              ? 'text-lg font-semibold leading-7 text-foreground'
              : 'text-sm font-semibold leading-6 text-foreground'
          }
        >
          {summary.coreConclusion}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {summary?.temperatureScore !== undefined ? (
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold text-white"
            style={{ backgroundColor: getSentimentColor(summary.temperatureScore) }}
          >
            {labels.temperature} {summary.temperatureScore}/100
            {summary.temperatureLabel ? ` · ${summary.temperatureLabel}` : ''}
          </span>
        ) : null}
        {summary?.marketState ? (
          <span className="home-accent-chip rounded-full px-2 py-0.5 font-semibold">
            {labels.marketState} {summary.marketState}
          </span>
        ) : null}
        {summary?.suggestedPosition ? (
          <span className="home-accent-chip rounded-full px-2 py-0.5 font-semibold">
            {labels.suggestedPosition} {summary.suggestedPosition}
          </span>
        ) : null}
      </div>
      {noteRows.length > 0 ? (
        <div className="mt-2 space-y-1 text-sm leading-6 text-secondary-text">
          {noteRows.map(({ label, value }) => (
            <p key={label}>
              <span className="font-medium text-foreground">{label}</span>
              {'：'}
              {value}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
};

interface CatalystsTableProps {
  catalysts?: MarketReviewCatalyst[];
  labels: WorkbenchLabels;
}

export const CatalystsTableBody: React.FC<CatalystsTableProps> = ({ catalysts, labels }) => {
  const rows = (catalysts || []).filter((item) => item?.title);
  if (rows.length === 0) {
    return null;
  }
  return (
    <div data-testid="workbench-catalysts" className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="text-left text-xs uppercase text-muted-text">
          <tr>
            <th className="px-2 py-2">{labels.catalystTitle}</th>
            <th className="px-2 py-2">{labels.nature}</th>
            <th className="px-2 py-2">{labels.scope}</th>
            <th className="px-2 py-2">{labels.duration}</th>
            <th className="px-2 py-2">{labels.digestion}</th>
            <th className="px-2 py-2">{labels.catalystComment}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-subtle">
          {rows.map((item, index) => (
            <tr key={`${item.title}-${index}`}>
              <td className="px-2 py-2 text-foreground">{item.title}</td>
              <td className="px-2 py-2">
                {item.nature ? (
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${natureBadgeClass(item.nature)}`}>
                    {item.nature}
                  </span>
                ) : (
                  '-'
                )}
              </td>
              <td className="px-2 py-2 text-secondary-text">{item.scope || '-'}</td>
              <td className="px-2 py-2 text-secondary-text">{item.duration || '-'}</td>
              <td className="px-2 py-2 text-secondary-text">{item.digestion || '-'}</td>
              <td className="px-2 py-2 text-secondary-text">{item.comment || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

interface NextSessionPlanProps {
  plan?: MarketReviewNextSessionPlan;
  labels: WorkbenchLabels;
}

export const NextSessionPlanBody: React.FC<NextSessionPlanProps> = ({ plan, labels }) => {
  if (!hasNextSessionPlanContent(plan) || !plan) {
    return null;
  }
  const chipRows: Array<{ label: string; values: string[] }> = [];
  if (plan.focusSectors?.length) {
    chipRows.push({ label: labels.focus, values: plan.focusSectors });
  }
  if (plan.avoidSectors?.length) {
    chipRows.push({ label: labels.avoid, values: plan.avoidSectors });
  }
  const listRows: Array<{ label: string; values: string[] }> = [];
  if (plan.keyLevels?.length) {
    listRows.push({ label: labels.keyLevels, values: plan.keyLevels });
  }
  if (plan.riskTriggers?.length) {
    listRows.push({ label: labels.riskTriggers, values: plan.riskTriggers });
  }
  return (
    <div data-testid="workbench-next-session-plan" className="space-y-2 text-sm leading-6">
      {plan.positionAdvice ? (
        <p className="text-foreground">
          <span className="font-medium">{labels.positionAdvice}</span>
          {'：'}
          {plan.positionAdvice}
        </p>
      ) : null}
      {chipRows.map(({ label, values }) => (
        <div key={label} className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium text-muted-text">{label}</span>
          {values.map((value) => (
            <span key={value} className="home-accent-chip rounded-full px-2 py-0.5 text-xs">
              {value}
            </span>
          ))}
        </div>
      ))}
      {listRows.map(({ label, values }) => (
        <div key={label}>
          <span className="text-xs font-medium text-muted-text">{label}</span>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-secondary-text">
            {values.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
};

interface WorkbenchDataQualityNotesProps {
  notes?: string[];
  labels: WorkbenchLabels;
}

export const WorkbenchDataQualityNotes: React.FC<WorkbenchDataQualityNotesProps> = ({ notes, labels }) => {
  const rows = (notes || []).filter(Boolean);
  if (rows.length === 0) {
    return null;
  }
  return (
    <div data-testid="workbench-data-quality" className="text-xs text-muted-text">
      <p className="font-medium">{labels.dataQualityNotes}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {rows.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
};
