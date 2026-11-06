import type {
  DataCapabilityOverview,
  DataDatasetQuality,
  DataPriorityView,
  DataProviderCapability,
} from '../types/dataCapability';
import apiClient from './index';

type RawOverview = {
  as_of: string;
  providers: Array<Record<string, unknown>>;
  datasets: Array<Record<string, unknown>>;
  priorities: Array<Record<string, unknown>>;
  warnings: string[];
};

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

function mapProvider(raw: Record<string, unknown>): DataProviderCapability {
  return {
    name: String(raw.name ?? ''),
    label: String(raw.label ?? ''),
    enabled: Boolean(raw.enabled),
    configured: Boolean(raw.configured),
    status: raw.status as DataProviderCapability['status'],
    priority: raw.priority == null ? null : Number(raw.priority),
    markets: strings(raw.markets),
    datasets: strings(raw.datasets),
    datasetMarkets: (raw.dataset_markets as Record<string, string[]> | undefined) ?? {},
    warnings: strings(raw.warnings),
    lastError: raw.last_error == null ? null : String(raw.last_error),
    cooldown: raw.cooldown == null ? null : Boolean(raw.cooldown),
  };
}

function mapDataset(raw: Record<string, unknown>): DataDatasetQuality {
  return {
    dataset: String(raw.dataset ?? ''),
    status: raw.status as DataDatasetQuality['status'],
    source: raw.source == null ? null : String(raw.source),
    stale: raw.stale == null ? null : Boolean(raw.stale),
    lastSuccess: raw.last_success == null ? null : String(raw.last_success),
    lastError: raw.last_error == null ? null : String(raw.last_error),
    fallbackFrom: strings(raw.fallback_from),
    coverage: (raw.coverage as Record<string, unknown> | null | undefined) ?? null,
    warnings: strings(raw.warnings),
  };
}

function mapPriority(raw: Record<string, unknown>): DataPriorityView {
  return {
    scenario: String(raw.scenario ?? ''),
    providers: strings(raw.providers),
    source: String(raw.source ?? ''),
    warnings: strings(raw.warnings),
  };
}

export const dataCapabilityApi = {
  async getOverview(): Promise<DataCapabilityOverview> {
    const response = await apiClient.get<RawOverview>('/api/v1/data/overview');
    return {
      asOf: response.data.as_of,
      providers: response.data.providers.map(mapProvider),
      datasets: response.data.datasets.map(mapDataset),
      priorities: response.data.priorities.map(mapPriority),
      warnings: response.data.warnings,
    };
  },
};
