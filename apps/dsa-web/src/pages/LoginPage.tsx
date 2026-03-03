import type React from 'react';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks';
import { SettingsAlert } from '../components/settings';

const LoginPage: React.FC = () => {
  const { login, passwordSet } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawRedirect = searchParams.get('redirect') ?? '';
  const redirect =
    rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';

  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFirstTime = !passwordSet;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (isFirstTime && password !== passwordConfirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await login(password, isFirstTime ? passwordConfirm : undefined);
      if (result.success) {
        navigate(redirect, { replace: true });
      } else {
        setError(result.error ?? '登录失败');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/8 bg-card/80 p-6 backdrop-blur-sm">
        <h1 className="mb-2 text-xl font-semibold text-white">
          {isFirstTime ? '设置初始密码' : '管理员登录'}
        </h1>
        <p className="mb-6 text-sm text-secondary">
          {isFirstTime
            ? '请设置管理员密码，输入两遍确认'
            : '请输入密码以继续访问'}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-secondary">
              {isFirstTime ? '新密码' : '密码'}
            </label>
            <input
              id="password"
              type="password"
              className="input-terminal"
              placeholder={isFirstTime ? '输入新密码' : '输入密码'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
              autoFocus
              autoComplete={isFirstTime ? 'new-password' : 'current-password'}
            />
          </div>

          {isFirstTime ? (
            <div>
              <label
                htmlFor="passwordConfirm"
                className="mb-1 block text-sm font-medium text-secondary"
              >
                确认密码
              </label>
              <input
                id="passwordConfirm"
                type="password"
                className="input-terminal"
                placeholder="再次输入密码"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                disabled={isSubmitting}
                autoComplete="new-password"
              />
            </div>
          ) : null}

          {error ? (
            <SettingsAlert
              title={isFirstTime ? '设置失败' : '登录失败'}
              message={error}
              variant="error"
              className="!mt-3"
            />
          ) : null}

          <button
            type="submit"
            className="btn-primary w-full"
            disabled={isSubmitting}
          >
            {isSubmitting ? (isFirstTime ? '设置中...' : '登录中...') : isFirstTime ? '设置密码' : '登录'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
