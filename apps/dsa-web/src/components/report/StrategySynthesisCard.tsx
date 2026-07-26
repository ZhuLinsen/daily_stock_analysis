import { useId, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronDown, CircleMinus, GitCompareArrows, ShieldCheck } from 'lucide-react';
import type {
  ReportLanguage,
  StrategyConflictSeverity,
  StrategyOpinionItem,
  StrategySignal,
  StrategySynthesis,
} from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface StrategySynthesisCardProps {
  synthesis?: StrategySynthesis | null;
  language?: ReportLanguage;
}

type Text = ReturnType<typeof getReportText>;

const percent = (value?: number | null) => (
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—'
);

const signedPercent = (value?: number | null) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const percentage = Math.round(value * 100);
  return `${percentage > 0 ? '+' : ''}${percentage}%`;
};

const severityVariant = (severity: StrategyConflictSeverity) => {
  if (severity === 'high') return 'danger' as const;
  if (severity === 'medium') return 'warning' as const;
  if (severity === 'low') return 'info' as const;
  return 'default' as const;
};

const signalVariant = (signal: StrategySignal) => {
  if (signal === 'strong_buy' || signal === 'buy') return 'success' as const;
  if (signal === 'strong_sell' || signal === 'sell') return 'danger' as const;
  return 'default' as const;
};

const SignalIcon = ({ signal }: { signal: StrategySignal }) => {
  if (signal === 'strong_buy' || signal === 'buy') return <ArrowUp aria-hidden="true" size={14} />;
  if (signal === 'strong_sell' || signal === 'sell') return <ArrowDown aria-hidden="true" size={14} />;
  return <CircleMinus aria-hidden="true" size={14} />;
};

const OpinionRow = ({ opinion, text }: { opinion: StrategyOpinionItem; text: Text }) => {
  const [expanded, setExpanded] = useState(false);
  const reasoningId = useId();
  const reasoning = (opinion.reasoning || '').trim();

  return (
    <li className="rounded-xl border border-border/55 bg-elevated/45 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 break-all font-mono text-sm font-semibold text-foreground">
          {opinion.skillId}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={signalVariant(opinion.signal)}>
            <SignalIcon signal={opinion.signal} />
            {text.signalLabels[opinion.signal]}
          </Badge>
          <span className="text-xs text-muted-text">{text.confidence} {percent(opinion.confidence)}</span>
          {typeof opinion.appliedWeight === 'number' ? (
            <span className="text-xs text-muted-text">{text.appliedWeight} {opinion.appliedWeight.toFixed(4)}</span>
          ) : null}
        </div>
      </div>
      {reasoning ? (
        <div className="mt-2">
          <p id={reasoningId} className={expanded ? 'whitespace-pre-wrap break-words text-sm text-secondary-text' : 'line-clamp-2 break-words text-sm text-secondary-text'}>
            {reasoning}
          </p>
          <button
            type="button"
            aria-controls={reasoningId}
            aria-expanded={expanded}
            className="mt-1 text-xs font-medium text-cyan hover:underline"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? text.showLess : text.showMore}
          </button>
        </div>
      ) : null}
    </li>
  );
};

const OpinionGroup = ({
  title,
  opinions,
  text,
}: {
  title: string;
  opinions: StrategyOpinionItem[];
  text: Text;
}) => (
  <section aria-label={title} className="min-w-0">
    <h4 className="mb-2 text-sm font-semibold text-foreground">{title} ({opinions.length})</h4>
    {opinions.length ? (
      <ul className="space-y-2">
        {opinions.map((opinion, index) => (
          <OpinionRow key={`${opinion.skillId}-${opinion.signal}-${index}`} opinion={opinion} text={text} />
        ))}
      </ul>
    ) : (
      <p className="rounded-xl border border-dashed border-border/55 p-3 text-sm text-muted-text">{text.noOpinions}</p>
    )}
  </section>
);

