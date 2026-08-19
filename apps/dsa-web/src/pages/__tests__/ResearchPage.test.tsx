import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import ResearchPage from '../ResearchPage';
import type { ResearchJob } from '../../types/research';

const { create, cancel } = vi.hoisted(() => ({
  create: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock('../../api/research', () => ({
  researchApi: {
    create: (...args: unknown[]) => create(...args),
    cancel: (...args: unknown[]) => cancel(...args),
  },
}));

const job: ResearchJob = {
  jobId: 'research-1',
  taskId: 'task-1',
  status: 'succeeded',
  idempotencyKey: 'k1',
  subject: 'TEST',
  market: 'cn',
  asOf: '2026-07-01',
  createdAt: '',
  updatedAt: '',
  warnings: [],
  error: '',
  decision: {
    asOf: '2026-07-01',
    shortTerm: {
      horizon: 'short_term',
      conclusion: '',
      stance: 'neutral',
      actionBoundary: '',
      confidence: 0.4,
      evidenceIds: ['ev-short'],
      risks: [],
      abstainReason: '',
    },
    mediumTerm: {
      horizon: 'medium_term',
      conclusion: '',
      stance: 'abstain',
      actionBoundary: '',
      confidence: 0,
      evidenceIds: [],
      risks: [],
      abstainReason: 'missing report',
    },
    longTerm: {
      horizon: 'long_term',
      conclusion: '',
      stance: 'bullish',
      actionBoundary: '',
      confidence: 0.7,
      evidenceIds: ['ev-long'],
      risks: [],
      abstainReason: '',
    },
    conflicts: [],
    providerVersions: { mock: '0.2.0' },
  },
};

describe('ResearchPage', () => {
  beforeEach(() => {
    create.mockReset();
    cancel.mockReset();
    create.mockResolvedValue(job);
    cancel.mockResolvedValue({ ...job, status: 'cancelled' });
  });

  it('submits a subject and renders stance plus evidence', async () => {
    render(
      <UiLanguageProvider>
        <ResearchPage />
      </UiLanguageProvider>,
    );

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'TEST' } });
    fireEvent.click(screen.getByRole('button', { name: /开始研究|Run research/ }));

    await waitFor(() => expect(create).toHaveBeenCalledWith({ subject: 'TEST' }));
    expect(await screen.findByText('neutral')).toBeInTheDocument();
    expect(screen.getByText('ev-short')).toBeInTheDocument();
    expect(screen.getByText('missing report')).toBeInTheDocument();
    expect(screen.getByText('bullish')).toBeInTheDocument();
    expect(screen.queryByText(/place_order|broker|quantity/i)).not.toBeInTheDocument();
  });
});
