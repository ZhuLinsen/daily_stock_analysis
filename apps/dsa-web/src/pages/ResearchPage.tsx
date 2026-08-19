import React, { useState } from 'react';
import { researchApi } from '../api/research';
import type { ParsedApiError } from '../api/error';
import { ApiErrorAlert, AppPage, Card, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { ResearchHorizonView, ResearchJob } from '../types/research';

function asParsedError(error: unknown, title: string): ParsedApiError {
  if (error && typeof error === 'object' && 'parsedError' in error) {
    const parsed = (error as { parsedError?: ParsedApiError }).parsedError;
    if (parsed) {
      return parsed;
    }
  }
  const message = error instanceof Error ? error.message : title;
  return {
    title,
    message,
    rawMessage: message,
    category: 'http_error',
  };
}

const HorizonCard: React.FC<{ title: string; view?: ResearchHorizonView }> = ({ title, view }) => {
  if (!view) {
    return (
      <Card padding="sm">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="mt-2 text-sm text-secondary-text">—</p>
      </Card>
    );
  }
  return (
    <Card padding="sm">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <p className="mt-2 text-lg font-medium capitalize text-cyan">{view.stance}</p>
      {view.abstainReason ? (
        <p className="mt-1 text-sm text-secondary-text">{view.abstainReason}</p>
      ) : null}
      {view.evidenceIds.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs text-secondary-text">
          {view.evidenceIds.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
};

const ResearchPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [subject, setSubject] = useState('');
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const code = subject.trim();
    if (!code) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await researchApi.create({ subject: code });
      setJob(created);
    } catch (err) {
      setError(asParsedError(err, t('research.error')));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!job) {
      return;
    }
    setBusy(true);
    try {
      const updated = await researchApi.cancel(job.jobId);
      setJob(updated);
    } catch (err) {
      setError(asParsedError(err, t('research.error')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppPage>
      <PageHeader title={t('research.pageTitle')} description={t('research.pageDescription')} />
      <Card className="mb-6">
        <form
          className="flex flex-col gap-3 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="sr-only" htmlFor="research-subject">
            {t('research.subject')}
          </label>
          <input
            id="research-subject"
            className="h-10 flex-1 rounded-xl border border-border bg-card px-3 text-sm"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder={t('research.subjectPlaceholder')}
          />
          <button type="submit" className="btn-primary h-10 px-4" disabled={busy}>
            {t('research.submit')}
          </button>
          <button type="button" className="btn-secondary h-10 px-4" disabled={busy || !job} onClick={() => void cancel()}>
            {t('research.cancel')}
          </button>
        </form>
      </Card>
      {error ? <ApiErrorAlert error={error} /> : null}
      {job ? (
        <div className="space-y-4">
          <p className="text-sm text-secondary-text">
            {t('research.status')}: {job.status}
          </p>
          <div className="grid gap-4 md:grid-cols-3">
            <HorizonCard title={t('research.short')} view={job.decision?.shortTerm} />
            <HorizonCard title={t('research.medium')} view={job.decision?.mediumTerm} />
            <HorizonCard title={t('research.long')} view={job.decision?.longTerm} />
          </div>
          {job.decision?.conflicts?.length ? (
            <Card>
              <h3 className="mb-2 text-sm font-semibold">{t('research.conflicts')}</h3>
              <ul className="space-y-2 text-sm text-secondary-text">
                {job.decision.conflicts.map((item) => (
                  <li key={`${item.conflictType}-${item.claimText}`}>
                    {item.claimText || item.reasonCannotAverage}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      ) : null}
    </AppPage>
  );
};

export default ResearchPage;
