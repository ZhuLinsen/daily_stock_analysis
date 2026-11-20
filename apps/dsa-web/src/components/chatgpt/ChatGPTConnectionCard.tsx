import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { useEffect, useState } from 'react';
import { chatgptApi, type ConnectTarget } from '../../api/chatgpt';
import { isAxiosError } from 'axios';
import { extractErrorCode, getParsedApiError } from '../../api/error';
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
  const { t } = useUiLanguage();
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const disconnectRetryId = status?.disconnect_retry_connection_id;
  const disconnectConnectionId = status?.connection_id ?? disconnectRetryId;
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!status?.pending) return;
    const timer = window.setInterval(() => { void refresh(); }, 1000);
    return () => window.clearInterval(timer);
  }, [refresh, status?.pending]);

  async function connect(target?: ConnectTarget) {
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      setNotice('浏览器阻止了授权窗口。允许弹窗后再试。');
      return;
    }
    tab.opener = null;
    setWorking(true);
    setNotice(null);
    try {
      const result = await chatgptApi.connect(target);
      tab.location.replace(result.authorization_url);
      await refresh();
    } catch (error) {
      tab.close();
      const code = isAxiosError(error) && extractErrorCode(error.response?.data);
      if (code === 'chatgpt_target_changed' || code === 'chatgpt_connection_busy') await refresh();
      if (code !== 'chatgpt_connection_busy' || !useChatGPTStore.getState().status?.disconnect_retry_connection_id) {
        setNotice(getParsedApiError(error).message);
      }
    } finally {
      setWorking(false);
    }
  }

  async function disconnectCurrent() {
    setWorking(true);
    setNotice(null);
    try {
      const target = disconnectConnectionId ? { connection_id: disconnectConnectionId }
        : status?.attempt_id ? { attempt_id: status.attempt_id } : null;
      if (!target) return;
      const confirmed = await disconnect(target);
      if (confirmed === undefined && !useChatGPTStore.getState().status?.disconnect_retry_connection_id) {
        setNotice(disconnectStatusUnknown);
      }
      if (confirmed === false) setNotice('attempt_id' in target ? t('chat.cancelledLocally') : t('chat.disconnectedLocally'));
    } catch (error) {
      const code = isAxiosError(error) && extractErrorCode(error.response?.data);
      if (code === 'chatgpt_store_unavailable' && useChatGPTStore.getState().status?.disconnect_retry_connection_id) return;
      setNotice(code === 'chatgpt_target_changed' ? t('chat.chatGPTConnectionChanged') : getParsedApiError(error).message);
    } finally {
      setWorking(false);
    }
  }

  const retryId = status?.retry_id;
  const currentLabel = status?.accounts && status.accounts.length > 1
    ? `${status.account_label} (${status.registration_id})`
    : status?.account_label;
  const statusMessage = status?.error ? messages[status.error] || '授权未完成，请检查账号后重试。' : null;
  const button = 'rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm disabled:opacity-50';

  return (
    <section aria-labelledby="chatgpt-connection-title" className="space-y-3 border-t border-subtle pt-4">
      <h3 id="chatgpt-connection-title" className="text-sm font-semibold">ChatGPT 授权</h3>
      <p aria-live="polite" className="text-sm text-secondary-text">
        {disconnectRetryId ? t('chat.fixStorageBeforeRetryingDisconnect') : notice === disconnectStatusUnknown ? null : status?.cancelling ? t('chat.finishingAuthorization') : status?.pending ? '请在 ChatGPT 页面完成授权。' : status?.connected
          ? `已授权 · ${currentLabel || 'ChatGPT'}`
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
          {disconnectRetryId || status.connected || status.pending ? (
            <button type="button" className={button} disabled={working || status.cancelling} onClick={() => void disconnectCurrent()}>
              {disconnectRetryId ? t('chat.retryDisconnect') : status.connected ? '断开连接' : '取消授权'}
            </button>
          ) : (
            <>
              {retryId ? (
                <button type="button" className={button} disabled={working} onClick={() => void connect({ retry_id: retryId })}>
                  {t('chat.continueAuthorization')}
                </button>
              ) : (
                <button type="button" className={button} disabled={working}
                  onClick={() => void connect(status.registration_id ? { registration_id: status.registration_id } : undefined)}>
                  {status.error === 'chatgpt_plan_permission_required' ? '补充授权' : status.account_label ? '重新授权' : 'Continue with ChatGPT'}
                  {status.accounts && status.accounts.length > 1 && ` · ${currentLabel}`}
                </button>
              )}
              {status.accounts?.filter((entry) => status.retry_id || entry.id !== status.registration_id).map((entry) => (
                <button key={entry.id} type="button" className={button} disabled={working} onClick={() => void connect({ registration_id: entry.id })}>
                  {retryId
                    ? t('chat.abandonRetryForSavedAccount', { account: `${entry.label} (${entry.id})` })
                    : `${t('chat.savedAccount')} · ${entry.label} (${entry.id})`}
                </button>
              ))}
              {(status.retry_id || status.account_label) && (
                <button type="button" className={button} disabled={working} onClick={() => void connect()}>
                  {status.retry_id ? t('chat.restartAuthorization') : '连接其他账号'}
                </button>
              )}
            </>
          )}
          <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer" className="text-sm underline">管理 ChatGPT 用量</a>
        </div>
      )}
      {status?.revocation_unconfirmed && (
        <p role="status">{status.revocation_account_label
          ? t('chat.checkRemoteAccountAuthorization', { account: status.revocation_account_label })
          : t('chat.checkRemoteAuthorization')}</p>
      )}
      {(notice || error) && <p role="status" className="break-words text-sm text-secondary-text">{notice || error}</p>}
    </section>
  );
}
