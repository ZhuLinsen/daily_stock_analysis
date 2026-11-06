import type { DecisionAction } from './analysis';

export type ResearchQualityLevel = 'good' | 'usable' | 'limited' | 'poor' | 'unknown';
export type ResearchDirection = 'bullish' | 'bearish' | 'neutral' | 'unknown';
export type ResearchEvidenceFreshness = 'fresh' | 'stale' | 'unknown';
export type ResearchInvalidationCategory =
  | 'price'
  | 'volume'
  | 'evidence'
  | 'market'
  | 'time'
  | 'data_quality'
  | 'manual';
export type ResearchInvalidationSeverity = 'watch' | 'warning' | 'critical';

export interface ResearchSubject {
  stockCode: string;
  stockName?: string | null;
  market?: string | null;
  entityRef?: string | null;
}

export interface ResearchThesis {
  direction: ResearchDirection;
  summary: string;
  confidence?: number | null;
  score?: number | null;
  horizon?: string | null;
  action?: DecisionAction | null;
  actionLabel?: string | null;
  reasons: string[];
  risks: string[];
}

export interface ResearchEvidenceItem {
  id: string;
  sourceType: string;
  title: string;
  summary?: string | null;
  source?: string | null;
  freshness: ResearchEvidenceFreshness;
  qualityLevel: ResearchQualityLevel;
  asOf?: string | null;
  url?: string | null;
  metadata: Record<string, unknown>;
}

export interface ResearchInvalidationCondition {
  id: string;
  category: ResearchInvalidationCategory;
  description: string;
  trigger?: string | null;
  severity: ResearchInvalidationSeverity;
  metric?: string | null;
  threshold?: string | null;
  dueAt?: string | null;
  metadata: Record<string, unknown>;
}

export interface ResearchNextAction {
  action: string;
  label: string;
  reason?: string | null;
  dueAt?: string | null;
  metadata: Record<string, unknown>;
}

export interface ResearchDataQuality {
  level: ResearchQualityLevel;
  overallScore?: number | null;
  sourceCount: number;
  staleCount: number;
  missingBlocks: string[];
  limitations: string[];
}

export interface ResearchArtifact {
  schemaVersion: 'research-artifact-v1';
  artifactId: string;
  sourceReportId?: number | null;
  sourceQueryId?: string | null;
  createdAt?: string | null;
  subject: ResearchSubject;
  thesis: ResearchThesis;
  evidence: ResearchEvidenceItem[];
  invalidationConditions: ResearchInvalidationCondition[];
  nextActions: ResearchNextAction[];
  dataQuality: ResearchDataQuality;
  metadata: Record<string, unknown>;
}
