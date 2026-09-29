import type React from 'react';
import { useMemo, useState } from 'react';
import type { DecisionAction } from '../../types/analysis';
import type {
  DecisionProfile,
  DecisionSignalHorizon,
  DecisionSignalProfileCalibration as DecisionSignalProfileCalibrationData,
  DecisionSignalProfileCalibrationBucket,
} from '../../types/decisionSignals';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { buildDecisionActionLabelMap } from '../../utils/decisionAction';
import { getDecisionSignalHorizonLabel } from '../../utils/decisionSignalLabels';
import { getDecisionProfileLabel } from '../../utils/decisionSignalProfile';
import { cn } from '../../utils/cn';

type BreakdownMode = 'horizon' | 'action';

const PROFILE_OPTIONS: DecisionProfile[] = ['conservative', 'balanced', 'aggressive'];
const ACTION_VALUES: DecisionAction[] = ['buy', 'add', 'hold', 'reduce', 'sell', 'watch', 'avoid', 'alert'];
const HORIZON_VALUES: DecisionSignalHorizon[] = ['intraday', '1d', '3d', '5d', '10d', 'swing', 'long'];

function isDecisionAction(value: string | undefined): value is DecisionAction {
  return !!value && ACTION_VALUES.includes(value as DecisionAction);
}

function isDecisionSignalHorizon(value: string | undefined): value is DecisionSignalHorizon {
  return !!value && HORIZON_VALUES.includes(value as DecisionSignalHorizon);
}

function formatPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '';
  const formatted = Number(value).toFixed(2).replace(/\.?0+$/, '');
  return `${formatted}%`;
}

type Props = {
  calibration: DecisionSignalProfileCalibrationData;
};

