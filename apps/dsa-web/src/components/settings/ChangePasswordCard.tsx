import type React from 'react';
import { useState } from 'react';
import { useAuth } from '../../hooks';
import { EyeToggleIcon } from '../common';
import { SettingsAlert } from './SettingsAlert';

export const ChangePasswordCard: React.FC = () => {
  const { changePassword } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (!currentPassword.trim()) {
      setError('请输入当前密码');
      return;
    }
    if (!newPassword.trim()) {
      setError('请输入新密码');
      return;
    }
    if (newPassword.length < 6) {
      setError('新密码至少 6 位');
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      setError('两次输入的新密码不一致');
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await changePassword(currentPassword, newPassword, newPasswordConfirm);
      if (result.success) {
        setSuccess(true);
        setCurrentPassword('');
        setNewPassword('');
        setNewPasswordConfirm('');
        setShowCurrent(false);
        setShowNew(false);
        setShowConfirm(false);
        setTimeout(() => setSuccess(false), 4000);
      } else {
        setError(result.error ?? '修改失败');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-white/8 bg-elevated/50 p-4">
      <div className="mb-2 flex items-center gap-2">
        <label className="text-sm font-semibold text-white">修改密码</label>
      </div>
      <p className="mb-3 text-xs text-muted">修改管理员登录密码</p>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label
            htmlFor="change-pass-current"
            className="mb-1 block text-xs font-medium text-secondary"
          >
            当前密码
          </label>
          <div className="flex items-center gap-2">
            <input
              id="change-pass-current"
              type={showCurrent ? 'text' : 'password'}
              className="input-terminal flex-1"
              placeholder="输入当前密码"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="current-password"
            />
            <button
              type="button"
              className="btn-secondary !p-2 shrink-0"
              disabled={isSubmitting}
              onClick={() => setShowCurrent((v) => !v)}
              title={showCurrent ? '隐藏' : '显示'}
              aria-label={showCurrent ? '隐藏密码' : '显示密码'}
            >
              <EyeToggleIcon visible={showCurrent} />
            </button>
          </div>
        </div>
        <div>
          <label
            htmlFor="change-pass-new"
            className="mb-1 block text-xs font-medium text-secondary"
          >
            新密码
          </label>
          <div className="flex items-center gap-2">
            <input
              id="change-pass-new"
              type={showNew ? 'text' : 'password'}
              className="input-terminal flex-1"
              placeholder="输入新密码（至少 6 位）"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="new-password"
            />
            <button
              type="button"
              className="btn-secondary !p-2 shrink-0"
              disabled={isSubmitting}
              onClick={() => setShowNew((v) => !v)}
              title={showNew ? '隐藏' : '显示'}
              aria-label={showNew ? '隐藏密码' : '显示密码'}
            >
              <EyeToggleIcon visible={showNew} />
            </button>
          </div>
        </div>
        <div>
          <label
            htmlFor="change-pass-confirm"
            className="mb-1 block text-xs font-medium text-secondary"
          >
            确认新密码
          </label>
          <div className="flex items-center gap-2">
            <input
              id="change-pass-confirm"
              type={showConfirm ? 'text' : 'password'}
              className="input-terminal flex-1"
              placeholder="再次输入新密码"
              value={newPasswordConfirm}
              onChange={(e) => setNewPasswordConfirm(e.target.value)}
              disabled={isSubmitting}
              autoComplete="new-password"
            />
            <button
              type="button"
              className="btn-secondary !p-2 shrink-0"
              disabled={isSubmitting}
              onClick={() => setShowConfirm((v) => !v)}
              title={showConfirm ? '隐藏' : '显示'}
              aria-label={showConfirm ? '隐藏密码' : '显示密码'}
            >
              <EyeToggleIcon visible={showConfirm} />
            </button>
          </div>
        </div>

        {error ? (
          <SettingsAlert title="修改失败" message={error} variant="error" className="!mt-3" />
        ) : null}
        {success ? (
          <p className="text-xs text-green-500">密码已修改成功</p>
        ) : null}

        <button
          type="submit"
          className="btn-primary mt-2"
          disabled={isSubmitting}
        >
          {isSubmitting ? '修改中...' : '修改'}
        </button>
      </form>
    </div>
  );
};
