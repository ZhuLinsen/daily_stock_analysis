import type React from 'react';
import {
  Activity,
  BarChart3,
  CalendarClock,
  FileText,
  Gauge,
  Newspaper,
  TrendingUp,
} from 'lucide-react';
import type {
  MarketReviewBreadth,
  MarketReviewCatalyst,
  MarketReviewIndex,
  MarketReviewNextSessionPlan,
  MarketReviewPayloadSection,
  MarketReviewStyleRotation,
  MarketReviewWorkbenchSummary,
  SectorRankingItem,
  SectorRankings,
} from '../../types/analysis';
import { Card } from '../common';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import {
  CatalystsTableBody,
  NextSessionPlanBody,
  WorkbenchDataQualityNotes,
  WorkbenchSummaryBody,
  type WorkbenchLabels,
} from './MarketReviewWorkbench';
import {
  formatIndexAmount,
  formatSectionNumber,
  hasNextSessionPlanContent,
  matchSectionsToModules,
  stripInjectedTables,
  stripSectionNumbering,
} from './marketReviewModuleMatching';

/**
 * 复盘工作台的六个模块卡（Issue #1584，参考截图的分节形态）。
 *
 * 每个模块按字段存在与否独立渲染（渐进增强），并吸收对应叙事 section 的
 * LLM 正文；未匹配的 section 作为叙事卡渲染在模块之后。旧 payload（无
 * 工作台字段）不会进入本组件，走既有展示路径。
 */

export interface StructuredMarketData {
  id: string;
  title?: string;
  breadth?: MarketReviewBreadth;
  indices: MarketReviewIndex[];
  sectors?: SectorRankings;
  concepts?: SectorRankings;
  summary?: MarketReviewWorkbenchSummary;
  styleRotation?: MarketReviewStyleRotation;
  catalysts?: MarketReviewCatalyst[];
  nextSessionPlan?: MarketReviewNextSessionPlan;
  dataQuality?: { notes?: string[] };
}

const hasRankingRows = (rankings?: SectorRankings): boolean =>
  Boolean(rankings?.top?.length || rankings?.bottom?.length);

const formatChangePct = (value: unknown): string => {
  const numeric = typeof value === 'number' ? value : Number(String(value ?? '').replace(/%$/, ''));
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
};

const changePctClass = (value: unknown): string => {
  const numeric = typeof value === 'number' ? value : Number(String(value ?? '').replace(/%$/, ''));
  if (!Number.isFinite(numeric) || numeric === 0) {
    return 'text-secondary-text';
  }
  return numeric > 0 ? 'text-success' : 'text-danger';
};

interface ModuleCardProps {
  icon: typeof FileText;
  title: string;
  testId: string;
  prose?: string;
  children?: React.ReactNode;
}

const ModuleCard: React.FC<ModuleCardProps> = ({ icon: Icon, title, testId, prose, children }) => (
  <Card variant="bordered" padding="md" className="home-panel-card text-left">
    {/* Card 不透传 data-* 属性，testid 落在内层包裹元素上 */}
    <div data-testid={testId}>
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
      </div>
      {children}
      {prose ? (
        <div className={children ? 'mt-3 border-t border-subtle pt-3' : undefined}>
          <ReportMarkdownBody content={prose} className="market-review-markdown" />
        </div>
      ) : null}
    </div>
  </Card>
);

