import type React from 'react';
import { useEffect, useState } from 'react';
import { Menu } from 'lucide-react';
import { Outlet } from 'react-router-dom';
import { Drawer } from '../common/Drawer';
import { SidebarNav } from './SidebarNav';
import { DesktopUpdateIndicator } from './DesktopUpdateIndicator';
import { cn } from '../../utils/cn';
import { ThemeToggle } from '../theme/ThemeToggle';
import { UiLanguageToggle } from '../i18n/UiLanguageToggle';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

type ShellProps = {
  children?: React.ReactNode;
};

export const Shell: React.FC<ShellProps> = ({ children }) => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const collapsed = false;
  const { t } = useUiLanguage();

  useEffect(() => {
    if (!mobileOpen) {
      return undefined;
    }

    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        setMobileOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [mobileOpen]);

  return (
    <div className="app-shell min-h-screen bg-background text-foreground">
      <div className="pointer-events-none fixed inset-x-0 top-3 z-40 flex items-start justify-between px-3 lg:hidden">
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          className="tech-icon-button pointer-events-auto inline-flex h-10 w-10 items-center justify-center"

          aria-label={t('layout.openNav')}
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="pointer-events-auto ml-auto flex items-center gap-2">
          <DesktopUpdateIndicator />
          <div className="flex items-center gap-2 lg:hidden">
            <UiLanguageToggle />
            <ThemeToggle />
          </div>
        </div>
      </div>

      <div className="mx-auto flex min-h-screen w-full max-w-[1920px] gap-2.5 px-2 py-2 sm:px-3 sm:py-3 lg:gap-3">
        <aside
          className={cn(
            'app-sidebar sticky top-2 z-40 hidden shrink-0 overflow-hidden rounded-xl border border-[var(--shell-sidebar-border)] bg-card p-2 transition-[width] duration-200 lg:flex',
            'max-h-[calc(100vh-1rem)] self-start sm:top-3 sm:max-h-[calc(100vh-1.5rem)]',
            collapsed ? 'w-16' : 'w-40'
          )}
          aria-label={t('layout.desktopSidebar')}
        >
          <SidebarNav collapsed={collapsed} variant={collapsed ? 'rail' : 'default'} onNavigate={() => setMobileOpen(false)} />
        </aside>

        <main className="min-h-0 min-w-0 flex-1 pt-14 lg:pt-0 touch-pan-y">
          {children ?? <Outlet />}
        </main>
      </div>

      <Drawer
        isOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
        title={t('layout.navMenu')}
        width="max-w-xs"
        zIndex={90}
        side="left"
      >
        <SidebarNav onNavigate={() => setMobileOpen(false)} />
      </Drawer>
    </div>
  );
};
