import { useCallback, useEffect, useState } from 'react';

/**
 * TaskPanel 折叠态 localStorage key。
 *
 * issue #2115：用户希望任务面板可以折叠为一行摘要，刷新页面后保留偏好。
 * issue #2144 review blocker OR-COR-1fd4ac89：HomePage 同时挂载桌面侧栏与移动抽屉两个
 * TaskPanel 实例，单实例内部 useState 会在响应式切换后产生状态漂移，需要把折叠态
 * 提升到 HomePage 让两个实例共享同一来源。
 *
 * 这里把读写 localStorage 的逻辑抽成可复用 hook，HomePage 用它拿到 (collapsed,
 * setCollapsed) 注入到两实例的受控 props，避免每个实例各自维护 state。
 */
const TASK_PANEL_COLLAPSED_STORAGE_KEY = 'dsa.taskPanel.collapsed';

function readCollapsedFromStorage(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    return window.localStorage.getItem(TASK_PANEL_COLLAPSED_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsedToStorage(collapsed: boolean): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(TASK_PANEL_COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0');
  } catch {
    // Ignore storage failures; in-memory state still updates.
  }
}

export interface UseTaskPanelCollapsedResult {
  isCollapsed: boolean;
  toggleCollapsed: () => void;
  setCollapsed: (next: boolean) => void;
}

/**
 * 折叠态 hook：负责 lazy 读取 localStorage + 通过 useEffect 写回 + 暴露
 * toggleCollapsed / setCollapsed 给 TaskPanel 受控使用。
 *
 * 设计上只有一个 useState，保证 HomePage 在 sidebarContent useMemo 里调用本 hook
 * 时，两实例拿到的 collapsed 是同一份；setCollapsed 触发后 HomePage 重渲染，两个
 * TaskPanel 实例因 isCollapsed prop 变化同步切换。
 */
export function useTaskPanelCollapsed(): UseTaskPanelCollapsedResult {
  const [isCollapsed, setIsCollapsed] = useState<boolean>(readCollapsedFromStorage);

  useEffect(() => {
    writeCollapsedToStorage(isCollapsed);
  }, [isCollapsed]);

  const toggleCollapsed = useCallback(() => {
    setIsCollapsed((prev) => !prev);
  }, []);

  const setCollapsed = useCallback((next: boolean) => {
    setIsCollapsed(next);
  }, []);

  return { isCollapsed, toggleCollapsed, setCollapsed };
}

export const TASK_PANEL_COLLAPSED_STORAGE_KEY_FOR_TESTS =
  TASK_PANEL_COLLAPSED_STORAGE_KEY;
