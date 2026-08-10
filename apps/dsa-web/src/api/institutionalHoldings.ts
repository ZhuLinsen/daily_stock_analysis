import apiClient from './index';
import { toCamelCase } from './utils';

export const DEFAULT_INSTITUTIONAL_MANAGER_CIK = '0001759760';

export type InstitutionalHoldingStatus = 'new' | 'increased' | 'decreased' | 'unchanged' | 'exited';

export type InstitutionalFilingSnapshot = {
  managerCik: string;
  managerName: string;
  formType: string;
  accessionNumber: string;
  reportPeriod: string;
  filedDate: string;
  acceptedAt: string;
  entryCount: number;
  totalValueUsd: number;
  primaryDocumentUrl: string;
  informationTableUrl: string;
};

export type InstitutionalHoldingDelta = {
  issuerName: string;
  titleOfClass: string;
  cusip: string;
  putCall: string;
  status: InstitutionalHoldingStatus;
  currentShares: number | string | null;
  previousShares: number | string | null;
  shareDelta: number | string | null;
  shareDeltaPct: number | null;
  currentValueUsd: number | null;
  previousValueUsd: number | null;
  currentWeightPct: number | null;
};

export type InstitutionalHoldingAnalysis = {
  managerCik: string;
  managerName: string;
  current: InstitutionalFilingSnapshot;
  previous: InstitutionalFilingSnapshot | null;
  top4ConcentrationPct: number;
  top6ConcentrationPct: number;
  holdings: InstitutionalHoldingDelta[];
  disclosureNote: string;
};

export type InstitutionalHoldingImportResult = {
  managerCik: string;
  requested: number;
  processed: number;
  created: number;
  refreshed: number;
  unchanged: number;
  holdingsSaved: number;
  errors: Array<{ accessionNumber: string; message: string }>;
};

export const institutionalHoldingsApi = {
  async getLatest(cik = DEFAULT_INSTITUTIONAL_MANAGER_CIK): Promise<InstitutionalHoldingAnalysis> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/institutional-holdings/${encodeURIComponent(cik)}/latest`,
    );
    return toCamelCase<InstitutionalHoldingAnalysis>(response.data);
  },

  async importRecent(
    cik = DEFAULT_INSTITUTIONAL_MANAGER_CIK,
    maxFilings = 8,
  ): Promise<InstitutionalHoldingImportResult> {
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/institutional-holdings/import',
      { cik, max_filings: maxFilings },
    );
    return toCamelCase<InstitutionalHoldingImportResult>(response.data);
  },
};
