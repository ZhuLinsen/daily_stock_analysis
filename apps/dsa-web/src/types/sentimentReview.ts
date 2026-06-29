export type TrendPoint = { tradeDate: string; value: number | null; quality: string; sampleCount: number | null };

export type SentimentReviewDetail = {
  id: number;
  market: string;
  tradeDate: string;
  runStatus: string;
  dataQuality: string;
  payload: {
    quality: string;
    emotionState?: string | null;
    breadth?: Record<string, number | null>;
    boards?: {
      limitUpCount?: number;
      brokenCount?: number;
      brokenRate?: number | null;
      highest?: number | null;
      promotionRates?: Record<string, number | null>;
      ladder?: Record<string, number>;
    };
    nextDayFeedback?: Record<string, number | null>;
    themes?: Array<{ name: string; limitUpCount: number }>;
    completeness?: Record<string, boolean>;
    llmStatus?: string;
  };
  narrative: { analysis?: string | null; nextDayWatch?: string | null; riskNotes?: string | null };
};

export type SentimentReviewDate = { tradeDate: string; runStatus: string; dataQuality: string; updatedAt?: string };
