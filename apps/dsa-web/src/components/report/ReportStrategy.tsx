import type React from 'react';
import type { ReportLanguage, ReportStrategy as ReportStrategyType } from '../../types/analysis';
import type { ResearchArtifact } from '../../types/researchArtifact';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  language?: ReportLanguage;
  currentPrice?: number;
  artifact?: ResearchArtifact | null;
}

interface StrategyItemProps {
  label: string;
  value?: string;
  tone: string;
}

interface ParsedLevels {
  idealBuy?: number | null;
  secondaryBuy?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  referencePrice?: number | null;
  riskRewardRatio?: number | null;
  status?: string;
  validation?: string;
}

interface ParsedPosition {
  minPct?: number;
  maxPct?: number;
}

const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value;
  }
  return null;
};

const extractNumericLevels = (
  artifact: ResearchArtifact | null | undefined,
  currentPrice?: number,
): ParsedLevels => {
  const meta = (artifact?.metadata ?? {}) as Record<string, unknown>;
  const raw = (meta.levels ?? null) as Record<string, unknown> | null;
  if (!raw) {
    return {
      referencePrice: toFiniteNumber(currentPrice),
    };
  }
  return {
    idealBuy: toFiniteNumber(raw.idealBuy ?? raw.ideal_buy),
    secondaryBuy: toFiniteNumber(raw.secondaryBuy ?? raw.secondary_buy),
    stopLoss: toFiniteNumber(raw.stopLoss ?? raw.stop_loss),
    takeProfit: toFiniteNumber(raw.takeProfit ?? raw.take_profit),
    referencePrice: toFiniteNumber(raw.referencePrice ?? raw.reference_price ?? currentPrice),
    riskRewardRatio: toFiniteNumber(raw.riskRewardRatio ?? raw.risk_reward_ratio),
    status: typeof raw.status === 'string' ? raw.status : undefined,
    validation: typeof raw.validation === 'string' ? raw.validation : undefined,
  };
};

const extractPosition = (
  artifact: ResearchArtifact | null | undefined,
  levels: ParsedLevels,
): ParsedPosition | null => {
  const meta = (artifact?.metadata ?? {}) as Record<string, unknown>;
  const raw = (meta.position ?? null) as Record<string, unknown> | null;
  if (!raw) return null;
  const minPct = raw.minPct ?? raw.min_pct;
  const maxPct = raw.maxPct ?? raw.max_pct;
  const riskBudgetPct = toFiniteNumber(raw.riskBudgetPct ?? raw.risk_budget_pct);
  const { idealBuy, referencePrice, stopLoss, status, validation } = levels;
  const entryPrice = idealBuy ?? referencePrice;
  if (
    typeof minPct !== 'number' || typeof maxPct !== 'number'
    || !Number.isFinite(minPct) || !Number.isFinite(maxPct)
    || minPct < 0 || minPct > maxPct || maxPct <= 0 || maxPct > 100
    || !entryPrice || !stopLoss || stopLoss >= entryPrice
    || status === 'invalid' || validation !== 'ok' || riskBudgetPct === null
  ) {
    return null;
  }
  // Recheck actual stop risk so unsafe metadata in older reports is not displayed.
  const stopDistancePct = (entryPrice - stopLoss) / entryPrice * 100;
  if (maxPct * stopDistancePct / 100 > riskBudgetPct + 1e-10) {
    return null;
  }
  return { minPct, maxPct };
};

const StrategyItem: React.FC<StrategyItemProps> = ({
  label,
  value,
  tone,
}) => (
  <div className="home-subpanel home-strategy-card p-3" style={{ ['--home-strategy-tone' as string]: `var(${tone})` }}>
    <div className="flex flex-col">
      <span className="home-strategy-label mb-0.5 text-xs">{label}</span>
      <span className="home-strategy-value text-lg font-bold font-mono" style={!value ? { color: 'var(--text-muted-text)' } : undefined}>
        {value || '—'}
      </span>
    </div>
    <div
      className="absolute bottom-0 left-0 right-0 h-0.5"
      style={{ background: `linear-gradient(90deg, transparent, var(${tone}), transparent)` }}
    />
  </div>
);

