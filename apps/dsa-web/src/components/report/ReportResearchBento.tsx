import type React from 'react';
import type { ReportLanguage } from '../../types/analysis';
import type {
  ResearchArtifact,
  ResearchInvalidationSeverity,
  ResearchQualityLevel,
} from '../../types/researchArtifact';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportResearchBentoProps {
  artifact?: ResearchArtifact | null;
  language?: ReportLanguage;
}

interface RiskFlagItem {
  code?: string;
  severity?: 'info' | 'warning' | 'critical';
  message?: string;
}

interface CommitteeAgentItem {
  agent?: string;
  signal?: string;
  confidence?: number;
}

interface CommitteeData {
  baseDisagreement?: {
    type?: string;
    agents?: CommitteeAgentItem[];
  };
  base_disagreement?: {
    type?: string;
    agents?: CommitteeAgentItem[];
  };
  riskControl?: {
    applied?: boolean;
    fromSignal?: string;
    toSignal?: string;
    reason?: string;
  };
  risk_control?: {
    applied?: boolean;
    from_signal?: string;
    to_signal?: string;
    reason?: string;
  };
  decisionPath?: string;
  decision_path?: string;
}

const getQualityVariant = (level: ResearchQualityLevel): 'success' | 'info' | 'warning' | 'danger' | 'default' => {
  switch (level) {
    case 'good':
      return 'success';
    case 'usable':
      return 'info';
    case 'limited':
      return 'warning';
    case 'poor':
      return 'danger';
    default:
      return 'default';
  }
};

const getSeverityVariant = (
  severity?: ResearchInvalidationSeverity | 'info',
): 'danger' | 'warning' | 'info' | 'default' => {
  switch (severity) {
    case 'critical':
      return 'danger';
    case 'warning':
      return 'warning';
    case 'watch':
    case 'info':
      return 'info';
    default:
      return 'default';
  }
};

/**
 * Structured Research Bento Card: surfaces thesis direction, data quality gate,
 * invalidation triggers, risk flags, and multi-agent committee consensus.
 */
export const ReportResearchBento: React.FC<ReportResearchBentoProps> = ({
  artifact,
  language = 'zh',
}) => {
  if (!artifact) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const meta = (artifact.metadata ?? {}) as Record<string, unknown>;

  const rawRiskFlags = (meta.riskFlags ?? meta.risk_flags) as RiskFlagItem[] | undefined;
  const riskFlags = Array.isArray(rawRiskFlags) ? rawRiskFlags : [];

  const committee = (meta.committee ?? null) as CommitteeData | null;
  const baseDisagreement = committee?.baseDisagreement ?? committee?.base_disagreement;
  const committeeAgents = Array.isArray(baseDisagreement?.agents) ? baseDisagreement.agents : [];
  const riskControl = committee?.riskControl ?? committee?.risk_control;
  const riskOverrideApplied = Boolean(riskControl?.applied);

  let bullishCount = 0;
  let neutralCount = 0;
  let bearishCount = 0;
  committeeAgents.forEach((member) => {
    const sig = String(member.signal || '').toLowerCase();
    if (sig === 'buy' || sig === 'strong_buy' || sig === 'add') {
      bullishCount += 1;
    } else if (sig === 'sell' || sig === 'strong_sell' || sig === 'reduce' || sig === 'avoid') {
      bearishCount += 1;
    } else if (sig) {
      neutralCount += 1;
    }
  });
  const totalAgents = bullishCount + neutralCount + bearishCount;

  const isLowQuality = artifact.dataQuality.level === 'limited' || artifact.dataQuality.level === 'poor';

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <DashboardPanelHeader
        eyebrow={text.researchBentoEyebrow}
        title={text.researchBentoTitle}
        actions={
          <Badge variant={getQualityVariant(artifact.dataQuality.level)}>
            {artifact.dataQuality.level.toUpperCase()} · {artifact.dataQuality.sourceCount} src / {artifact.dataQuality.staleCount} stale
          </Badge>
        }
        className="mb-4"
      />

      {isLowQuality && (
        <div
          role="note"
          className="mb-4 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-5 text-foreground"
        >
          {text.dataQualityCaution}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Card A: Thesis & Next Actions */}
        <div className="home-subpanel rounded-xl p-3.5 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">{text.nextActionsTitle}</span>
            <Badge variant={artifact.thesis.direction === 'bullish' ? 'success' : artifact.thesis.direction === 'bearish' ? 'danger' : 'default'}>
              {artifact.thesis.direction}
            </Badge>
          </div>
          {artifact.nextActions.length > 0 ? (
            <ul className="space-y-2">
              {artifact.nextActions.slice(0, 3).map((item, idx) => (
                <li key={`${item.action}-${idx}`} className="text-xs leading-5 text-secondary-text">
                  <span className="font-medium text-foreground">{item.label}</span>
                  {item.reason ? <span className="block text-muted-text">{item.reason}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-text">{text.noValue}</p>
          )}
        </div>

        {/* Card B: Invalidation Triggers */}
        <div className="home-subpanel rounded-xl p-3.5 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">{text.invalidationConditionsTitle}</span>
            <span className="text-xs font-mono text-muted-text">{artifact.invalidationConditions.length}</span>
          </div>
          <ul className="space-y-2">
            {artifact.invalidationConditions.slice(0, 4).map((cond) => (
              <li key={cond.id} className="flex items-start justify-between gap-2 text-xs leading-5">
                <span className="text-secondary-text">{cond.description}</span>
                <Badge variant={getSeverityVariant(cond.severity)} className="shrink-0">
                  {cond.severity}
                </Badge>
              </li>
            ))}
          </ul>
        </div>

        {/* Card C: Risk Flags & Committee */}
        <div className="home-subpanel rounded-xl p-3.5 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">
              {committee ? text.committeeTitle : text.riskFlagsTitle}
            </span>
            {riskOverrideApplied && (
              <Badge variant="warning">{text.riskOverrideTriggered}</Badge>
            )}
          </div>

          {committee && totalAgents > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-text">
                <span>{text.committeeConsensus}</span>
                <span className="font-mono text-foreground">
                  {bullishCount} / {neutralCount} / {bearishCount}
                </span>
              </div>
              <div className="flex h-2 w-full overflow-hidden rounded-full bg-elevated">
                {bullishCount > 0 && (
                  <div
                    className="bg-success"
                    style={{ width: `${(bullishCount / totalAgents) * 100}%` }}
                  />
                )}
                {neutralCount > 0 && (
                  <div
                    className="bg-warning"
                    style={{ width: `${(neutralCount / totalAgents) * 100}%` }}
                  />
                )}
                {bearishCount > 0 && (
                  <div
                    className="bg-danger"
                    style={{ width: `${(bearishCount / totalAgents) * 100}%` }}
                  />
                )}
              </div>
            </div>
          )}

          {riskFlags.length > 0 ? (
            <ul className="space-y-1.5">
              {riskFlags.slice(0, 4).map((flag, idx) => (
                <li key={`${flag.code || 'flag'}-${idx}`} className="flex items-start justify-between gap-2 text-xs leading-5">
                  <span className="text-secondary-text">{flag.message || flag.code}</span>
                  <Badge variant={getSeverityVariant(flag.severity)} className="shrink-0">
                    {flag.severity || 'info'}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            !committee && <p className="text-xs text-muted-text">{text.noValue}</p>
          )}
        </div>
      </div>
    </Card>
  );
};
