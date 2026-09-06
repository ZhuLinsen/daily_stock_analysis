export type ProviderCapabilityStatus = 'ok' | 'partial' | 'unconfigured' | 'unavailable' | 'unknown';

export type DatasetQualityStatus =
  | 'ok'
  | 'degraded'
  | 'partial'
  | 'unconfigured'
  | 'unavailable'
  | 'unknown'
  | 'stale';

export type DataProviderCapability = {
  name: string;
  label: string;
  enabled: boolean;
  configured: boolean;
  status: ProviderCapabilityStatus;
  priority?: number | null;
  markets: string[];
  datasets: string[];
  datasetMarkets: Record<string, string[]>;
  warnings: string[];
  lastError?: string | null;
  cooldown?: boolean | null;
};

export type DataDatasetQuality = {
  dataset: string;
  status: DatasetQualityStatus;
  source?: string | null;
  stale?: boolean | null;
  lastSuccess?: string | null;
  lastError?: string | null;
  fallbackFrom: string[];
  coverage?: Record<string, unknown> | null;
  warnings: string[];
};

export type DataPriorityView = {
  scenario: string;
  providers: string[];
  source: string;
  warnings: string[];
};

export type DataCapabilityOverview = {
  asOf: string;
  providers: DataProviderCapability[];
  datasets: DataDatasetQuality[];
  priorities: DataPriorityView[];
  warnings: string[];
};