export const DecisionSignalProfileCalibration: React.FC<Props> = ({ calibration }) => {
  const { t } = useUiLanguage();
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);
  const [selectedProfile, setSelectedProfile] = useState<DecisionProfile>('balanced');
  const [breakdownMode, setBreakdownMode] = useState<BreakdownMode>('horizon');
  const profileBuckets = calibration.breakdowns.decisionProfile;
  const selectedProfileBucket = profileBuckets.find(
    (bucket) => bucket.dimensions.decisionProfile === selectedProfile,
  );
  const unknownProfileBucket = profileBuckets.find(
    (bucket) => bucket.dimensions.decisionProfile === 'unknown',
  );
  const allChildBuckets = breakdownMode === 'horizon'
    ? calibration.breakdowns.decisionProfileHorizon
    : calibration.breakdowns.decisionProfileAction;
  const childBuckets = allChildBuckets.filter(
    (bucket) => bucket.dimensions.decisionProfile === selectedProfile,
  );

  const metricRows = (bucket: DecisionSignalProfileCalibrationBucket) => [
    {
      label: t('decisionSignals.profileCalibrationHitRate'),
      value: formatPercent(bucket.hitRatePct),
      tone: 'text-success',
    },
    {
      label: t('decisionSignals.profileCalibrationAverageReturn'),
      value: formatPercent(bucket.avgStockReturnPct),
      tone: 'text-foreground',
    },
    {
      label: t('decisionSignals.profileCalibrationMissRate'),
      value: formatPercent(bucket.missRatePct),
      tone: 'text-danger',
    },
    {
      label: t('decisionSignals.profileCalibrationUnableRate'),
      value: formatPercent(bucket.unableRatePct),
      tone: 'text-warning',
    },
    {
      label: t('decisionSignals.profileCalibrationMae'),
      value: formatPercent(bucket.maxAdverseExcursionPct),
      tone: 'text-warning',
    },
  ];

  const childLabel = (bucket: DecisionSignalProfileCalibrationBucket): string => {
    if (breakdownMode === 'action') {
      const action = bucket.dimensions.action;
      return isDecisionAction(action)
        ? actionLabels[action]
        : t('decisionSignals.profileCalibrationUnknownDimension');
    }
    const horizon = bucket.dimensions.horizon;
    return isDecisionSignalHorizon(horizon)
      ? getDecisionSignalHorizonLabel(horizon, t)
      : t('decisionSignals.profileCalibrationUnknownDimension');
  };

  return (
    <section className="mt-5 border-t border-border/60 pt-5" aria-labelledby="profile-calibration-title">
      <div className="max-w-3xl">
        <h3 id="profile-calibration-title" className="text-base font-semibold text-foreground">
          {t('decisionSignals.profileCalibrationTitle')}
        </h3>
        <p className="mt-1 text-sm text-secondary-text">
          {t('decisionSignals.profileCalibrationDescription')}
        </p>
        <p className="mt-1 text-xs text-secondary-text">
          {t('decisionSignals.profileCalibrationThreshold', {
            count: calibration.minimumCompletedSampleSize,
          })}
        </p>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {PROFILE_OPTIONS.map((profile) => {
          const bucket = profileBuckets.find((item) => item.dimensions.decisionProfile === profile);
          const completed = bucket?.completed ?? 0;
          const selected = selectedProfile === profile;
          return (
            <button
              key={profile}
              type="button"
              aria-pressed={selected}
              onClick={() => setSelectedProfile(profile)}
              className={cn(
                'rounded-xl border px-3 py-3 text-left transition-colors',
                selected
                  ? 'border-primary/70 bg-primary/10 text-foreground'
                  : 'border-border/60 bg-elevated/30 text-secondary-text hover:border-primary/40 hover:text-foreground',
              )}
            >
              <span className="block text-sm font-medium">{getDecisionProfileLabel(profile, t)}</span>
              <span className="mt-1 block text-xs">
                {t('decisionSignals.profileCalibrationCompletedShort', { count: completed })}
              </span>
            </button>
          );
        })}
      </div>

      {unknownProfileBucket && unknownProfileBucket.total > 0 ? (
        <p className="mt-3 text-xs text-secondary-text">
          {t('decisionSignals.profileCalibrationUnknownNotice', { count: unknownProfileBucket.total })}
        </p>
      ) : null}

      <div className="mt-4 rounded-xl border border-border/60 bg-elevated/25 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-sm font-semibold text-foreground">
            {getDecisionProfileLabel(selectedProfile, t)}
          </h4>
          <p className="text-xs text-secondary-text">
            {t('decisionSignals.profileCalibrationSampleCounts', {
              completed: selectedProfileBucket?.completed ?? 0,
              total: selectedProfileBucket?.total ?? 0,
            })}
          </p>
        </div>
        {!selectedProfileBucket?.sampleSufficient ? (
          <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
            {t('decisionSignals.profileCalibrationInsufficient')}
          </p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {metricRows(selectedProfileBucket).map((metric) => (
              <div key={metric.label} className="rounded-lg border border-border/50 bg-background/30 px-3 py-2">
                <p className="text-xs text-secondary-text">{metric.label}</p>
                <p className={cn('mt-1 text-lg font-semibold', metric.tone)}>
                  {metric.value || t('decisionSignals.profileCalibrationUnavailable')}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <p className="mt-3 text-xs text-secondary-text">
        {t('decisionSignals.profileCalibrationMaeDescription')}
      </p>

      <div className="mt-5 flex flex-wrap gap-2" aria-label={t('decisionSignals.profileCalibrationBreakdownLabel')}>
        {(['horizon', 'action'] as BreakdownMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={breakdownMode === mode}
            onClick={() => setBreakdownMode(mode)}
            className={cn(
              'rounded-lg border px-3 py-2 text-sm transition-colors',
              breakdownMode === mode
                ? 'border-primary/70 bg-primary/10 text-foreground'
                : 'border-border/60 text-secondary-text hover:border-primary/40 hover:text-foreground',
            )}
          >
            {mode === 'horizon'
              ? t('decisionSignals.profileCalibrationByHorizon')
              : t('decisionSignals.profileCalibrationByAction')}
          </button>
        ))}
      </div>

      {childBuckets.length === 0 ? (
        <p className="mt-3 text-sm text-secondary-text">
          {t('decisionSignals.profileCalibrationNoBreakdownSamples')}
        </p>
      ) : (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {childBuckets.map((bucket) => {
            const label = childLabel(bucket);
            return (
              <article
                key={`${selectedProfile}-${breakdownMode}-${label}`}
                className="rounded-xl border border-border/60 bg-elevated/25 p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h5 className="text-sm font-semibold text-foreground">{label}</h5>
                  <p className="text-xs text-secondary-text">
                    {t('decisionSignals.profileCalibrationSampleCounts', {
                      completed: bucket.completed,
                      total: bucket.total,
                    })}
                  </p>
                </div>
                {!bucket.sampleSufficient ? (
                  <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
                    {t('decisionSignals.profileCalibrationInsufficient')}
                  </p>
                ) : (
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {metricRows(bucket).map((metric) => (
                      <div key={metric.label} className="rounded-lg border border-border/50 bg-background/30 px-3 py-2">
                        <p className="text-xs text-secondary-text">{metric.label}</p>
                        <p className={cn('mt-1 text-base font-semibold', metric.tone)}>
                          {metric.value || t('decisionSignals.profileCalibrationUnavailable')}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
};