export const StrategySynthesisCard = ({
  synthesis,
  language = 'zh',
}: StrategySynthesisCardProps) => {
  if (!synthesis || synthesis.schemaVersion !== 'strategy-synthesis-v1') return null;

  const text = getReportText(normalizeReportLanguage(language));
  const conflictDescriptions = text.conflictDescriptions as Record<string, string>;
  const distribution = [
    { key: 'bullish', label: text.bullish, icon: ArrowUp, value: synthesis.signalDistribution.bullish, tone: 'bg-success' },
    { key: 'neutral', label: text.neutral, icon: CircleMinus, value: synthesis.signalDistribution.neutral, tone: 'bg-cyan' },
    { key: 'bearish', label: text.bearish, icon: ArrowDown, value: synthesis.signalDistribution.bearish, tone: 'bg-danger' },
  ] as const;

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <section aria-label={text.strategySynthesisTitle}>
        <DashboardPanelHeader
          eyebrow={text.strategySynthesisEyebrow}
          title={text.strategySynthesisTitle}
          leading={<GitCompareArrows aria-hidden="true" size={18} className="text-cyan" />}
          actions={<Badge variant="info"><ShieldCheck aria-hidden="true" size={13} />{text.authoritativeResult}</Badge>}
        />

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <div className="home-subpanel col-span-2 p-3 lg:col-span-1">
            <span className="text-xs text-muted-text">{text.finalSignal}</span>
            <div className="mt-1">
              <Badge variant={signalVariant(synthesis.finalSignal)} size="md">
                <SignalIcon signal={synthesis.finalSignal} />
                {text.signalLabels[synthesis.finalSignal]}
              </Badge>
            </div>
          </div>
          {[
            [text.weightedScore, synthesis.weightedScore.toFixed(2)],
            [text.confidence, percent(synthesis.confidence)],
            [text.consensusLevel, text.consensusLabels[synthesis.consensusLevel]],
            [text.conflicts, `${text.severityLabels[synthesis.conflictSeverity]} · ${synthesis.conflictCount}`],
            [text.validOpinions, String(synthesis.summaryParams.opinionCount)],
          ].map(([label, value]) => (
            <div key={label} className="home-subpanel p-3">
              <span className="text-xs text-muted-text">{label}</span>
              <p className="mt-1 font-mono text-base font-semibold text-foreground">{value}</p>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-text">
          {text.invalidOpinions}: {synthesis.summaryParams.invalidOpinionCount}
        </p>

        <section aria-label={text.signalDistribution} className="mt-5">
          <h4 className="mb-2 text-sm font-semibold text-foreground">{text.signalDistribution}</h4>
          <div className="grid gap-3 sm:grid-cols-3">
            {distribution.map(({ key, label, icon: Icon, value, tone }) => {
              const width = typeof value.weightShare === 'number'
                ? Math.max(0, Math.min(100, value.weightShare * 100))
                : 0;
              return (
                <div key={key} className="rounded-xl border border-border/55 bg-elevated/45 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                      <Icon aria-hidden="true" size={15} />{label}
                    </span>
                    <span className="font-mono text-sm text-secondary-text">{value.count}</span>
                  </div>
                  <div
                    role="img"
                    aria-label={`${label}: ${text.weightShare} ${percent(value.weightShare)}`}
                    className="mt-2 h-1.5 overflow-hidden rounded-full bg-border/50"
                  >
                    <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-muted-text">{text.weightShare}: {percent(value.weightShare)}</p>
                </div>
              );
            })}
          </div>
        </section>

        {synthesis.primaryDissent ? (
          <section aria-label={text.primaryDissent} className="mt-5 rounded-xl border border-warning/30 bg-warning/5 p-3">
            <h4 className="mb-2 text-sm font-semibold text-foreground">{text.primaryDissent}</h4>
            <ul><OpinionRow opinion={synthesis.primaryDissent} text={text} /></ul>
          </section>
        ) : null}

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <OpinionGroup title={text.supportingOpinions} opinions={synthesis.supportingSkills} text={text} />
          <OpinionGroup title={text.opposingOpinions} opinions={synthesis.opposingSkills} text={text} />
        </div>

        {synthesis.conflicts.length ? (
          <details className="mt-5 rounded-xl border border-border/55 bg-elevated/35 p-3">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold text-foreground">
              {text.conflictDetails} ({synthesis.conflicts.length})
              <ChevronDown aria-hidden="true" size={16} />
            </summary>
            <ul className="mt-3 space-y-2">
              {synthesis.conflicts.map((conflict, index) => (
                <li key={`${conflict.conflictType}-${index}`} className="flex flex-wrap items-center gap-2 text-sm text-secondary-text">
                  <Badge variant={severityVariant(conflict.severity)}>{text.severityLabels[conflict.severity]}</Badge>
                  <span>
                    {conflictDescriptions[conflict.descriptionKey?.replace('strategy_conflict.', '') || conflict.conflictType]
                      || text.unknownConflict}
                  </span>
                  <span className="text-muted-text">{conflict.participants.join(', ')}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {synthesis.deliberation ? (
          <section aria-label={text.deliberation} className="mt-5 rounded-xl border border-cyan/25 bg-cyan/5 p-3">
            <h4 className="text-sm font-semibold text-foreground">{text.deliberation}</h4>
            <p className="mt-1 text-xs text-muted-text">
              {text.deliberationMode}: {synthesis.deliberation.mode} · {text.rounds} {synthesis.deliberation.rounds} · {text.responses} {synthesis.deliberation.responses.length}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-cyan/20 bg-background/35 p-2.5">
                <span className="text-xs text-muted-text">{text.resolutionStatus}</span>
                <p className="mt-1 text-sm font-semibold text-foreground">
                  {text.resolutionStatusLabels[synthesis.deliberation.summary.resolutionStatus]}
                </p>
              </div>
              <div className="rounded-lg border border-cyan/20 bg-background/35 p-2.5">
                <span className="text-xs text-muted-text">{text.resolvedConflicts} / {text.unresolvedConflicts}</span>
                <p className="mt-1 font-mono text-sm font-semibold text-foreground">
                  {synthesis.deliberation.summary.resolvedConflictCount} / {synthesis.deliberation.summary.unresolvedConflictCount}
                </p>
              </div>
              <div className="rounded-lg border border-cyan/20 bg-background/35 p-2.5">
                <span className="text-xs text-muted-text">{text.minorityView}</span>
                <p className="mt-1 text-sm font-semibold text-foreground">
                  {synthesis.deliberation.summary.minorityViewPreserved
                    ? text.minorityPreserved
                    : text.minorityNotPreserved}
                </p>
              </div>
              <div className="rounded-lg border border-cyan/20 bg-background/35 p-2.5">
                <span className="text-xs text-muted-text">{text.confidenceAdjustment}</span>
                <p className="mt-1 font-mono text-sm font-semibold text-foreground">
                  {signedPercent(synthesis.deliberation.summary.confidenceAdjustment)}
                </p>
              </div>
            </div>
          </section>
        ) : null}

        {synthesis.revisionProjection ? (
          <section aria-label={text.revisionPreview} className="mt-5 rounded-xl border border-purple/30 bg-purple/5 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-foreground">{text.revisionPreview}</h4>
              <Badge variant="history">{text.previewNonAuthoritative}</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <span className="text-sm text-secondary-text">{text.finalSignal}: {text.signalLabels[synthesis.revisionProjection.projectedSignal]}</span>
              <span className="text-sm text-secondary-text">{text.weightedScore}: {synthesis.revisionProjection.projectedWeightedScore.toFixed(2)}</span>
              <span className="text-sm text-secondary-text">{text.confidence}: {percent(synthesis.revisionProjection.projectedConfidence)}</span>
              <span className="text-sm text-secondary-text">{text.conflicts}: {synthesis.revisionProjection.projectedConflictCount}</span>
            </div>
          </section>
        ) : null}
      </section>
    </Card>
  );
};
