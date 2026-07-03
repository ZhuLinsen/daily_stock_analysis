import type {
  DecisionProfileDisplay,
  DecisionSignalItem,
} from '../types/decisionSignals';

export function getDecisionProfile(item: DecisionSignalItem): DecisionProfileDisplay {
  const metadata = item.metadata;
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return 'unknown';
  const value = (metadata as Record<string, unknown>).decision_profile;
  return value === 'conservative' || value === 'balanced' || value === 'aggressive'
    ? value
    : 'unknown';
}
