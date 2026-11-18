import { useEffect, useState } from 'react';
import { chatgptApi } from '../../api/chatgpt';
import { getParsedApiError } from '../../api/error';
import { useChatGPTStore } from '../../stores/chatgptStore';

const messages: Record<string, string> = {
  chatgpt_deployment_unsupported: '请从 macOS 本机源码启动 DSA，并使用 127.0.0.1 打开 Web。',
  chatgpt_store_unavailable: '本机 ChatGPT 凭据无法读取。请检查目录权限或关闭占用它的 DSA 进程。',
  chatgpt_admin_auth_required: '请先启用管理员认证并登录 DSA。',
  chatgpt_plan_permission_required: '已验证账号身份，请补充授予 ChatGPT 套餐使用权限。',
  chatgpt_reauthorization_required: '连接已失效，请重新授权。',
  chatgpt_consent_declined: '授权已取消，可以重新连接。',
  chatgpt_authorization_timeout: '授权超时，请重新连接。',
  chatgpt_invalid_identity: '返回的账号与已保存的注册不匹配。请用原账号重试，或选择其他账号。',
};

const disconnectStatusUnknown = '断开结果待确认。请刷新页面查看当前连接状态。';

export function ChatGPTConnectionCard() {
  const { status, models, model, error, refresh, selectModel, disconnect } = useChatGPTStore();
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!status?.pending) return;
    const timer = window.setInterval(() => { void refresh(); }, 1000);
    return () => window.clearInterval(timer);
  }, [refresh, status?.pending]);

  async function connect(newAccount = false) {
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      setNotice('浏览器阻止了授权窗口。允许弹窗后再试。');
      return;
    }
    tab.opener = null;
    setWorking(true);
    setNotice(null);
    try {
      const result = await chatgptApi.connect(newAccount, status?.error === 'chatgpt_plan_permission_required');
      tab.location.replace(result.authorization_url);
      await refresh();
    } catch (error) {
      tab.close();
      setNotice(getParsedApiError(error).message);
    } finally {
      setWorking(false);
    }
  }

  async function disconnectCurrent() {
    setWorking(true);
    setNotice(null);
    try {
      const confirmed = await disconnect();
      if (confirmed === undefined) setNotice(disconnectStatusUnknown);
      if (confirmed === false) setNotice('本地已断开原连接。请在 ChatGPT 设置中确认远端授权是否已撤销。');
    } catch (error) {
      setNotice(getParsedApiError(error).message);
    } finally {
      setWorking(false);
    }
  }

  const statusMessage = status?.error ? messages[status.error] || '授权未完成，请检查账号后重试。' : null;
  const button = 'rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm disabled:opacity-50';

  return (
    <section aria-labelledby="chatgpt-connection-title" className="space-y-3 border-t border-subtle pt-4">
      <h3 id="chatgpt-connection-title" className="text-sm font-semibold">ChatGPT 授权</h3>
      <p aria-live="polite" className="text-sm text-secondary-text">
        {notice === disconnectStatusUnknown ? null : status?.pending ? '请在 ChatGPT 页面完成授权。' : status?.connected
          ? `已授权 · ${status.account_label || 'ChatGPT'}`
          : statusMessage || (status?.available ? '连接后可在普通单股分析或问股中选择 ChatGPT。' : null)}
      </p>
      {status?.available && (
        <div className="flex flex-wrap items-center gap-2">
          {status.connected ? (
            <>
              <label className="flex flex-wrap items-center gap-2 text-sm">
                模型
                <select className="max-w-full rounded-lg border border-subtle bg-surface px-2 py-1.5" value={model} onChange={(event) => selectModel(event.target.value)}>
                  <option value="">选择模型</option>
                  {models.map(({ slug, display_name }) => <option key={slug} value={slug}>{display_name}</option>)}
                </select>
              </label>
              <button type="button" className={button} disabled={working} onClick={() => void refresh(true)}>刷新模型</button>
            </>
          ) : null}
          {status.connected || status.pending ? (
            <button type="button" className={button} disabled={working} onClick={() => void disconnectCurrent()}>
              {status.connected ? '断开连接' : '取消授权'}
            </button>
          ) : (
            <>
              <button type="button" className={button} disabled={working} onClick={() => void connect()}>
                {status.error === 'chatgpt_plan_permission_required' ? '补充授权' : status.account_label ? '重新授权' : 'Continue with ChatGPT'}
              </button>
              {status.account_label && <button type="button" className={button} disabled={working} onClick={() => void connect(true)}>连接其他账号</button>}
            </>
          )}
          <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer" className="text-sm underline">管理 ChatGPT 用量</a>
        </div>
      )}
      {(notice || error) && <p role="status" className="break-words text-sm text-secondary-text">{notice || error}</p>}
    </section>
  );
}