/**
 * 策略点位区组件 - 终端风格 + 量化校验/点位刻度条
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({
  strategy,
  language = 'zh',
  currentPrice,
  artifact,
}) => {
  if (!strategy) {
    return null;
  }

  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const levels = extractNumericLevels(artifact, currentPrice);
  const position = extractPosition(artifact, levels);

  const strategyItems = [
    {
      label: text.idealBuy,
      value: strategy.idealBuy,
      tone: '--home-strategy-buy',
    },
    {
      label: text.secondaryBuy,
      value: strategy.secondaryBuy,
      tone: '--home-strategy-secondary',
    },
    {
      label: text.stopLoss,
      value: strategy.stopLoss,
      tone: '--home-strategy-stop',
    },
    {
      label: text.takeProfit,
      value: strategy.takeProfit,
      tone: '--home-strategy-take',
    },
  ];

  const markers = [
    levels.stopLoss ? { key: 'stop', label: text.stopLoss, price: levels.stopLoss, toneClass: 'bg-danger' } : null,
    levels.secondaryBuy ? { key: 'secondary', label: text.secondaryBuy, price: levels.secondaryBuy, toneClass: 'bg-info' } : null,
    levels.idealBuy ? { key: 'ideal', label: text.idealBuy, price: levels.idealBuy, toneClass: 'bg-success' } : null,
    levels.referencePrice ? { key: 'ref', label: 'Ref', price: levels.referencePrice, toneClass: 'bg-foreground' } : null,
    levels.takeProfit ? { key: 'take', label: text.takeProfit, price: levels.takeProfit, toneClass: 'bg-warning' } : null,
  ]
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort((a, b) => a.price - b.price);

  const minMarker = markers.length >= 2 ? markers[0].price : null;
  const maxMarker = markers.length >= 2 ? markers[markers.length - 1].price : null;
  const span = minMarker !== null && maxMarker !== null && maxMarker > minMarker ? maxMarker - minMarker : 0;

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        eyebrow={text.strategyPoints}
        title={text.sniperLevels}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {levels.status && (
              <Badge variant={levels.status === 'active' ? 'success' : levels.status === 'invalid' ? 'danger' : 'warning'}>
                {levels.status === 'active'
                  ? text.activeLevelBadge
                  : levels.status === 'invalid'
                    ? text.invalidLevelBadge
                    : text.conditionalWatchBadge}
              </Badge>
            )}
            {levels.riskRewardRatio != null && (
              <Badge variant={levels.riskRewardRatio >= 1.5 ? 'info' : 'warning'}>
                {text.riskRewardLabel} 1:{levels.riskRewardRatio.toFixed(2)}
              </Badge>
            )}
            {position && (
              <Badge variant="default">
                {text.suggestedPositionLabel} {position.minPct}%–{position.maxPct}%
              </Badge>
            )}
          </div>
        }
        className="mb-3"
      />

      {levels.validation === 'direction_conflict' && (
        <div role="note" className="mb-3 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-foreground">
          {text.levelValidationConflict}
        </div>
      )}
      {levels.validation === 'out_of_range' && (
        <div role="note" className="mb-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-foreground">
          {text.levelValidationOutOfRange}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>

      {span > 0 && (
        <div className="mt-4 pt-3 border-t border-border/50">
          <div className="relative h-2.5 w-full rounded-full bg-elevated">
            {markers.map((m) => {
              const pct = Math.max(2, Math.min(98, ((m.price - (minMarker as number)) / span) * 100));
              return (
                <span
                  key={m.key}
                  title={`${m.label}: ${m.price.toFixed(2)}`}
                  className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-3.5 w-3.5 rounded-full border-2 border-card ${m.toneClass}`}
                  style={{ left: `${pct}%` }}
                />
              );
            })}
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-text font-mono">
            {markers.map((m) => (
              <span key={`${m.key}-label`} className="inline-flex items-center gap-1.5">
                <span className={`inline-block h-2 w-2 rounded-full ${m.toneClass}`} />
                <span>{m.label}</span>
                <span className="text-foreground">{m.price.toFixed(2)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
};
