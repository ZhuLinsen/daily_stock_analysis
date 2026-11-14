import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../../../api';
import { analysisApi } from '../../../api/analysis';
import { historyApi } from '../../../api/history';
import type { AnalysisReport, AnalysisResult } from '../../../types/analysis';
import { ReportSummary } from '../ReportSummary';

// Keep API conversion and all report components real; replace only HTTP transport.
const rawReport = (maxPct: number, stopLoss: number | null) => ({
  meta: {
    query_id: 'risk-budget', stock_code: 'AAPL', current_price: 100,
    report_type: 'detailed', report_language: 'en', created_at: '2026-01-01T00:00:00Z',
  },
  summary: {
    analysis_summary: 'Stop-risk regression', operation_advice: 'Buy',
    sentiment_score: 80, action: 'buy',
  },
  strategy: { ideal_buy: '100', stop_loss: stopLoss?.toString(), take_profit: '150' },
  structured_report: {
    schema_version: 'research-artifact-v1', artifact_id: 'report:AAPL:risk-budget',
    subject: { stock_code: 'AAPL' },
    thesis: { direction: 'bullish', summary: 'Stop-risk regression', action: 'buy', reasons: [], risks: [] },
    evidence: [],
    invalidation_conditions: [{
      id: 'manual:thesis_reassessment', category: 'manual', severity: 'warning',
      description: 'Reassess if market conditions change.',
    }],
    next_actions: [],
    data_quality: { level: 'good', source_count: 1, stale_count: 0, limitations: [], missing_blocks: [] },
    metadata: {
      levels: {
        reference_price: 100, ideal_buy: 100, stop_loss: stopLoss, take_profit: 150,
        status: stopLoss === null ? 'conditional_watch' : 'active', validation: 'ok',
      },
      position: { min_pct: 0, max_pct: maxPct, risk_budget_pct: 1.2, method: 'atr_risk_budget' },
    },
  },
});

afterEach(() => vi.restoreAllMocks());

describe('ReportSummary stop-risk advice through API payload conversion', () => {
  for (const entry of ['sync', 'async', 'history'] as const) {
    it.each([
      { maxPct: 4, stopLoss: 70, visible: true },
      { maxPct: 5, stopLoss: 70, visible: false },
      { maxPct: 30, stopLoss: null, visible: false },
    ])(`${entry}: guards max=$maxPct, stop=$stopLoss`, async ({ maxPct, stopLoss, visible }) => {
      const report = rawReport(maxPct, stopLoss);
      let data: AnalysisReport | AnalysisResult;
      if (entry === 'sync') {
        vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { report } });
        const response = await analysisApi.analyze({ stockCode: 'AAPL' });
        if (!('report' in response)) throw new Error('Expected completed report');
        data = response;
      } else if (entry === 'async') {
        vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { status: 'completed', result: { report } } });
        const status = await analysisApi.getStatus('risk-budget');
        data = status.result!;
      } else {
        vi.spyOn(apiClient, 'get').mockResolvedValue({ data: report });
        data = await historyApi.getDetail(42);
      }
      render(<ReportSummary data={data} isHistory={entry === 'history'} />);
      expect(screen.getByText('Stop-risk regression')).toBeInTheDocument();
      const badge = screen.queryByText('Stop-loss Risk-budget Position 0%–4%');
      if (visible) expect(badge).toBeInTheDocument();
      else expect(screen.queryByText(/Stop-loss Risk-budget Position/)).not.toBeInTheDocument();
    });
  }

  it('renders old history reports without structured metadata', async () => {
    const { structured_report: _structuredReport, ...legacy } = rawReport(4, 70);
    void _structuredReport;
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: legacy });
    render(<ReportSummary data={await historyApi.getDetail(42)} isHistory />);
    expect(screen.getByText('Stop-risk regression')).toBeInTheDocument();
    expect(screen.queryByText(/Stop-loss Risk-budget Position/)).not.toBeInTheDocument();
  });
});
