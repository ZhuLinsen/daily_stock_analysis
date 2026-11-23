import type {
  DecisionProfileDisplay,
  DecisionSignalItem,
} from '../types/decisionSignals';
import type { UiTextKey } from '../i18n/uiText';

function isDecisionProfile(value: unknown): value is Exclude<DecisionProfileDisplay, 'unknown'> {
  return value === 'conservative' || value === 'balanced' || value === 'aggressive';
}

export function getDecisionProfile(item: DecisionSignalItem): DecisionProfileDisplay {
  if (Object.prototype.hasOwnProperty.call(item, 'decisionProfile')) {
    return isDecisionProfile(item.decisionProfile) ? item.decisionProfile : 'unknown';
  }

  const metadata = item.metadata;
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return 'unknown';
  const value = (metadata as Record<string, unknown>).decision_profile;
  return isDecisionProfile(value) ? value : 'unknown';
}

export function getDecisionProfileLabel(
  profile: DecisionProfileDisplay,
  t: (key: UiTextKey) => string,
): string {
  return t(`decisionSignals.profile.${profile}` as UiTextKey);
}

export function getDecisionSignalProfileLabel(
  item: DecisionSignalItem,
  t: (key: UiTextKey) => string,
): string {
  return getDecisionProfileLabel(getDecisionProfile(item), t);
}
