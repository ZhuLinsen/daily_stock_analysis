import { fireEvent, render, screen } from '@testing-library/react';
import { lazy } from 'react';
import type React from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { RouteOutletBoundary } from '../RouteBoundary';
import { Shell } from '../Shell';
import { attemptRouteChunkRecovery } from '../routeChunkRecovery';

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    authEnabled: false,
    logout: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock('../../../stores/agentChatStore', () => {
  const state = { completionBadge: false };

  return {
    useAgentChatStore: (selector?: (value: typeof state) => unknown) => (
      selector ? selector(state) : state
    ),
  };
});

describe('RouteOutletBoundary', () => {
  it('reloads once for a stale lazy-route chunk and suppresses a reload loop', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    const reload = vi.fn();
    const error = new TypeError(
      'Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/ChatPage-old.js',
    );

    expect(attemptRouteChunkRecovery(error, { storage, reload })).toBe(true);
    expect(attemptRouteChunkRecovery(error, { storage, reload })).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload for ordinary render errors', () => {
    const reload = vi.fn();
    expect(attemptRouteChunkRecovery(new Error('render failed'), {
      storage: { getItem: () => null, setItem: vi.fn() },
      reload,
    })).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('catches rejected lazy route imports inside the shell and resets on navigation', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const BrokenLazyRoute = lazy(() => (
      Promise.reject(new Error('chunk load failed')) as Promise<{ default: React.ComponentType }>
    ));

    try {
      render(
        <MemoryRouter initialEntries={['/chat']}>
          <Routes>
            <Route
              element={(
                <Shell>
                  <RouteOutletBoundary />
                </Shell>
              )}
            >
              <Route path="/chat" element={<BrokenLazyRoute />} />
              <Route path="/portfolio" element={<div data-testid="portfolio-page">Portfolio</div>} />
            </Route>
          </Routes>
        </MemoryRouter>,
      );

      expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument();
      expect(await screen.findByRole('heading', { name: '页面加载失败' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '重新加载页面' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '返回首页' })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('link', { name: '持仓' }));

      expect(await screen.findByTestId('portfolio-page')).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: '页面加载失败' })).not.toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });
});
