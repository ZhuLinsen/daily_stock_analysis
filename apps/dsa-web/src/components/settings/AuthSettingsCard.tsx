import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { authApi } from '../../api/auth';
import { getParsedApiError, isParsedApiError, type ParsedApiError } from '../../api/error';
import { useAuth } from '../../hooks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { Badge, Button, Input, Checkbox } from '../common';
import { SettingsAlert } from './SettingsAlert';
import { SettingsSectionCard } from './SettingsSectionCard';

function createNextModeLabel(authEnabled: boolean, desiredEnabled: boolean, t: (key: UiTextKey) => string) {
  if (authEnabled && !desiredEnabled) {
    return t('settings.disableAuth');
  }
  if (!authEnabled && desiredEnabled) {
    return t('settings.enableAuth');
  }
  return authEnabled ? t('settings.keepAuthEnabled') : t('settings.keepAuthDisabled');
}

export const AuthSettingsCard: React.FC = () => {
  const { authEnabled, setupState, refreshStatus } = useAuth();
  const { t } = useUiLanguage();
  const [desiredEnabled, setDesiredEnabled] = useState(authEnabled);
  const [currentPassword, setCurrentPassword] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const isDirty = desiredEnabled !== authEnabled || currentPassword || password || passwordConfirm;
  const targetActionLabel = createNextModeLabel(authEnabled, desiredEnabled, t);

  const helperText = useMemo(() => {
    switch (setupState) {
      case 'no_password':
        return t('settings.authHelperNoPassword');
      case 'password_retained':
        return t('settings.authHelperPasswordRetained');
      case 'enabled':
        return !desiredEnabled 
          ? t('settings.authHelperTurnOff')
          : t('settings.authHelperEnabled');
      default:
        return t('settings.authHelperDefault');
    }
  }, [setupState, desiredEnabled, t]);

  useEffect(() => {
    setDesiredEnabled(authEnabled);
  }, [authEnabled]);

  const resetForm = () => {
    setCurrentPassword('');
    setPassword('');
    setPasswordConfirm('');
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSuccessMessage(null);

    // Initial setup validation
    if (setupState === 'no_password' && desiredEnabled) {
      if (!password) {
        setError(t('settings.authRequiredPassword'));
        return;
      }
      if (password !== passwordConfirm) {
        setError(t('login.passwordMismatch'));
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await authApi.updateSettings(
        desiredEnabled,
        password.trim() || undefined,
        passwordConfirm.trim() || undefined,
        currentPassword.trim() || undefined,
      );
      await refreshStatus();
      setSuccessMessage(desiredEnabled ? t('settings.authSuccessUpdated') : t('settings.authSuccessDisabled'));
      resetForm();
    } catch (err: unknown) {
      setError(getParsedApiError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <SettingsSectionCard
      title={t('settings.authTitle')}
      description={t('settings.authDescription')}
      actions={
        <Badge
          variant={authEnabled ? 'success' : 'default'}
          size="sm"
          className={authEnabled ? '' : 'border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-secondary-text'}
        >
          {authEnabled ? t('settings.authEnabled') : t('settings.authDisabled')}
        </Badge>
      }
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        <div className="rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card transition-[background-color,border-color] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <p className="text-sm font-semibold text-foreground">{t('settings.authStatus')}</p>
              <p className="text-xs leading-6 text-muted-text">{helperText}</p>
            </div>
            <Checkbox
              checked={desiredEnabled}
              disabled={isSubmitting}
              label={desiredEnabled ? t('common.enabled') : t('common.disabled')}
              onChange={(event) => setDesiredEnabled(event.target.checked)}
              containerClassName="rounded-full border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] px-4 py-2 shadow-soft-card transition-[background-color,border-color] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface)]"
            />
          </div>
        </div>

        {/* Password input fields logic based on setupState and desiredEnabled */}
        {(desiredEnabled || (authEnabled && !desiredEnabled)) && (
          <div className="grid gap-4 md:grid-cols-2">
            {/* Show Current Password if we have one and we're either re-enabling or turning off */}
            {(setupState === 'password_retained' && desiredEnabled) || 
             (setupState === 'enabled' && !desiredEnabled) ? (
              <div className="space-y-3">
                <Input
                  label={t('settings.authCurrentPassword')}
                  type="password"
                  allowTogglePassword
                  iconType="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  autoComplete="current-password"
                  disabled={isSubmitting}
                  placeholder={t('settings.authPasswordPlaceholder')}
                  hint={setupState === 'password_retained' ? t('settings.authPasswordHintRetained') : t('settings.authPasswordHintOff')}
                />
              </div>
            ) : null}

            {/* Show New Password fields only during initial setup */}
            {setupState === 'no_password' && desiredEnabled ? (
              <>
                <div className="space-y-3">
                  <Input
                    label={t('settings.authSetPassword')}
                    type="password"
                    allowTogglePassword
                    iconType="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    disabled={isSubmitting}
                    placeholder={t('settings.authSetPasswordPlaceholder')}
                  />
                </div>
                <div className="space-y-3">
                  <Input
                    label={t('settings.changePasswordConfirm')}
                    type="password"
                    allowTogglePassword
                    iconType="password"
                    value={passwordConfirm}
                    onChange={(event) => setPasswordConfirm(event.target.value)}
                    autoComplete="new-password"
                    disabled={isSubmitting}
                    placeholder={t('settings.changePasswordConfirmPlaceholder')}
                  />
                </div>
              </>
            ) : null}
          </div>
        )}

        {error ? (
          isParsedApiError(error) ? (
            <SettingsAlert
              title={t('settings.authFailure')}
              message={error.message}
              variant="error"
            />
          ) : (
            <SettingsAlert title={t('settings.authFailure')} message={error} variant="error" />
          )
        ) : null}

        {successMessage ? (
          <SettingsAlert title={t('settings.actionSuccess')} message={successMessage} variant="success" />
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="settings-primary" isLoading={isSubmitting} disabled={!isDirty}>
            {targetActionLabel}
          </Button>
          <Button
            type="button"
            variant="settings-secondary"
            onClick={() => {
              setDesiredEnabled(authEnabled);
              setError(null);
              setSuccessMessage(null);
              resetForm();
            }}
            disabled={isSubmitting || !isDirty}
          >
            {t('settings.revert')}
          </Button>
        </div>
      </form>
    </SettingsSectionCard>
  );
};