const SectorTable: React.FC<{
  caption: string;
  rows: SectorRankingItem[];
  labels: WorkbenchLabels;
}> = ({ caption, rows, labels }) => {
  if (!rows.length) {
    return null;
  }
  const showExtras = rows.some((row) => row.leader || row.persistence || row.comment);
  return (
    <div>
      <p className="label-uppercase mb-1.5">{caption}</p>
      <div className="overflow-x-auto">
        {/* 两列形态：板块列固定 56%（取自弱板块表的自然比例），强/弱两表涨跌幅列对齐；
            五列形态维持内容自适应布局 */}
        <table className={`min-w-full text-sm ${showExtras ? '' : 'table-fixed'}`}>
          <thead className="text-left text-xs uppercase text-muted-text">
            <tr>
              <th className={`px-2 py-2 ${showExtras ? '' : 'w-[56%]'}`}>{labels.sectorHeader}</th>
              <th className="px-2 py-2">{labels.changeHeader}</th>
              {showExtras ? (
                <>
                  <th className="px-2 py-2">{labels.leaderHeader}</th>
                  <th className="px-2 py-2">{labels.persistenceHeader}</th>
                  <th className="px-2 py-2">{labels.commentHeader}</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle">
            {rows.slice(0, 5).map((item, index) => (
              <tr key={`${item.name}-${index}`}>
                <td className="px-2 py-2 font-medium text-foreground">{item.name}</td>
                <td className={`px-2 py-2 font-mono ${changePctClass(item.changePct)}`}>
                  {formatChangePct(item.changePct)}
                </td>
                {showExtras ? (
                  <>
                    <td className="px-2 py-2 text-secondary-text">
                      {item.leader
                        ? `${item.leader}${item.leaderChangePct !== undefined ? ` ${formatChangePct(item.leaderChangePct)}` : ''}`
                        : '-'}
                    </td>
                    <td className="px-2 py-2 text-secondary-text">{item.persistence || '-'}</td>
                    <td className="px-2 py-2 text-secondary-text">{item.comment || '-'}</td>
                  </>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const ConceptPanels: React.FC<{
  concepts?: SectorRankings;
  conceptTitle: string;
  labels: WorkbenchLabels;
}> = ({ concepts, conceptTitle, labels }) => {
  if (!hasRankingRows(concepts)) {
    return null;
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {(['top', 'bottom'] as const).map((side) => {
        const rows = concepts?.[side] || [];
        if (!rows.length) {
          return null;
        }
        return (
          <div key={side} className="rounded-lg border border-subtle p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="label-uppercase">{conceptTitle}</p>
              <span className="text-xs text-secondary-text">
                {side === 'top' ? labels.leading : labels.lagging}
              </span>
            </div>
            <div className="space-y-1.5">
              {rows.slice(0, 5).map((item, index) => (
                <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate text-foreground">
                    {item.name}
                    {item.leader ? (
                      <span className="ml-1.5 text-xs text-muted-text">
                        · {labels.leaderHeader} {item.leader}
                        {item.leaderChangePct !== undefined ? ` ${formatChangePct(item.leaderChangePct)}` : ''}
                      </span>
                    ) : null}
                  </span>
                  <span className={`shrink-0 font-mono ${changePctClass(item.changePct)}`}>
                    {formatChangePct(item.changePct)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export interface MarketModulesGroupProps {
  market: StructuredMarketData;
  sections: MarketReviewPayloadSection[];
  labels: WorkbenchLabels;
  language: 'zh' | 'en';
  conceptTitle: string;
  breadthLabels: { advancers: string; decliners: string; limitUpDown: string; turnover: string };
  /** 多市场时的分组标题 */
  title?: string;
  /** 叙事卡图标复用父组件的匹配函数 */
  getNarrativeIcon: (title: string) => typeof FileText;
}

export const MarketReviewMarketModules: React.FC<MarketModulesGroupProps> = ({
  market,
  sections,
  labels,
  language,
  conceptTitle,
  breadthLabels,
  title,
  getNarrativeIcon,
}) => {
  const { modules, narrative } = matchSectionsToModules(sections);
  const prose = (key: keyof typeof modules): string | undefined => {
    const value = modules[key];
    return value ? stripInjectedTables(value) || undefined : undefined;
  };

  const summaryProse = prose('conclusion');
  const indicesProse = prose('indices');
  const breadthProse = prose('breadth');
  const sectorsProse = prose('sectors');
  const catalystsProse = prose('catalysts');
  const planProse = prose('plan');

  const showConclusion = Boolean(
    market.summary || market.dataQuality?.notes?.length || summaryProse,
  );
  const showIndices = Boolean(market.indices.length || indicesProse);
  const showBreadth = Boolean(market.breadth || breadthProse);
  const showSectors = Boolean(
    hasRankingRows(market.sectors)
    || hasRankingRows(market.concepts)
    || market.styleRotation?.strong?.length
    || market.styleRotation?.weak?.length
    || market.styleRotation?.comment
    || sectorsProse,
  );
  const showCatalysts = Boolean(market.catalysts?.some((item) => item?.title) || catalystsProse);
  const showPlan = Boolean(hasNextSessionPlanContent(market.nextSessionPlan) || planProse);

  const showIndexAmount = market.indices.some((index) => formatIndexAmount(index.amount, language));
  const showIndexTech = market.indices.some((index) => index.technicalStatus || index.comment);

  // 分组内连续编号（参考截图形态）：可见模块按序 一、二、…，
  // 叙事卡剥掉 LLM 原编号后接续，模块缺席时自动顺延不断号
  const moduleVisibility = [showConclusion, showIndices, showBreadth, showSectors, showCatalysts, showPlan];
  const numberedTitle = (position: number, moduleTitle: string): string =>
    formatSectionNumber(
      moduleVisibility.slice(0, position).filter(Boolean).length,
      moduleTitle,
      language,
    );
  const visibleModuleCount = moduleVisibility.filter(Boolean).length;

  return (
    <div className="space-y-4">
      {title ? (
        <h3 className="border-b border-subtle pb-2 text-base font-semibold text-foreground">{title}</h3>
      ) : null}

      {showConclusion ? (
        <ModuleCard icon={Gauge} title={numberedTitle(0, labels.moduleConclusion)} testId="module-conclusion" prose={summaryProse}>
          <WorkbenchSummaryBody summary={market.summary} labels={labels} emphasizeConclusion />
          <div className={market.summary ? 'mt-3' : undefined}>
            <WorkbenchDataQualityNotes notes={market.dataQuality?.notes} labels={labels} />
          </div>
        </ModuleCard>
      ) : null}

      {showIndices ? (
        <ModuleCard icon={BarChart3} title={numberedTitle(1, labels.moduleIndices)} testId="module-indices" prose={indicesProse}>
          {market.indices.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-xs uppercase text-muted-text">
                  <tr>
                    <th className="px-2 py-2">{labels.indexHeader}</th>
                    <th className="px-2 py-2">{labels.close}</th>
                    <th className="px-2 py-2">{labels.changeHeader}</th>
                    {showIndexAmount ? <th className="px-2 py-2">{labels.amountHeader}</th> : null}
                    {showIndexTech ? (
                      <>
                        <th className="px-2 py-2">{labels.maStatusHeader}</th>
                        <th className="px-2 py-2">{labels.commentHeader}</th>
                      </>
                    ) : null}
                  </tr>
                </thead>
                <tbody className="divide-y divide-subtle">
                  {market.indices.map((index) => (
                    <tr key={index.code || index.name}>
                      <td className="px-2 py-2 font-medium text-foreground">{index.name}</td>
                      <td className="px-2 py-2 font-mono text-secondary-text">{index.current ?? '-'}</td>
                      <td className={`px-2 py-2 font-mono ${changePctClass(index.changePct)}`}>
                        {formatChangePct(index.changePct)}
                      </td>
                      {showIndexAmount ? (
                        <td className="px-2 py-2 font-mono text-secondary-text">
                          {formatIndexAmount(index.amount, language) || '-'}
                        </td>
                      ) : null}
                      {showIndexTech ? (
                        <>
                          <td className="px-2 py-2 text-secondary-text">{index.technicalStatus ?? '-'}</td>
                          <td className="px-2 py-2 text-secondary-text">{index.comment ?? '-'}</td>
                        </>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </ModuleCard>
      ) : null}

      {showBreadth ? (
        <ModuleCard icon={Activity} title={numberedTitle(2, labels.moduleBreadth)} testId="module-breadth" prose={breadthProse}>
          {market.breadth ? (
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <div className="rounded-lg border border-subtle p-3">
                <p className="label-uppercase">{breadthLabels.advancers}</p>
                <p className="mt-1 font-semibold text-foreground">{market.breadth.upCount ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-subtle p-3">
                <p className="label-uppercase">{breadthLabels.decliners}</p>
                <p className="mt-1 font-semibold text-foreground">{market.breadth.downCount ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-subtle p-3">
                <p className="label-uppercase">{breadthLabels.limitUpDown}</p>
                <p className="mt-1 font-semibold text-foreground">
                  {market.breadth.limitUpCount ?? '-'} / {market.breadth.limitDownCount ?? '-'}
                </p>
              </div>
              <div className="rounded-lg border border-subtle p-3">
                <p className="label-uppercase">{breadthLabels.turnover}</p>
                <p className="mt-1 font-semibold text-foreground">
                  {typeof market.breadth.totalAmount === 'number'
                    ? Math.round(market.breadth.totalAmount).toLocaleString()
                    : market.breadth.totalAmount ?? '-'}{' '}
                  {market.breadth.turnoverUnit || ''}
                </p>
              </div>
            </div>
          ) : null}
          {market.breadth?.divergenceDiagnosis ? (
            <div className="mt-3 rounded-lg border border-subtle bg-primary/10 px-3 py-2 text-sm text-foreground">
              <span className="label-uppercase mr-2">{labels.divergence}</span>
              {market.breadth.divergenceDiagnosis}
            </div>
          ) : null}
        </ModuleCard>
      ) : null}

      {showSectors ? (
        <ModuleCard icon={TrendingUp} title={numberedTitle(3, labels.moduleSectors)} testId="module-sectors" prose={sectorsProse}>
          <div className="space-y-4">
            <SectorTable caption={labels.leading} rows={market.sectors?.top || []} labels={labels} />
            <SectorTable caption={labels.lagging} rows={market.sectors?.bottom || []} labels={labels} />
            <ConceptPanels concepts={market.concepts} conceptTitle={conceptTitle} labels={labels} />
            {market.styleRotation
              && (market.styleRotation.strong?.length
                || market.styleRotation.weak?.length
                || market.styleRotation.comment) ? (
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="label-uppercase">{labels.rotationJudgment}</span>
                {(market.styleRotation.strong || []).map((name) => (
                  <span key={`s-${name}`} className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">
                    {labels.rotationStrong} {name}
                  </span>
                ))}
                {(market.styleRotation.weak || []).map((name) => (
                  <span key={`w-${name}`} className="rounded-full bg-danger/10 px-2 py-0.5 text-xs font-semibold text-danger">
                    {labels.rotationWeak} {name}
                  </span>
                ))}
                {market.styleRotation.comment ? (
                  <span className="text-secondary-text">{market.styleRotation.comment}</span>
                ) : null}
              </div>
            ) : null}
          </div>
        </ModuleCard>
      ) : null}

      {showCatalysts ? (
        <ModuleCard icon={Newspaper} title={numberedTitle(4, labels.moduleCatalysts)} testId="module-catalysts" prose={catalystsProse}>
          <CatalystsTableBody catalysts={market.catalysts} labels={labels} />
        </ModuleCard>
      ) : null}

      {showPlan ? (
        <ModuleCard icon={CalendarClock} title={numberedTitle(5, labels.modulePlan)} testId="module-plan" prose={planProse}>
          <NextSessionPlanBody plan={market.nextSessionPlan} labels={labels} />
        </ModuleCard>
      ) : null}

      {narrative.map((section, index) => {
        const baseTitle = stripSectionNumbering(section.title || '') || section.title || 'Review';
        const sectionTitle = formatSectionNumber(visibleModuleCount + index, baseTitle, language);
        const Icon = getNarrativeIcon(sectionTitle);
        return (
          <Card
            key={`${market.id}-narrative-${section.key || index}`}
            variant="bordered"
            padding="md"
            className="home-panel-card text-left"
          >
            <div className="mb-3 flex items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="h-4 w-4" aria-hidden="true" />
              </span>
              <h3 className="text-base font-semibold text-foreground">{sectionTitle}</h3>
            </div>
            <ReportMarkdownBody content={section.markdown} className="market-review-markdown" />
          </Card>
        );
      })}
    </div>
  );
};
