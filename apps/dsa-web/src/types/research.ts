export type ResearchHorizonView = {
  horizon: string;
  conclusion: string;
  stance: string;
  actionBoundary: string;
  confidence: number;
  evidenceIds: string[];
  risks: string[];
  abstainReason: string;
};

export type ResearchConflictView = {
  claimText: string;
  conflictingProviders: string[];
  evidenceIds: string[];
  conflictType: string;
  resolutionStatus: string;
  reasonCannotAverage: string;
};

export type ResearchDecisionView = {
  asOf: string;
  shortTerm: ResearchHorizonView;
  mediumTerm: ResearchHorizonView;
  longTerm: ResearchHorizonView;
  conflicts: ResearchConflictView[];
  providerVersions: Record<string, string>;
};

export type ResearchJob = {
  jobId: string;
  taskId: string;
  status: string;
  idempotencyKey: string;
  subject: string;
  market: string;
  asOf: string;
  createdAt: string;
  updatedAt: string;
  decision: ResearchDecisionView | null;
  warnings: string[];
  error: string;
};

export type ResearchJobCreateRequest = {
  subject: string;
  market?: string;
  asOf?: string;
};
