import type React from 'react';
import { useState, useEffect } from 'react';
import { motion, useMotionValue, useTransform, useSpring } from "motion/react";
import { Lock, Loader2, Cpu, TrendingUp, Network, ShieldCheck } from "lucide-react";
import { Button, Input, ParticleBackground } from '../components/common';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ParsedApiError } from '../api/error';
import { isParsedApiError } from '../api/error';
import { useAuth } from '../hooks';
import { SettingsAlert } from '../components/settings';

const LoginPage: React.FC = () => {
  const { login, passwordSet, setupState } = useAuth();
  const navigate = useNavigate();

  // Set page title
  useEffect(() => {
    document.title = '登录 - DSA';
  }, []);
  const [searchParams] = useSearchParams();
  const rawRedirect = searchParams.get('redirect') ?? '';
  const redirect =
    rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';

  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(null);

  const isFirstTime = setupState === 'no_password' || !passwordSet;

  // 3D Tilt effect values
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  // Smooth out the mouse movement
  const smoothX = useSpring(mouseX, { damping: 30, stiffness: 200 });
  const smoothY = useSpring(mouseY, { damping: 30, stiffness: 200 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const x = e.clientX / window.innerWidth - 0.5;
      const y = e.clientY / window.innerHeight - 0.5;
      mouseX.set(x);
      mouseY.set(y);
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [mouseX, mouseY]);

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
    <div 
      style={{
        '--login-bg-main': 'hsl(222 84% 5%)',
        '--login-bg-card': 'hsl(222 34% 8%)',
        '--login-border-card': 'hsl(0 0% 100% / 0.05)',
        '--login-border-input': 'hsl(0 0% 100% / 0.1)',
        '--login-border-focus': 'hsl(var(--primary) / 0.5)',
        '--login-error-text': 'hsl(var(--destructive))',
        '--login-error-bg': 'hsl(var(--destructive) / 0.1)',
        '--login-error-border': 'hsl(var(--destructive) / 0.2)',
        '--login-text-primary': 'hsl(0 0% 100%)',
        '--login-text-secondary': 'hsl(215 20% 65%)',
        '--login-text-muted': 'hsl(215 16% 45%)',
        '--login-accent-soft': 'hsl(var(--primary) / 0.08)',
        '--login-accent-border': 'hsl(var(--primary) / 0.28)',
        '--login-accent-text': 'hsl(var(--primary) / 0.92)',
        '--login-accent-glow': 'hsl(var(--primary) / 0.2)',
        '--login-brand-start': 'hsl(var(--primary))',
        '--login-brand-end': 'hsl(214 100% 62%)',
        '--login-brand-button-start': 'hsl(194 96% 45%)',
        '--login-brand-button-end': 'hsl(214 100% 56%)',
        '--login-brand-button-start-hover': 'hsl(194 96% 50%)',
        '--login-brand-button-end-hover': 'hsl(214 100% 62%)',
        '--login-grid-line': 'hsl(0 0% 50% / 0.04)',
        '--login-grid-mask': 'radial-gradient(ellipse 80% 50% at 50% 50%, #000 70%, transparent 100%)',
      } as React.CSSProperties}
      className="relative flex min-h-screen flex-col justify-center overflow-hidden bg-[var(--login-bg-main)] py-12 font-sans selection:bg-[var(--login-accent-soft)] sm:px-6 lg:px-8 [perspective:1500px]"
    >
      {/* Dynamic Background */}
      <ParticleBackground />

      {/* Cyber Grid */}
      <div className="absolute inset-0 z-0 bg-[linear-gradient(to_right,var(--login-grid-line)_1px,transparent_1px),linear-gradient(to_bottom,var(--login-grid-line)_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:var(--login-grid-mask)]" />

      {/* Parallax Glowing Orbs */}
      <motion.div
        style={{
          x: useTransform(smoothX, [-0.5, 0.5], [-50, 50]),
          y: useTransform(smoothY, [-0.5, 0.5], [-50, 50]),
        }}
        className="absolute left-[20%] top-[20%] -z-10 h-[300px] w-[300px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--login-accent-glow)] blur-[100px]"
      />
      <motion.div
        style={{
          x: useTransform(smoothX, [-0.5, 0.5], [60, -60]),
          y: useTransform(smoothY, [-0.5, 0.5], [60, -60]),
        }}
        className="absolute right-[20%] bottom-[10%] -z-10 h-[400px] w-[400px] translate-x-1/2 translate-y-1/2 rounded-full bg-emerald-600/10 blur-[120px]"
      />

      <div className="sm:mx-auto sm:w-full sm:max-w-md relative z-10">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="flex flex-col items-center justify-center mb-10 relative"
        >
          {/* Immersive Full-Height Background Logo */}
          <motion.div
            style={{
              x: useTransform(smoothX, [-0.5, 0.5], [-8, 8]),
              y: useTransform(smoothY, [-0.5, 0.5], [-8, 8]),
              rotate: useTransform(smoothX, [-0.5, 0.5], [-0.5, 0.5]),
            }}
            className="pointer-events-none absolute -top-[20vh] -z-10 opacity-80"
          >
            <div className="relative flex h-[120vh] w-[120vh] items-center justify-center rounded-full border border-[var(--login-accent-soft)] bg-gradient-to-br from-[var(--login-accent-soft)] to-[hsl(214_100%_20%_/_0.18)] shadow-[inset_0_0_200px_var(--login-accent-glow)] blur-[4px]">
              <Cpu className="h-[70vh] w-[70vh] text-[hsl(200_80%_22%_/_0.4)] brightness-50" />
              <TrendingUp className="absolute h-[25vh] w-[25vh] translate-x-[15vh] translate-y-[15vh] text-emerald-900/30 brightness-50" />
            </div>
          </motion.div>

          <div className="mt-8 flex flex-col items-center">
            <h2 className="text-4xl font-extrabold tracking-tighter text-[var(--login-text-primary)] sm:text-6xl">
              <span className="bg-gradient-to-r from-[var(--login-text-primary)] via-[var(--login-text-primary)] to-[var(--login-text-secondary)] bg-clip-text text-transparent">DAILY </span>
              <span className="bg-gradient-to-r from-[var(--login-brand-start)] to-[var(--login-brand-end)] bg-clip-text text-transparent drop-shadow-[0_0_20px_var(--login-accent-glow)]">STOCK</span>
            </h2>
            <h3 className="mt-1 text-xl font-bold uppercase tracking-[0.5em] text-[var(--login-text-muted)]">
              Analysis Engine
            </h3>
          </div>

          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="mt-6 flex items-center gap-2 rounded-full border border-[var(--login-accent-border)] bg-[var(--login-accent-soft)] px-3 py-1 text-[10px] font-medium text-[var(--login-accent-text)] backdrop-blur-sm"
          >
            <Network className="h-3 w-3" />
            <span>V3.X QUANTITATIVE SYSTEM</span>
          </motion.div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="relative group z-20 pointer-events-auto"
        >
          {/* Card Border Glow */}
          <div className="pointer-events-none absolute -inset-0.5 rounded-3xl bg-gradient-to-b from-[var(--login-accent-glow)] to-[hsl(214_100%_56%_/_0.18)] opacity-50 blur-sm transition duration-1000 group-hover:opacity-100 group-hover:duration-200" />

          <div className="pointer-events-auto relative flex flex-col overflow-hidden rounded-3xl border border-[var(--login-border-card)] bg-[var(--login-bg-card)]/80 p-8 shadow-2xl backdrop-blur-xl">
            {/* Inner corner glow */}
            <div className="absolute -right-20 -top-20 h-40 w-40 rounded-full bg-[var(--login-accent-soft)] blur-[50px]" />
            <div className="absolute -bottom-20 -left-20 h-40 w-40 rounded-full bg-blue-600/10 blur-[50px]" />

            <div className="mb-8">
              <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-[var(--login-text-primary)]">
                {isFirstTime ? (
                  <>
                    <ShieldCheck className="h-6 w-6 text-emerald-400" />
                    <span>设置初始密码</span>
                  </>
                ) : (
                  <>
                    <Lock className="h-5 w-5 text-[var(--login-accent-text)]" />
                    <span>管理员登录</span>
                  </>
                )}
              </h1>
              <p className="mt-2 text-sm text-[var(--login-text-secondary)]">
                {isFirstTime
                  ? '首次启用认证，请为系统工作台设置管理员密码。'
                  : '访问 DSA 量化决策引擎需要有效的身份凭证。'}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-4">
                <Input
                  id="password"
                  type="password"
                  allowTogglePassword
                  iconType="password"
                  label={isFirstTime ? '管理员密码' : '登录密码'}
                  placeholder={isFirstTime ? '请设置 6 位以上密码' : '请输入密码'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isSubmitting}
                  autoFocus
                  autoComplete={isFirstTime ? 'new-password' : 'current-password'}
                  className="!bg-[var(--login-border-card)] !border-[var(--login-border-input)] focus:!border-[var(--login-border-focus)]"
                />

                {isFirstTime && (
                  <Input
                    id="passwordConfirm"
                    type="password"
                    allowTogglePassword
                    iconType="password"
                    label="确认密码"
                    placeholder="再次确认管理员密码"
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    disabled={isSubmitting}
                    autoComplete="new-password"
                    className="!bg-[var(--login-border-card)] !border-[var(--login-border-input)] focus:!border-[var(--login-border-focus)]"
                  />
                )}
              </div>

              {error && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="overflow-hidden"
                >
                  <SettingsAlert
                    title={isFirstTime ? '配置失败' : '验证未通过'}
                    message={isParsedApiError(error) ? error.message : error}
                    variant="error"
                    className="!border-[var(--login-error-border)] !bg-[var(--login-error-bg)] !text-[var(--login-error-text)]"
                  />
                </motion.div>
              )}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                className="group/btn relative h-12 w-full overflow-hidden rounded-xl border-0 bg-gradient-to-r from-[var(--login-brand-button-start)] to-[var(--login-brand-button-end)] font-medium text-foreground shadow-lg shadow-[0_18px_36px_hsl(214_100%_8%_/_0.24)] hover:from-[var(--login-brand-button-start-hover)] hover:to-[var(--login-brand-button-end-hover)]"
                disabled={isSubmitting}
              >
                <div className="relative z-10 flex items-center justify-center gap-2">
                  {isSubmitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      <span>{isFirstTime ? '初始化中...' : '正在建立连接...'}</span>
                    </>
                  ) : (
                    <span>{isFirstTime ? '完成设置并登录' : '授权进入工作台'}</span>
                  )}
                </div>
                <div className="absolute inset-0 z-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite] pointer-events-none" />
              </Button>
            </form>
          </div>
        </motion.div>

        {/* Footer info */}
        <motion.p 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="mt-8 text-center font-mono text-xs uppercase tracking-wider text-[var(--login-text-muted)]"
        >
          Secure Connection Established via DSA-V3-TLS
        </motion.p>
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes shimmer {
          100% {
            transform: translateX(100%);
          }
        }
      `}} />
    </div>
  );
};

export default LoginPage;
