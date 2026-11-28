import type React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Layers,
  Scale,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type { ReportDetails, ReportLanguage } from '../../types/analysis';
import { parseReportDashboard } from '../../utils/reportDashboard';
import {
  formatStrategySynthesisSummary,
  getReportText,
  localizeConflictSeverity,
  localizeConsensusLevel,
  localizeStrategySignal,
  localizeStrategySkillName,
  normalizeReportLanguage,
} from '../../utils/reportLanguage';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface ReportDecisionBriefProps {
  details?: ReportDetails;
  language?: ReportLanguage;
}

export const ReportDecisionBrief: React.FC<ReportDecisionBriefProps> = ({
  details,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const brief = parseReportDashboard(details);

  if (!brief) {
    return null;
  }

  const {
    riskAlerts,
    positionAdvice,
    positionStrategy,
    timeSensitivity,
    positiveCatalysts,
    earningsOutlook,
    sentimentSummary,
    signalAttribution,
    strategySynthesis,
    actionChecklist,
  } = brief;

  const hasPositionSection = Boolean(
    positionAdvice.noPosition
    || positionAdvice.hasPosition
    || positionStrategy.suggestedPosition
    || timeSensitivity,
  );
  const hasCatalystSection = Boolean(
    positiveCatalysts.length > 0 || earningsOutlook || sentimentSummary,
  );
  const hasAttributionSection = Boolean(signalAttribution);

  const attrLabels: Record<'technical' | 'news' | 'fundamentals' | 'market', string> = {
    technical: text.attrTechnical,
    news: text.attrNews,
    fundamentals: text.attrFundamentals,
    market: text.attrMarket,
  };

  const passCount = actionChecklist.filter((i) => i.status === 'pass').length;
  const warnCount = actionChecklist.filter((i) => i.status === 'warn').length;
  const failCount = actionChecklist.filter((i) => i.status === 'fail').length;

  const resolveSignalVariant = (signal: string): 'success' | 'danger' | 'info' => {
    const normalized = signal.trim().toLowerCase();
    if (normalized === 'strong_buy' || normalized === 'buy' || normalized === 'strong buy' || normalized === '买入' || normalized === '强烈买入') {
      return 'success';
    }
    if (normalized === 'strong_sell' || normalized === 'sell' || normalized === 'strong sell' || normalized === '卖出' || normalized === '强烈卖出') {
      return 'danger';
    }
    return 'info';
  };

  const resolveConsensusVariant = (level: string): 'success' | 'warning' | 'info' => {
    const normalized = level.trim().toLowerCase();
    if (normalized === 'high' || normalized === '高') return 'success';
    if (normalized === 'low' || normalized === 'insufficient' || normalized === '低' || normalized === '证据不足') return 'warning';
    return 'info';
  };

  const resolveConflictVariant = (severity: string, count: number): 'danger' | 'warning' | 'default' => {
    if (count === 0) return 'default';
    const normalized = severity.trim().toLowerCase();
    if (normalized === 'high' || normalized === '高') return 'danger';
    return 'warning';
  };

  return (
    <Card variant="bordered" padding="md" className="home-panel-card space-y-4 text-left">
      <DashboardPanelHeader
        eyebrow={text.decisionBriefEyebrow}
        title={text.decisionBriefTitle}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {positionStrategy.suggestedPosition ? (
              <Badge variant="info" className="shadow-none">
                {text.suggestedPositionLabel}: {positionStrategy.suggestedPosition}
              </Badge>
            ) : null}
            {timeSensitivity ? (
              <span className="home-accent-chip inline-flex items-center gap-1 px-2 py-0.5 text-xs">
                <Clock className="h-3 w-3" aria-hidden="true" />
                {timeSensitivity}
              </span>
            ) : null}
          </div>
        )}
      />

      {/* Alert-First 风险预警置顶区 */}
      {riskAlerts.length > 0 ? (
        <div
          role="region"
          aria-label={text.riskAlertsTitle}
          className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3"
        >
          <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-danger">
            <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{text.riskAlertsTitle}</span>
          </div>
          <ul className="space-y-1 pl-5 text-sm leading-6 text-foreground list-disc">
            {riskAlerts.map((alert, idx) => (
              <li key={`${idx}-${alert.slice(0, 24)}`}>{alert}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* 仓位应对策略 */}
      {hasPositionSection && (positionAdvice.noPosition || positionAdvice.hasPosition) ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-text">
            <Scale className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{text.positionPlaybookTitle}</span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="home-subpanel p-3.5">
              <div className="mb-1 text-xs font-semibold text-secondary-text">
                {text.noPositionLabel}
              </div>
              <p className="text-sm leading-6 text-foreground">
                {positionAdvice.noPosition || text.noValue}
              </p>
            </div>
            <div className="home-subpanel p-3.5">
              <div className="mb-1 text-xs font-semibold text-secondary-text">
                {text.hasPositionLabel}
              </div>
              <p className="text-sm leading-6 text-foreground">
                {positionAdvice.hasPosition || text.noValue}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {/* 利好催化 & 多空归因 */}
      {(hasCatalystSection || hasAttributionSection) ? (
        <div className={`grid grid-cols-1 gap-3 ${hasCatalystSection && hasAttributionSection ? 'md:grid-cols-2' : ''}`}>
          {hasCatalystSection ? (
            <div className="home-subpanel space-y-2 p-3.5">
              {positiveCatalysts.length > 0 ? (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-success">
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>{text.positiveCatalystsTitle}</span>
                  </div>
                  <ul className="space-y-1 pl-4 text-xs leading-5 text-foreground list-disc">
                    {positiveCatalysts.map((item, idx) => (
                      <li key={`${idx}-${item.slice(0, 20)}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {earningsOutlook ? (
                <p className="text-xs leading-5 text-secondary-text">
                  <strong className="text-foreground">{text.earningsOutlookLabel}:</strong> {earningsOutlook}
                </p>
              ) : null}
              {sentimentSummary ? (
                <p className="text-xs leading-5 text-secondary-text">
                  <strong className="text-foreground">{text.sentimentSummaryLabel}:</strong> {sentimentSummary}
                </p>
              ) : null}
            </div>
          ) : null}

          {hasAttributionSection && signalAttribution ? (
            <div className="home-subpanel space-y-2.5 p-3.5">
              <div className="text-xs font-semibold uppercase tracking-wider text-secondary-text">
                {text.signalAttributionTitle}
              </div>
              {signalAttribution.weights.length > 0 ? (
                <div className="space-y-1.5">
                  {signalAttribution.weights.map((item) => {
                    const widthPct = Math.max(0, Math.min(100, item.value));
                    return (
                      <div key={item.key} className="grid grid-cols-[72px_1fr_36px] items-center gap-2 text-xs">
                        <span className="truncate text-secondary-text">{attrLabels[item.key]}</span>
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-border/60">
                          <div
                            className="h-full rounded-full bg-[hsl(var(--primary))]"
                            style={{ width: `${widthPct}%` }}
                          />
                        </div>
                        <span className="num text-right font-mono text-muted-text">{Math.round(item.value)}%</span>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {(signalAttribution.strongestBullish || signalAttribution.strongestBearish) ? (
                <div className="space-y-1 pt-1 text-xs leading-5">
                  {signalAttribution.strongestBullish ? (
                    <div className="flex items-start gap-1.5 text-success">
                      <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      <span>
                        <strong>{text.strongestBullishLabel}:</strong> {signalAttribution.strongestBullish}
                      </span>
                    </div>
                  ) : null}
                  {signalAttribution.strongestBearish ? (
                    <div className="flex items-start gap-1.5 text-danger">
                      <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      <span>
                        <strong>{text.strongestBearishLabel}:</strong> {signalAttribution.strongestBearish}
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 执行检查清单 */}
      {actionChecklist.length > 0 ? (
        <div className="home-subpanel space-y-2 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-secondary-text">
              {text.checklistTitle}
            </span>
            <span className="text-xs text-muted-text">
              {text.checklistPass} {passCount} · {text.checklistWarn} {warnCount} · {text.checklistFail} {failCount}
            </span>
          </div>
          <ul className="grid grid-cols-1 gap-1.5 md:grid-cols-2">
            {actionChecklist.map((item, idx) => (
              <li key={`${idx}-${item.text.slice(0, 20)}`} className="flex items-start gap-2 text-xs leading-5 text-foreground">
                {item.status === 'fail' ? (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden="true" />
                ) : item.status === 'warn' ? (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
                )}
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* 多策略综合共识与分歧（Refs #2071） */}
      {strategySynthesis ? (
        <div
          role="region"
          aria-label={text.strategySynthesisTitle}
          className="home-subpanel space-y-3 p-3.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-secondary-text">
              <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{text.strategySynthesisTitle}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={resolveSignalVariant(strategySynthesis.finalSignal)} className="shadow-none">
                {text.strategyFinalSignal}: {localizeStrategySignal(strategySynthesis.finalSignal, reportLanguage)}
              </Badge>
              <Badge variant={resolveConsensusVariant(strategySynthesis.consensusLevel)} className="shadow-none">
                {text.strategyConsensus}: {localizeConsensusLevel(strategySynthesis.consensusLevel, reportLanguage)}
              </Badge>
              <Badge
                variant={resolveConflictVariant(strategySynthesis.conflictSeverity, strategySynthesis.conflictCount)}
                className="shadow-none"
              >
                {text.strategyConflict}: {localizeConflictSeverity(strategySynthesis.conflictSeverity, reportLanguage)} ({strategySynthesis.conflictCount})
              </Badge>
              {strategySynthesis.confidence !== undefined ? (
                <Badge variant="default" className="shadow-none num font-mono">
                  {text.strategyConfidence}: {Math.round(strategySynthesis.confidence * 100)}%
                </Badge>
              ) : null}
            </div>
          </div>

          <p className="text-xs leading-5 text-secondary-text">
            {formatStrategySynthesisSummary(strategySynthesis, reportLanguage)}
          </p>

          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
            <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
              <div className="mb-1.5 text-xs font-semibold text-success">
                {text.strategySupporting} ({strategySynthesis.supportingSkills.length})
              </div>
              {strategySynthesis.supportingSkills.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {strategySynthesis.supportingSkills.map((item) => (
                    <span
                      key={`sup-${item.skillId}`}
                      className="inline-flex items-center gap-1 rounded-md border border-success/25 bg-success/10 px-2 py-0.5 text-xs text-foreground"
                    >
                      <span>{localizeStrategySkillName(item.skillId, reportLanguage)}</span>
                      <span className="text-muted-text">·</span>
                      <span className="text-success">{localizeStrategySignal(item.signal, reportLanguage)}</span>
                      {item.confidence !== undefined ? (
                        <span className="num font-mono text-muted-text">{Math.round(item.confidence * 100)}%</span>
                      ) : null}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-muted-text">{text.noValue}</span>
              )}
            </div>

            <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
              <div className="mb-1.5 text-xs font-semibold text-warning">
                {text.strategyOpposing} ({strategySynthesis.opposingSkills.length})
              </div>
              {strategySynthesis.opposingSkills.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {strategySynthesis.opposingSkills.map((item) => (
                    <span
                      key={`opp-${item.skillId}`}
                      className="inline-flex items-center gap-1 rounded-md border border-warning/25 bg-warning/10 px-2 py-0.5 text-xs text-foreground"
                    >
                      <span>{localizeStrategySkillName(item.skillId, reportLanguage)}</span>
                      <span className="text-muted-text">·</span>
                      <span className="text-warning">{localizeStrategySignal(item.signal, reportLanguage)}</span>
                      {item.confidence !== undefined ? (
                        <span className="num font-mono text-muted-text">{Math.round(item.confidence * 100)}%</span>
                      ) : null}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-muted-text">{text.noValue}</span>
              )}
            </div>
          </div>

          {(strategySynthesis.minorityViewPreserved || strategySynthesis.invalidOpinionCount > 0) ? (
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-text">
              {strategySynthesis.minorityViewPreserved ? (
                <span className="inline-flex items-center gap-1 text-warning">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span>{text.strategyMinorityPreserved}</span>
                </span>
              ) : null}
              {strategySynthesis.invalidOpinionCount > 0 ? (
                <span>
                  {text.strategyInvalidOpinions.replace('{count}', String(strategySynthesis.invalidOpinionCount))}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
};
