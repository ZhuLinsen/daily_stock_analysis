export interface MasterDebatePersona {
  personaId: string;
  name: string;
  englishName: string;
  philosophy: string;
  stance: string;
  confidence: number;
  thesis: string;
  keyPoints: string[];
  keyLevels: Record<string, unknown>;
  risk: string;
}

export interface MasterDebateRequest {
  code: string;
  name?: string;
  market: string;
  context?: string;
  analysisHistoryId?: number;
  persist?: boolean;
}

export interface MasterDebateResponse {
  id?: number | null;
  code: string;
  name?: string | null;
  market: string;
  consensus: string;
  divergence: number;
  conviction: number;
  bullCount: number;
  bearCount: number;
  neutralCount: number;
  bullArguments: string[];
  bearArguments: string[];
  personas: MasterDebatePersona[];
  summary: string;
}

export interface MasterDebateRecordItem {
  id: number;
  code: string;
  name?: string | null;
  market: string;
  consensus: string;
  divergence: number;
  bullCount: number;
  bearCount: number;
  neutralCount: number;
  personas: MasterDebatePersona[];
  summary?: string | null;
  createdAt?: string | null;
}

export interface MasterDebateListResponse {
  items: MasterDebateRecordItem[];
  total: number;
  page: number;
  pageSize: number;
}
