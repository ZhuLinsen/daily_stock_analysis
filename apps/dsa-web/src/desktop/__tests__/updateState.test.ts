import { describe, expect, it } from 'vitest';
import { formatUiText, UI_TEXT } from '../../i18n/uiText';
import { getDesktopUpdateBadgeTone, getDesktopUpdateNotice, isBusyDesktopUpdateStatus, normalizeDesktopUpdateState } from '../updateState';

const t = (key: keyof typeof UI_TEXT.zh, params?: Record<string, string | number>) => (
  formatUiText(UI_TEXT.zh[key], params)
);

describe('desktop updateState helpers', () => {
  it('normalizes raw IPC payloads and falls back to idle/manual', () => {
    expect(normalizeDesktopUpdateState(null)).toBeNull();
    expect(normalizeDesktopUpdateState({
      status: ' update-available ',
      latestVersion: '3.31.0',
      downloadPercent: '42',
    })).toEqual(expect.objectContaining({
      status: 'update-available',
      updateMode: 'manual',
      latestVersion: '3.31.0',
      downloadPercent: 42,
    }));
  });

  it('maps notice actions for available, downloaded, and error states', () => {
    expect(getDesktopUpdateNotice({
      status: 'update-available',
      currentVersion: '3.30.0',
      latestVersion: '3.31.0',
      updateMode: 'manual',
    }, t)?.actionKind).toBe('release');

    expect(getDesktopUpdateNotice({
      status: 'update-downloaded',
    }, t)?.actionKind).toBe('install');

    expect(getDesktopUpdateNotice({
      status: 'error',
      updateMode: 'auto',
      releaseUrl: 'https://example.test/releases',
    }, t)?.actionKind).toBe('release');
  });

  it('keeps auto-download available notices without a release action', () => {
    expect(getDesktopUpdateNotice({
      status: 'update-available',
      updateMode: 'auto',
      latestVersion: '3.31.0',
    }, t)?.actionLabel).toBeUndefined();
  });

  it('classifies badge tones and busy statuses', () => {
    expect(getDesktopUpdateBadgeTone('update-available')).toBe('warning');
    expect(getDesktopUpdateBadgeTone('update-downloaded')).toBe('success');
    expect(getDesktopUpdateBadgeTone('error')).toBe('danger');
    expect(getDesktopUpdateBadgeTone('idle')).toBeNull();
    expect(isBusyDesktopUpdateStatus('checking')).toBe(true);
    expect(isBusyDesktopUpdateStatus('up-to-date')).toBe(false);
  });
});
