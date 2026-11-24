import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ParsedApiError } from '../../api/error';
import { isParsedApiError } from '../../api/error';
import { useAuth } from '../../hooks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Button, Input } from '../common';
import { SettingsAlert } from './SettingsAlert';
import { SettingsSectionCard } from './SettingsSectionCard';

export const ChangePasswordCard: React.FC = () => {
  const { changePassword } = useAuth();
  const { t } = useUiLanguage();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(null);
  const [success, setSuccess] = useState(false);
  const mountedRef = useRef(true);
  const submittingRef = useRef(false);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearSuccessTimer = useCallback(() => {
    if (successTimerRef.current !== null) {
      clearTimeout(successTimerRef.current);
      successTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearSuccessTimer();
    };
  }, [clearSuccessTimer]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || submittingRef.current) return;
    clearSuccessTimer();
    setError(null);
    setSuccess(false);

    if (!currentPassword.trim()) {
      setError(t('settings.changePasswordRequiredCurrent'));
      return;
    }
    if (!newPassword.trim()) {
      setError(t('settings.changePasswordRequiredNew'));
      return;
    }
    if (newPassword.length < 6) {
      setError(t('settings.changePasswordShort'));
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      setError(t('login.passwordMismatch'));
      return;
    }

    submittingRef.current = true;
    setIsSubmitting(true);
    try {
      const result = await changePassword(currentPassword, newPassword, newPasswordConfirm);
      if (!mountedRef.current) return;
      if (result.success) {
        setSuccess(true);
        setCurrentPassword('');
        setNewPassword('');
        setNewPasswordConfirm('');
        clearSuccessTimer();
        successTimerRef.current = setTimeout(() => {
          successTimerRef.current = null;
          if (mountedRef.current) {
            setSuccess(false);
          }
        }, 4000);
      } else {
        setError(result.error ?? t('settings.changePasswordFailure'));
      }
    } finally {
      submittingRef.current = false;
      if (mountedRef.current) {
        setIsSubmitting(false);
      }
    }
  };

  return (
    <SettingsSectionCard
      title={t('settings.changePasswordTitle')}
      description={t('settings.changePasswordDescription')}
    >
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <Input
              id="change-pass-current"
              type="password"
              allowTogglePassword
              iconType="password"
              label={t('settings.changePasswordCurrent')}
              placeholder={t('settings.changePasswordCurrentPlaceholder')}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="current-password"
            />
          </div>

          <div className="space-y-3">
            <Input
              id="change-pass-new"
              type="password"
              allowTogglePassword
              iconType="password"
              label={t('settings.changePasswordNew')}
              hint={t('settings.changePasswordNewHint')}
              placeholder={t('settings.changePasswordNewPlaceholder')}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="new-password"
            />
          </div>
        </div>

        <div className="space-y-3 md:max-w-md">
          <Input
            id="change-pass-confirm"
            type="password"
            allowTogglePassword
            iconType="password"
            label={t('settings.changePasswordConfirm')}
            placeholder={t('settings.changePasswordConfirmPlaceholder')}
            value={newPasswordConfirm}
            onChange={(e) => setNewPasswordConfirm(e.target.value)}
            disabled={isSubmitting}
            autoComplete="new-password"
          />
        </div>

        {error
          ? isParsedApiError(error)
            ? <SettingsAlert title={t('settings.changePasswordFailure')} message={error.message} variant="error" className="!mt-3" />
            : <SettingsAlert title={t('settings.changePasswordFailure')} message={error} variant="error" className="!mt-3" />
          : null}
        {success ? (
          <SettingsAlert title={t('settings.changePasswordSuccess')} message={t('settings.changePasswordSuccessMessage')} variant="success" />
        ) : null}

        <Button type="submit" variant="primary" isLoading={isSubmitting}>
          {t('settings.changePasswordSave')}
        </Button>
      </form>
    </SettingsSectionCard>
  );
};
