import { useEffect } from 'react';
// react-router-dom 7.13+ — useBlocker 已稳定, useBeforeUnload 保留。
// 我们从 'react-router-dom' 直接 import,避免分两个包管理。
import { useBlocker, useBeforeUnload } from 'react-router-dom';

/**
 * useUnsavedChangesGuard — 用于"已修改但未保存"场景的离开拦截 hook。
 *
 * 解决 issue #1948: SettingsPage 需要在有未保存修改时拦截两类离开操作:
 *   1. 浏览器刷新 / 关闭标签页 / 关闭窗口 — 用 beforeunload 事件(window-level)。
 *   2. 站内路由离开当前 /settings → 其他路由 — 用 react-router useBlocker。
 *
 * ZhuLinsen 2026-07-21 第 4 条契约要求:
 *   - 拦截只在 hasDirty === true 时生效,保存/重置后立即解除,避免残留提示。
 *   - 明确区分 beforeunload(浏览器退出)与 useBlocker(站内路由)两类场景。
 *
 * 实现策略:
 *   - beforeunload: useEffect 注册 window 事件监听, hasDirty=false 时 noop。
 *   - useBlocker: 直接传入 boolean shouldBlock = hasDirty (API 接受 boolean 或
 *     BlockerFunction)。react-router 在路由变化时会触发 blocker,UI 上由调用方
 *     渲染 confirm 对话框,通过 blocker.reset()/proceed() 控制行为。
 *
 * @param hasDirty 当前页面是否持有未保存修改 (boolean)。
 * @param ConfirmDialog 由调用方提供的 confirm 对话框组件,接收 blocker 实例。
 *   在 blocker.state === 'blocked' 时渲染,内部提供"留在此页"和"离开"两个按钮,
 *   分别调用 blocker.reset() 与 blocker.proceed()。也可以不传,默认用 window.confirm。
 *
 * @returns { blocker } — 当前 blocker 实例 (即使 hasDirty=false 也会返回一个),调用方
 *   可根据 blocker.state 渲染自定义 UI。
 */
export interface UseUnsavedChangesGuardOptions {
  hasDirty: boolean;
}

export interface UseUnsavedChangesGuardResult {
  /** react-router blocker 实例 (始终存在, hasDirty=false 时 state='unblocked')。 */
  blocker: ReturnType<typeof useBlocker>;
  /** blocker 当前是否处于 'blocked' 状态 (即用户尝试离开且尚未响应)。 */
  isBlocking: boolean;
}

export const useUnsavedChangesGuard = (
  options: UseUnsavedChangesGuardOptions,
): UseUnsavedChangesGuardResult => {
  const { hasDirty } = options;

  // beforeunload — 浏览器级别刷新/关闭标签页拦截。只在 hasDirty 真时加,假时移除,
  // 避免保存成功的页面残留 beforeunload 监听导致误弹。
  useBeforeUnload(
    (event: BeforeUnloadEvent) => {
      if (hasDirty) {
        // 浏览器规范: preventDefault + returnValue 必须设置才会弹原生 confirm。
        event.preventDefault();
        event.returnValue = '';
      }
    },
    { capture: true },
  );

  // useBlocker — 站内路由离开拦截。React-router 7 useBlocker 接受 boolean
  // 或 BlockerFunction。这里我们用 boolean 简化:hasDirty=true 时所有站内跳转都拦截。
  // 想做更精细的判断 (例如允许同 /settings 内的 sub-route 切换) 可改成 BlockerFunction
  // 但 SettingsPage 内部用 activeCategory (state) 切分类不算路由变化,不需要细粒度判断。
  const blocker = useBlocker(hasDirty);

  // 额外的保守 belt-and-suspenders: hasDirty 转 false 时强制 reset blocker,
  // 防止某些 React fiber 顺序导致 blocker.state 仍停留在 'blocked' 的边界情形。
  // 这等价于"保存成功 / 重置后立即解除拦截"的契约要求。
  useEffect(() => {
    if (!hasDirty && blocker.state === 'blocked') {
      blocker.reset();
    }
  }, [hasDirty, blocker]);

  return {
    blocker,
    isBlocking: blocker.state === 'blocked',
  };
};
