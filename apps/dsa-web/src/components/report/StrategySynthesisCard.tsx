import { useState } from 'react';
import type React from 'react';
import type {
  ReportLanguage,
  StrategySynthesis as StrategySynthesisType,
  StrategySynthesisSkillEntry,
} from '../../types/analysis';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

type ReportText = ReturnType<typeof getReportText>;

interface StrategySynthesisCardProps {
  synthesis?: StrategySynthesisType | null;
  language?: ReportLanguage;
}

const toNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const toTextList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const toRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

// Degraded display (issue #2071 review fix OR-COR-12e5b2ef): the backend keeps
// conflicts/revisionProjection as Dict[str, Any], so a legacy/malformed record
// can carry nested objects where these helpers promise strings/numbers. Every
// formatter therefore guards on typeof first and falls back to a placeholder —
// a malformed field degrades on its own instead of crashing the card.
const toText = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() !== '' ? value : null;

const formatPercent = (value: unknown): string => {
  const numeric = toNumber(value);
  return numeric == null ? '—' : `${(numeric * 100).toFixed(1)}%`;
};

const formatScore = (value: unknown): string => {
  const numeric = toNumber(value);
  return numeric == null ? '—' : numeric.toFixed(2);
};

const normalizeSignal = (signal: unknown): string =>
  typeof signal === 'string' ? signal.trim().toLowerCase() : '';

const getSignalLabel = (signal: unknown, text: ReportText): string => {
  switch (normalizeSignal(signal)) {
    case 'strong_buy':
      return text.signalStrongBuy;
    case 'buy':
      return text.signalBuy;
    case 'sell':
      return text.signalSell;
    case 'strong_sell':
      return text.signalStrongSell;
    case 'hold':
      return text.signalHold;
    default:
      return toText(signal) || '—';
  }
};

type SignalVariant = 'success' | 'danger' | 'default';

const getSignalVariant = (signal?: unknown): SignalVariant => {
  const normalized = normalizeSignal(signal);
  if (normalized === 'buy' || normalized === 'strong_buy') {
    return 'success';
  }
  if (normalized === 'sell' || normalized === 'strong_sell') {
    return 'danger';
  }
  return 'default';
};

const getConsensusLabel = (level: unknown, text: ReportText): string => {
  switch (level) {
    case 'high':
      return text.consensusHigh;
    case 'medium':
      return text.consensusMedium;
    case 'low':
      return text.consensusLow;
    case 'insufficient':
      return text.consensusInsufficient;
    default:
      return toText(level) || '—';
  }
};

type ConsensusVariant = 'success' | 'info' | 'warning' | 'default';

const getConsensusVariant = (level?: unknown): ConsensusVariant => {
  switch (level) {
    case 'high':
      return 'success';
    case 'medium':
      return 'info';
    case 'low':
      return 'warning';
    default:
      return 'default';
  }
};

const getSeverityLabel = (severity: unknown, text: ReportText): string => {
  switch (severity) {
    case 'none':
      return text.conflictSeverityNone;
    case 'low':
      return text.conflictSeverityLow;
    case 'medium':
      return text.conflictSeverityMedium;
    case 'high':
      return text.conflictSeverityHigh;
    default:
      return toText(severity) || '—';
  }
};

type SeverityVariant = 'default' | 'info' | 'warning' | 'danger';

const getSeverityVariant = (severity?: unknown): SeverityVariant => {
  switch (severity) {
    case 'low':
      return 'info';
    case 'medium':
      return 'warning';
    case 'high':
      return 'danger';
    default:
      return 'default';
  }
};

const MetricCell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="rounded-lg border border-border/40 bg-elevated/40 p-3">
    {children}
  </div>
);

const MetricLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="text-[11px] uppercase tracking-wide text-muted-text">{children}</div>
);

const SkillEntryRow: React.FC<{ entry: StrategySynthesisSkillEntry; text: ReportText }> = ({ entry, text }) => {
  const agentLabel = toText(entry.agentName) || toText(entry.skillId) || '—';
  const confidence = toNumber(entry.confidence);
  const reasoning = toText(entry.reasoning);
  return (
    <li className="rounded-lg border border-border/30 bg-elevated/30 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-secondary-text">{agentLabel}</span>
        <Badge variant={getSignalVariant(entry.signal)} className="shadow-none">
          {getSignalLabel(entry.signal, text)}
        </Badge>
        {confidence != null && (
          <span className="font-mono text-xs text-muted-text">{formatPercent(confidence)}</span>
        )}
      </div>
      {reasoning ? (
        <p className="mt-1 text-xs leading-5 text-secondary-text">
          <span className="text-muted-text">{text.strategySynthesisReasoning}: </span>
          {reasoning}
        </p>
      ) : null}
    </li>
  );
};

/**
 * 多策略综合卡片（issue #2071）。
 *
 * 只读投影后端 `details.strategy_synthesis`（camelCase），不重算阵营/权重/分歧；
 * revisionProjection 是协同推演的非权威预览，绝不覆盖 final_signal。
 */
