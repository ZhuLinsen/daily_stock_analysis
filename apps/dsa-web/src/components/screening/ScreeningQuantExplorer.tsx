import type React from 'react';
import { BarChart3, Download, Layers, RotateCcw, Search, X } from 'lucide-react';
import type { ScreeningCandidate, ScreeningStrategy } from '../../api/screening';
import { formatUiText, type UiLanguage } from '../../i18n/uiText';
import { SCREENING_TEXT } from '../../locales/screening';
import { SCREENING_QUANT_TEXT } from '../../locales/screeningQuantText';
import {
  factorBarColorClass,
  getCandidateExplicitFactorScore,
  getCandidateFactorValue,
  getFactorLabel,
  lookupOwnString,
  normalizeFactorKey,
  type CandidateRiskFilter,
  type CandidateSortKey,
} from '../../utils/screeningQuant';

export const StrategyFactorBlueprint: React.FC<{
  strategy: ScreeningStrategy;
  language: UiLanguage;
}> = ({ strategy, language }) => {
  const qcopy = SCREENING_QUANT_TEXT[language];
  const weightEntries = Object.entries(strategy.factorWeights || {})
    .filter(([, weight]) => typeof weight === 'number' && Number.isFinite(weight) && weight > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]));

  const rawStyle = (strategy.style || {}) as Record<string, unknown>;
  const riskProfile =
    typeof rawStyle.riskProfile === 'string'
      ? rawStyle.riskProfile
      : typeof rawStyle.risk_profile === 'string'
        ? rawStyle.risk_profile
        : undefined;
  const holdingPeriod =
    typeof rawStyle.holdingPeriod === 'string'
      ? rawStyle.holdingPeriod
      : typeof rawStyle.holding_period === 'string'
        ? rawStyle.holding_period
        : undefined;
  const rawRegimes = Array.isArray(rawStyle.marketRegime)
    ? rawStyle.marketRegime
    : Array.isArray(rawStyle.market_regime)
      ? rawStyle.market_regime
      : [];
  const marketRegimes = rawRegimes
    .map((item) => String(item || '').trim())
    .filter(Boolean);
  const filterCount = strategy.activeFilters?.length ?? 0;

  const totalWeight = weightEntries.reduce((acc, [, w]) => acc + w, 0) || 1;
  const riskLabel = riskProfile
    ? (lookupOwnString(qcopy.riskProfiles, riskProfile) ?? riskProfile)
    : null;
  const periodLabel = holdingPeriod
    ? (lookupOwnString(qcopy.holdingPeriods, holdingPeriod) ?? holdingPeriod)
    : null;
  const hasStyle = Boolean(riskLabel || periodLabel || marketRegimes.length > 0);

  if (
    weightEntries.length === 0 &&
    !hasStyle &&
    filterCount === 0 &&
    !strategy.requiresDailyFeatures
  ) {
    return null;
  }

  return (
    <div className="mt-3 rounded-xl border border-cyan/20 bg-surface/65 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <Layers className="h-3.5 w-3.5 text-cyan" />
          <span>{qcopy.blueprintTitle}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          {strategy.requiresDailyFeatures ? (
            <span className="rounded-md border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-medium text-cyan">
              {qcopy.dailyFeaturesRequired}
            </span>
          ) : null}
          {riskLabel ? (
            <span className="rounded-md border border-border bg-card px-2 py-0.5 text-secondary-text">
              {qcopy.riskStyleLabel}: <strong className="text-foreground">{riskLabel}</strong>
            </span>
          ) : null}
          {periodLabel ? (
            <span className="rounded-md border border-border bg-card px-2 py-0.5 text-secondary-text">
              {qcopy.holdingPeriodLabel}: <strong className="text-foreground">{periodLabel}</strong>
            </span>
          ) : null}
          {marketRegimes.length > 0 ? (
            <span className="rounded-md border border-border bg-card px-2 py-0.5 text-secondary-text">
              {qcopy.regimeLabel}:{' '}
              <strong className="text-foreground">
                {marketRegimes.map((r) => lookupOwnString(qcopy.marketRegimes, r) ?? r).join(' / ')}
              </strong>
            </span>
          ) : null}
          {filterCount > 0 ? (
            <span className="rounded-md border border-border bg-card px-2 py-0.5 text-secondary-text">
              {qcopy.hardFiltersLabel}:{' '}
              <strong className="text-foreground">
                {formatUiText(qcopy.filtersCount, { count: filterCount })}
              </strong>
            </span>
          ) : null}
        </div>
      </div>

      {weightEntries.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          {weightEntries.map(([key, weight]) => {
            const rawPct = (weight / totalWeight) * 100;
            const pctText = rawPct > 0 && rawPct < 1 ? '<1%' : `${Math.round(rawPct)}%`;
            return (
              <div
                key={key}
                className="flex min-w-[110px] flex-1 basis-[120px] flex-col gap-1 rounded-lg border border-border/70 bg-card/85 px-2.5 py-1.5"
              >
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-secondary-text">{getFactorLabel(language, key)}</span>
                  <span className="font-mono font-semibold text-cyan">{pctText}</span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-surface">
                  <div
                    className="h-full rounded-full bg-cyan"
                    style={{ width: `${Math.min(100, Math.max(4, rawPct))}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};

export const ScreeningResultsToolbar: React.FC<{
  language: UiLanguage;
  query: string;
  onQueryChange: (val: string) => void;
  riskFilter: CandidateRiskFilter;
  onRiskFilterChange: (val: CandidateRiskFilter) => void;
  sortKey: CandidateSortKey;
  onSortKeyChange: (val: CandidateSortKey) => void;
  onExportCsv: () => void;
  canExport: boolean;
}> = ({
  language,
  query,
  onQueryChange,
  riskFilter,
  onRiskFilterChange,
  sortKey,
  onSortKeyChange,
  onExportCsv,
  canExport,
}) => {
  const qcopy = SCREENING_QUANT_TEXT[language];
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/80 bg-surface/65 p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-text" />
          <input
            type="text"
            aria-label={qcopy.filterInputAria}
            placeholder={qcopy.filterInputPlaceholder}
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            className="h-8 w-48 rounded-lg border border-border bg-card pl-8 pr-2.5 text-xs text-foreground outline-none transition-colors focus:border-cyan"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1">
          {(
            [
              ['all', qcopy.riskAll],
              ['low', qcopy.riskLow],
              ['medium', qcopy.riskMedium],
              ['high', qcopy.riskHigh],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={riskFilter === key}
              onClick={() => onRiskFilterChange(key)}
              className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                riskFilter === key
                  ? 'border-cyan/60 bg-cyan/15 font-semibold text-cyan'
                  : 'border-border bg-card text-secondary-text hover:text-foreground'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <select
          aria-label={qcopy.sortLabel}
          value={sortKey}
          onChange={(e) => onSortKeyChange(e.target.value as CandidateSortKey)}
          className="h-8 rounded-lg border border-border bg-card px-2.5 text-xs text-foreground outline-none transition-colors focus:border-cyan"
        >
          <option value="default">{qcopy.sortDefault}</option>
          <option value="score_desc">{qcopy.sortScoreDesc}</option>
          <option value="llm_desc">{qcopy.sortLlmDesc}</option>
          <option value="change_desc">{qcopy.sortChangeDesc}</option>
          <option value="momentum_desc">{qcopy.sortMomentumDesc}</option>
          <option value="value_desc">{qcopy.sortValueDesc}</option>
          <option value="stability_desc">{qcopy.sortStabilityDesc}</option>
          <option value="liquidity_desc">{qcopy.sortLiquidityDesc}</option>
        </select>

        <button
          type="button"
          disabled={!canExport}
          onClick={onExportCsv}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 text-xs font-medium text-foreground transition-colors hover:border-cyan/60 hover:text-cyan disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-3.5 w-3.5" />
          {qcopy.exportCsv}
        </button>
      </div>
    </div>
  );
};

export const CandidateComparisonMatrix: React.FC<{
  candidates: ScreeningCandidate[];
  language: UiLanguage;
  onRemove: (code: string) => void;
  onClear: () => void;
}> = ({ candidates, language, onRemove, onClear }) => {
  const qcopy = SCREENING_QUANT_TEXT[language];
  const copy = SCREENING_TEXT[language];

  if (candidates.length === 0) return null;

  if (candidates.length === 1) {
    const pinned = candidates[0];
    return (
      <div
        role="status"
        className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-cyan/30 bg-cyan/5 px-3.5 py-2.5 text-xs"
      >
        <div className="flex flex-wrap items-center gap-2">
          <BarChart3 className="h-4 w-4 text-cyan" />
          <span className="font-medium text-foreground">
            {formatUiText(qcopy.compareSelectedProgress, { count: candidates.length })}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-cyan/30 bg-card px-2 py-1 font-medium text-foreground">
            <span>
              {pinned.name || pinned.code}{' '}
              <span className="font-mono text-[11px] font-normal text-secondary-text">
                ({pinned.code})
              </span>
            </span>
            <button
              type="button"
              aria-label={`${qcopy.compareRemove} ${pinned.code}`}
              onClick={() => onRemove(pinned.code)}
              className="rounded p-0.5 text-muted-text hover:bg-surface hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-xs text-secondary-text hover:text-foreground"
        >
          <RotateCcw className="h-3 w-3" />
          {qcopy.compareClear}
        </button>
      </div>
    );
  }

  const finiteFactorScores = candidates
    .map(getCandidateExplicitFactorScore)
    .filter((v): v is number => v != null);
  const hasFactorScoreRow = finiteFactorScores.length > 0;
  const bestFactorScore = hasFactorScoreRow ? Math.max(...finiteFactorScores) : null;

  const finiteLlmScores = candidates
    .map((c) => (typeof c.llmScore === 'number' && Number.isFinite(c.llmScore) ? c.llmScore : null))
    .filter((v): v is number => v != null);
  const hasLlmScoreRow = finiteLlmScores.length > 0;
  const bestLlmScore = hasLlmScoreRow ? Math.max(...finiteLlmScores) : null;

  const factorKeys = Array.from(
    new Set(
      candidates.flatMap((c) =>
        Object.entries(c.factorScores || {})
          .filter(([, val]) => typeof val === 'number' && Number.isFinite(val))
          .map(([k]) => normalizeFactorKey(k)),
      ),
    ),
  );

  return (
    <div className="mb-4 rounded-xl border border-cyan/30 bg-cyan/5 p-3.5">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-foreground">
          <BarChart3 className="h-4 w-4 text-cyan" />
          <span>{qcopy.compareTitle}</span>
          {candidates.length < 3 ? (
            <span className="rounded-full border border-cyan/25 bg-card/80 px-2 py-0.5 text-[11px] font-normal text-secondary-text">
              {qcopy.compareLimitHint}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-xs text-secondary-text hover:text-foreground"
        >
          <RotateCcw className="h-3 w-3" />
          {qcopy.compareClear}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-border/80 text-left text-secondary-text">
              <th className="py-2 pr-3 font-medium">{qcopy.compareMetric}</th>
              {candidates.map((c) => (
                <th key={c.code} className="px-3 py-2 font-semibold text-foreground">
                  <div className="flex items-center justify-between gap-2">
                    <span>
                      {c.name || c.code}{' '}
                      <span className="font-mono text-[11px] font-normal text-secondary-text">
                        ({c.code})
                      </span>
                    </span>
                    <button
                      type="button"
                      aria-label={`${qcopy.compareRemove} ${c.code}`}
                      onClick={() => onRemove(c.code)}
                      className="rounded p-0.5 text-muted-text hover:bg-card hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            <tr>
              <td className="py-2 pr-3 text-secondary-text">{qcopy.compareScore}</td>
              {candidates.map((c) => (
                <td key={c.code} className="px-3 py-2 font-mono font-bold text-cyan">
                  {c.score != null ? c.score.toFixed(2) : '-'}
                </td>
              ))}
            </tr>
            {hasFactorScoreRow ? (
              <tr>
                <td className="py-2 pr-3 text-secondary-text">{qcopy.compareFactorScore}</td>
                {candidates.map((c) => {
                  const factorScore = getCandidateExplicitFactorScore(c);
                  const isBestFactor =
                    factorScore != null &&
                    bestFactorScore != null &&
                    Math.abs(factorScore - bestFactorScore) < 1e-6;
                  return (
                    <td
                      key={c.code}
                      className={`px-3 py-2 font-mono ${isBestFactor ? 'font-bold text-cyan' : 'text-foreground'}`}
                    >
                      {factorScore != null ? factorScore.toFixed(2) : '-'}
                    </td>
                  );
                })}
              </tr>
            ) : null}
            {hasLlmScoreRow ? (
              <tr>
                <td className="py-2 pr-3 text-secondary-text">{qcopy.compareLlmScore}</td>
                {candidates.map((c) => {
                  const llmVal =
                    typeof c.llmScore === 'number' && Number.isFinite(c.llmScore) ? c.llmScore : null;
                  const isBestLlm =
                    llmVal != null && bestLlmScore != null && Math.abs(llmVal - bestLlmScore) < 1e-6;
                  return (
                    <td
                      key={c.code}
                      className={`px-3 py-2 font-mono ${isBestLlm ? 'font-bold text-success' : 'text-foreground'}`}
                    >
                      {llmVal != null ? llmVal.toFixed(2) : '-'}
                    </td>
                  );
                })}
              </tr>
            ) : null}
            <tr>
              <td className="py-2 pr-3 text-secondary-text">{qcopy.compareChange}</td>
              {candidates.map((c) => (
                <td key={c.code} className="px-3 py-2 font-mono text-foreground">
                  {c.changePct != null ? `${c.changePct > 0 ? '+' : ''}${c.changePct.toFixed(2)}%` : '-'}
                </td>
              ))}
            </tr>
            <tr>
              <td className="py-2 pr-3 text-secondary-text">{qcopy.compareRisk}</td>
              {candidates.map((c) => {
                const riskText =
                  c.riskLevel === 'high'
                    ? copy.highRisk
                    : c.riskLevel === 'medium'
                      ? copy.mediumRisk
                      : c.riskLevel === 'low'
                        ? copy.lowRisk
                        : copy.riskUnknown;
                return (
                  <td key={c.code} className="px-3 py-2 text-foreground">
                    {riskText}
                  </td>
                );
              })}
            </tr>
            {factorKeys.map((fk) => {
              const vals = candidates
                .map((c) => getCandidateFactorValue(c, fk))
                .filter((v): v is number => v != null);
              const bestVal = vals.length > 0 ? Math.max(...vals) : null;
              return (
                <tr key={fk}>
                  <td className="py-2 pr-3 text-secondary-text">{getFactorLabel(language, fk)}</td>
                  {candidates.map((c) => {
                    const val = getCandidateFactorValue(c, fk);
                    const isLeader = val != null && bestVal != null && Math.abs(val - bestVal) < 1e-6;
                    return (
                      <td key={c.code} className="px-3 py-2">
                        {val != null ? (
                          <div className="space-y-1">
                            <div className="flex items-center justify-between font-mono">
                              <span className={isLeader ? 'font-bold text-success' : 'text-foreground'}>
                                {val.toFixed(1)}
                              </span>
                            </div>
                            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface">
                              <div
                                className={`h-full rounded-full ${factorBarColorClass(val)}`}
                                style={{ width: `${Math.min(100, Math.max(4, val))}%` }}
                              />
                            </div>
                          </div>
                        ) : (
                          <span className="text-muted-text">-</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