export const StrategySynthesisCard: React.FC<StrategySynthesisCardProps> = ({
  synthesis,
  language = 'zh',
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [dissentExpanded, setDissentExpanded] = useState(false);

  if (!synthesis) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);

  const validCount = toNumber(synthesis.summaryParams?.opinionCount);
  const excludedCount = toNumber(synthesis.summaryParams?.invalidOpinionCount);
  const distribution = synthesis.signalDistribution;
  const buckets: Array<{
    key: 'bullish' | 'neutral' | 'bearish';
    label: string;
    count: number | null;
    share: number | null;
  }> = [
    {
      key: 'bullish',
      label: text.strategySynthesisBullish,
      count: toNumber(distribution?.bullish?.count),
      share: toNumber(distribution?.bullish?.weightShare),
    },
    {
      key: 'neutral',
      label: text.strategySynthesisNeutral,
      count: toNumber(distribution?.neutral?.count),
      share: toNumber(distribution?.neutral?.weightShare),
    },
    {
      key: 'bearish',
      label: text.strategySynthesisBearish,
      count: toNumber(distribution?.bearish?.count),
      share: toNumber(distribution?.bearish?.weightShare),
    },
  ];

  const supportingSkills = Array.isArray(synthesis.supportingSkills) ? synthesis.supportingSkills : [];
  const opposingSkills = Array.isArray(synthesis.opposingSkills) ? synthesis.opposingSkills : [];
  const conflicts = Array.isArray(synthesis.conflicts) ? synthesis.conflicts : [];
  const dissent = toRecord(synthesis.primaryDissent);
  const revision = toRecord(synthesis.revisionProjection);
  const deliberationRecord = toRecord(synthesis.deliberation);
  const deliberationSummary = toRecord(deliberationRecord?.summary);
  const originalConfidence = toNumber(synthesis.originalConfidence);
  const conflictCount = toNumber(synthesis.conflictCount);
  const conflictSeverity = toText(synthesis.conflictSeverity);

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <section data-testid="strategy-synthesis-card" aria-label={text.strategySynthesisTitle}>
        <DashboardPanelHeader
          eyebrow={text.strategySynthesisEyebrow}
          title={text.strategySynthesisTitle}
          className="mb-3"
        />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCell>
            <MetricLabel>{text.strategySynthesisFinalSignal}</MetricLabel>
            <div className="mt-1">
              <Badge variant={getSignalVariant(synthesis.finalSignal)}>
                {getSignalLabel(synthesis.finalSignal, text)}
              </Badge>
            </div>
          </MetricCell>
          <MetricCell>
            <MetricLabel>{text.strategySynthesisWeightedScore}</MetricLabel>
            <div className="mt-1 font-mono text-sm font-semibold text-foreground">
              {formatScore(synthesis.weightedScore)}
            </div>
          </MetricCell>
          <MetricCell>
            <MetricLabel>
              {text.strategySynthesisConfidence}: {formatPercent(synthesis.confidence)}
            </MetricLabel>
            {originalConfidence != null && (
              <div className="mt-1 font-mono text-xs text-muted-text">
                {text.strategySynthesisOriginalConfidence}: {formatPercent(originalConfidence)}
              </div>
            )}
          </MetricCell>
          <MetricCell>
            <MetricLabel>{text.strategySynthesisConsensus}</MetricLabel>
            <div className="mt-1">
              <Badge variant={getConsensusVariant(synthesis.consensusLevel)}>
                {getConsensusLabel(synthesis.consensusLevel, text)}
              </Badge>
            </div>
          </MetricCell>
        </div>

        {conflictCount != null && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-secondary-text">{text.strategySynthesisConflicts}: {conflictCount}</span>
            {conflictSeverity && (
              <Badge variant={getSeverityVariant(conflictSeverity)} className="shadow-none">
                {getSeverityLabel(conflictSeverity, text)}
              </Badge>
            )}
          </div>
        )}

        {distribution && (
          <div className="mt-4">
            <span className="label-uppercase">{text.strategySynthesisDistribution}</span>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {buckets.map((bucket) => (
                <div
                  key={bucket.key}
                  data-testid={`synthesis-dist-${bucket.key}`}
                  className="rounded-lg border border-border/30 bg-elevated/30 p-2 text-center"
                >
                  <div className="text-xs text-secondary-text">{bucket.label}</div>
                  <div className="font-mono text-base font-bold text-foreground">
                    {bucket.count ?? '—'}
                  </div>
                  <div className="font-mono text-xs text-muted-text">{formatPercent(bucket.share)}</div>
                </div>
              ))}
            </div>
            {(validCount != null || excludedCount != null) && (
              <div className="mt-2 flex flex-wrap gap-4 text-xs text-muted-text">
                {validCount != null && (
                  <span>{text.strategySynthesisValidOpinions}: {validCount}</span>
                )}
                {excludedCount != null && (
                  <span>{text.strategySynthesisExcludedOpinions}: {excludedCount}</span>
                )}
              </div>
            )}
          </div>
        )}

        <div className="mt-4">
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs font-medium text-cyan hover:underline"
            aria-expanded={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            {detailsOpen ? text.strategySynthesisHideDetails : text.strategySynthesisShowDetails}
            <svg
              className={`h-3 w-3 transition-transform ${detailsOpen ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {detailsOpen && (
            <div className="mt-3 space-y-4">
              {supportingSkills.length > 0 && (
                <div>
                  <span className="label-uppercase">{text.strategySynthesisSupporting}</span>
                  <ul className="mt-2 space-y-2">
                    {supportingSkills.map((entry, index) => (
                      <SkillEntryRow key={`${entry.skillId || index}-${index}`} entry={entry} text={text} />
                    ))}
                  </ul>
                </div>
              )}

              {opposingSkills.length > 0 && (
                <div>
                  <span className="label-uppercase">{text.strategySynthesisOpposing}</span>
                  <ul className="mt-2 space-y-2">
                    {opposingSkills.map((entry, index) => (
                      <SkillEntryRow key={`${entry.skillId || index}-${index}`} entry={entry} text={text} />
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <span className="label-uppercase">{text.strategySynthesisPrimaryDissent}</span>
                {dissent ? (
                  <div className="mt-2 rounded-lg border border-border/30 bg-elevated/30 p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-secondary-text">
                        {toText(dissent.agentName) || toText(dissent.skillId) || '—'}
                      </span>
                      <Badge variant={getSignalVariant(dissent.signal)} className="shadow-none">
                        {getSignalLabel(dissent.signal, text)}
                      </Badge>
                      {toNumber(dissent.confidence) != null && (
                        <span className="font-mono text-xs text-muted-text">
                          {formatPercent(dissent.confidence)}
                        </span>
                      )}
                    </div>
                    {toText(dissent.reasoning) ? (
                      <>
                        <p
                          className={`mt-1 text-xs leading-5 text-secondary-text ${
                            dissentExpanded ? '' : 'line-clamp-3'
                          }`}
                        >
                          <span className="text-muted-text">{text.strategySynthesisReasoning}: </span>
                          {toText(dissent.reasoning)}
                        </p>
                        <button
                          type="button"
                          className="mt-1 inline-flex items-center text-xs font-medium text-cyan hover:underline"
                          aria-expanded={dissentExpanded}
                          onClick={() => setDissentExpanded((expanded) => !expanded)}
                        >
                          {dissentExpanded
                            ? text.strategySynthesisCollapseReasoning
                            : text.strategySynthesisExpandReasoning}
                        </button>
                      </>
                    ) : null}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-muted-text">{text.strategySynthesisNoDissent}</p>
                )}
              </div>

              {conflicts.length > 0 && (
                <div>
                  <span className="label-uppercase">{text.strategySynthesisConflictDetails}</span>
                  <ul className="mt-2 space-y-2">
                    {conflicts.map((conflict, index) => {
                      const record = toRecord(conflict);
                      const conflictType = toText(record?.conflictType);
                      const severity = toText(record?.severity);
                      const descriptionKey = toText(record?.descriptionKey);
                      const participants = toTextList(record?.participants);
                      return (
                        <li
                          key={`${conflictType || 'conflict'}-${index}`}
                          className="rounded-lg border border-border/30 bg-elevated/30 p-3 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge
                              variant={getSeverityVariant(severity)}
                              className="shadow-none"
                            >
                              {getSeverityLabel(severity, text)}
                            </Badge>
                            {descriptionKey && (
                              <span className="font-mono text-xs text-secondary-text">
                                {descriptionKey}
                              </span>
                            )}
                          </div>
                          {participants.length > 0 && (
                            <div className="mt-1 text-xs text-muted-text">
                              {text.strategySynthesisParticipants}: {participants.join(', ')}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}

              {deliberationRecord && (
                <div>
                  <span className="label-uppercase">{text.strategySynthesisDeliberation}</span>
                  <div className="mt-2 space-y-1 font-mono text-xs text-secondary-text">
                    {Object.entries(deliberationSummary ?? deliberationRecord).map(([key, value]) => (
                      <div key={key}>{`${key}: ${String(value)}`}</div>
                    ))}
                  </div>
                </div>
              )}

              {revision && (
                <div
                  data-testid="synthesis-revision-preview"
                  className="rounded-lg border border-warning/30 bg-warning/10 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="warning" className="shadow-none">
                      {text.strategySynthesisPreviewBadge}
                    </Badge>
                    <span className="label-uppercase">{text.strategySynthesisRevisionPreview}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-4 text-sm">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="text-secondary-text">{text.strategySynthesisProjectedSignal}</span>
                      <Badge variant={getSignalVariant(revision.projectedSignal)} className="shadow-none">
                        {getSignalLabel(revision.projectedSignal, text)}
                      </Badge>
                    </span>
                    {toNumber(revision.projectedConfidence) != null && (
                      <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-text">
                        <span className="font-sans text-secondary-text">
                          {text.strategySynthesisProjectedConfidence}
                        </span>
                        {formatPercent(revision.projectedConfidence)}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-secondary-text">
                    {text.strategySynthesisPreviewNote}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </Card>
  );
};
