import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BellRing } from 'lucide-react';
import { alertsApi } from '../api/alerts';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { AlertRuleForm } from '../components/alerts/AlertRuleForm';
import {
  AlertRuleList,
  type AlertRuleBusyState,
  type AlertRuleEnabledFilter,
  type AlertTypeFilter,
} from '../components/alerts/AlertRuleList';
import { AlertTriggerHistory } from '../components/alerts/AlertTriggerHistory';
import { ApiErrorAlert, AppPage, Card, EmptyState, InlineAlert, Loading, PageHeader } from '../components/common';
import type {
  AlertNotificationItem,
  AlertRuleCreateRequest,
  AlertRuleItem,
  AlertRuleTestResponse,
  AlertTriggerItem,
  AlertType,
} from '../types/alerts';
import { formatDateTime } from '../utils/format';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiLanguage } from '../i18n/uiText';

const PAGE_SIZE = 20;

function enabledFilterToQuery(value: AlertRuleEnabledFilter): boolean | undefined {
  if (value === 'enabled') return true;
  if (value === 'disabled') return false;
  return undefined;
}

function alertTypeFilterToQuery(value: AlertTypeFilter): AlertType | undefined {
  return value === 'all' ? undefined : value;
}

function testVariant(result: AlertRuleTestResponse): 'success' | 'warning' | 'danger' {
  if (result.status === 'evaluation_error') return 'danger';
  return result.triggered ? 'success' : 'warning';
}

const TEXT: Record<UiLanguage, {
  documentTitle: string;
  eyebrow: string;
  title: string;
  description: string;
  createSuccess: string;
  createdRule: (name: string) => string;
  close: string;
  testResult: string;
  testStatus: string;
  testTriggered: string;
  testObserved: string;
  yes: string;
  no: string;
  evaluated: string;
  triggered: string;
  degraded: string;
  skipped: string;
  notificationTitle: string;
  notificationSubtitle: string;
  loadingNotifications: string;
  emptyNotifications: string;
  emptyNotificationsDescription: string;
  notificationHeaders: string[];
  channels: Record<string, string>;
  notificationStatus: Record<string, string>;
  statusLabels: Record<string, string>;
}> = {
  ko: {
    documentTitle: '알림 센터 - DSA', eyebrow: 'ALERT CENTER', title: '알림 센터',
    description: '이벤트 알림, 일봉 기술 지표, 관심종목, 보유 종목·계좌 연동 및 시장 신호 규칙을 관리하고, 일회성 테스트와 백그라운드 평가 이력을 확인합니다.',
    createSuccess: '생성 완료', createdRule: (name) => `알림 규칙 「${name}」을(를) 만들었습니다.`, close: '닫기',
    testResult: '테스트 결과', testStatus: '상태', testTriggered: '트리거', testObserved: '관측값',
    yes: '예', no: '아니요', evaluated: '평가', triggered: '트리거', degraded: '강등', skipped: '건너뜀',
    notificationTitle: '알림 전송 이력', notificationSubtitle: '알림 결과', loadingNotifications: '알림 전송 이력 불러오는 중',
    emptyNotifications: '알림 전송 이력 없음', emptyNotificationsDescription: '표시할 알림 전송 상세가 없습니다. 알림이 트리거되면 설정된 채널로 계속 전송됩니다.',
    notificationHeaders: ['채널', '상태', '오류 코드', '소요 시간', '시각', '진단'],
    channels: { __cooldown__: '업무 쿨다운', __cooldown_read_failed__: '쿨다운 읽기 실패', __noise_suppressed__: '알림 노이즈 억제', __no_channel__: '사용 가능한 채널 없음', __dispatch__: '알림 디스패치', __context__: '세션 채널' },
    notificationStatus: { success: '성공', cooldown_active: '쿨다운으로 억제됨', cooldown_read_failed: '쿨다운 읽기 실패', noise_suppressed: '노이즈 억제됨', no_channel: '채널 없음', failed: '실패' },
    statusLabels: { evaluation_error: '평가 오류', triggered: '트리거됨', skipped: '건너뜀', degraded: '강등', failed: '실패' },
  },
  en: {
    documentTitle: 'Alert Center - DSA', eyebrow: 'ALERT CENTER', title: 'Alert Center',
    description: 'Manage event alerts, daily technical indicators, watchlist and portfolio/account rules, run one-off tests, and review background evaluation history.',
    createSuccess: 'Created', createdRule: (name) => `Created alert rule “${name}”.`, close: 'Close',
    testResult: 'Test result', testStatus: 'Status', testTriggered: 'Triggered', testObserved: 'Observed value',
    yes: 'Yes', no: 'No', evaluated: 'Evaluated', triggered: 'Triggered', degraded: 'Degraded', skipped: 'Skipped',
    notificationTitle: 'Notification attempts', notificationSubtitle: 'Notification results', loadingNotifications: 'Loading notification attempts',
    emptyNotifications: 'No notification attempts', emptyNotificationsDescription: 'There are no notification attempt details to show. Triggered alerts will still use configured channels.',
    notificationHeaders: ['Channel', 'Status', 'Error code', 'Duration', 'Time', 'Diagnostics'],
    channels: { __cooldown__: 'Business cooldown', __cooldown_read_failed__: 'Cooldown read failed', __noise_suppressed__: 'Notification noise suppressed', __no_channel__: 'No available channel', __dispatch__: 'Notification dispatch', __context__: 'Session channel' },
    notificationStatus: { success: 'Success', cooldown_active: 'Suppressed by cooldown', cooldown_read_failed: 'Cooldown read failed', noise_suppressed: 'Noise suppressed', no_channel: 'No channel', failed: 'Failed' },
    statusLabels: { evaluation_error: 'Evaluation error', triggered: 'Triggered', skipped: 'Skipped', degraded: 'Degraded', failed: 'Failed' },
  },
  zh: {
    documentTitle: '告警中心 - DSA', eyebrow: 'Alert Center', title: '告警中心',
    description: '管理事件告警、日线技术指标、自选股、持仓/账户联动和大盘红绿灯规则，执行一次性测试，并查看后台评估任务记录的触发历史。',
    createSuccess: '创建成功', createdRule: (name) => `已创建告警规则「${name}」`, close: '关闭',
    testResult: '测试结果', testStatus: '状态', testTriggered: '触发', testObserved: '观察值',
    yes: '是', no: '否', evaluated: '评估', triggered: '触发', degraded: '降级', skipped: '跳过',
    notificationTitle: '通知尝试记录', notificationSubtitle: '通知结果', loadingNotifications: '正在加载通知尝试记录',
    emptyNotifications: '暂无通知尝试记录', emptyNotificationsDescription: '当前没有可展示的通知尝试明细；告警触发仍会按已配置通知渠道发送。',
    notificationHeaders: ['渠道', '状态', '错误码', '耗时', '时间', '诊断'],
    channels: { __cooldown__: '业务冷却', __cooldown_read_failed__: '冷却读取失败', __noise_suppressed__: '通知降噪', __no_channel__: '无可用渠道', __dispatch__: '通知调度', __context__: '会话渠道' },
    notificationStatus: { success: '成功', cooldown_active: '冷却抑制', cooldown_read_failed: '冷却读取失败', noise_suppressed: '降噪抑制', no_channel: '无渠道', failed: '失败' },
    statusLabels: { evaluation_error: '评估错误', triggered: '已触发', skipped: '已跳过', degraded: '降级', failed: '失败' },
  },
};

function renderTestResultMessage(result: AlertRuleTestResponse, language: UiLanguage): React.ReactNode {
  const text = TEXT[language];
  const targetResults = result.targetResults ?? [];
  return (
    <div className="space-y-2">
      <div>
        {result.message}
        {` · ${text.testStatus}: `}
        {text.statusLabels[result.status] ?? result.status}
        {` · ${text.testTriggered}: `}
        {result.triggered ? text.yes : text.no}
        {` · ${text.testObserved}: `}
        {result.observedValue == null ? '--' : String(result.observedValue)}
      </div>
      {result.evaluatedCount != null && result.evaluatedCount > 1 ? (
        <div className="text-xs">
          {text.evaluated} {result.evaluatedCount} · {text.triggered} {result.triggeredCount ?? 0} · {text.degraded} {result.degradedCount ?? 0} · {text.skipped} {result.skippedCount ?? 0}
        </div>
      ) : null}
      {targetResults.length > 1 ? (
        <div className="grid gap-1 text-xs">
          {targetResults.slice(0, 20).map((item) => (
            <div key={`${item.target}-${item.status}`} className="flex flex-wrap justify-between gap-2">
              <span>{item.displayTarget ?? item.target}</span>
              <span>
                {text.statusLabels[item.status] ?? item.status}
                {item.recordStatus ? ` / ${text.statusLabels[item.recordStatus] ?? item.recordStatus}` : ''}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function formatNotificationChannel(channel: string, language: UiLanguage): string {
  return TEXT[language].channels[channel] ?? channel;
}

function formatNotificationStatus(notification: AlertNotificationItem, language: UiLanguage): string {
  const labels = TEXT[language].notificationStatus;
  if (notification.success) return labels.success;
  if (notification.errorCode === 'cooldown_active') return labels.cooldown_active;
  if (notification.errorCode === 'cooldown_read_failed') return labels.cooldown_read_failed;
  if (notification.errorCode === 'noise_suppressed') return labels.noise_suppressed;
  if (notification.errorCode === 'no_channel') return labels.no_channel;
  return labels.failed;
}

const AlertsPage: React.FC = () => {
  const { language } = useUiLanguage();
  const text = TEXT[language];
  useEffect(() => {
    document.title = text.documentTitle;
  }, [text.documentTitle]);

  const [rules, setRules] = useState<AlertRuleItem[]>([]);
  const [rulesTotal, setRulesTotal] = useState(0);
  const [rulesPage, setRulesPage] = useState(1);
  const [enabledFilter, setEnabledFilter] = useState<AlertRuleEnabledFilter>('all');
  const [alertTypeFilter, setAlertTypeFilter] = useState<AlertTypeFilter>('all');
  const [rulesLoading, setRulesLoading] = useState(false);
  const [rulesError, setRulesError] = useState<ParsedApiError | null>(null);
  const [rulesLoaded, setRulesLoaded] = useState(false);

  const [triggers, setTriggers] = useState<AlertTriggerItem[]>([]);
  const [triggersLoading, setTriggersLoading] = useState(false);
  const [triggersError, setTriggersError] = useState<ParsedApiError | null>(null);

  const [notifications, setNotifications] = useState<AlertNotificationItem[]>([]);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsError, setNotificationsError] = useState<ParsedApiError | null>(null);

  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<ParsedApiError | null>(null);
  const [createSuccess, setCreateSuccess] = useState<string | null>(null);
  const [busyRule, setBusyRule] = useState<AlertRuleBusyState | null>(null);
  const [testResult, setTestResult] = useState<AlertRuleTestResponse | null>(null);
  const rulesRequestIdRef = useRef(0);

  const loadRules = useCallback(async (pageOverride?: number) => {
    const requestId = rulesRequestIdRef.current + 1;
    rulesRequestIdRef.current = requestId;
    const isLatestRequest = () => rulesRequestIdRef.current === requestId;
    const requestedPage = pageOverride ?? rulesPage;
    const baseQuery = {
      enabled: enabledFilterToQuery(enabledFilter),
      alertType: alertTypeFilterToQuery(alertTypeFilter),
      pageSize: PAGE_SIZE,
    };
    setRulesLoading(true);
    try {
      let response = await alertsApi.listRules({ ...baseQuery, page: requestedPage });
      if (!isLatestRequest()) return null;
      const lastPage = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
      if (response.items.length === 0 && response.total > 0 && requestedPage > lastPage) {
        setRulesPage(lastPage);
        response = await alertsApi.listRules({ ...baseQuery, page: lastPage });
        if (!isLatestRequest()) return null;
      } else if (pageOverride !== undefined && pageOverride !== rulesPage) {
        setRulesPage(pageOverride);
      }
      setRules(response.items);
      setRulesTotal(response.total);
      setRulesError(null);
      setRulesLoaded(true);
      return response;
    } catch (error) {
      if (!isLatestRequest()) return null;
      setRulesError(getParsedApiError(error));
      return null;
    } finally {
      if (isLatestRequest()) {
        setRulesLoading(false);
      }
    }
  }, [alertTypeFilter, enabledFilter, rulesPage]);

  const loadTriggers = useCallback(async () => {
    setTriggersLoading(true);
    try {
      const response = await alertsApi.listTriggers({ page: 1, pageSize: PAGE_SIZE });
      setTriggers(response.items);
      setTriggersError(null);
    } catch (error) {
      setTriggersError(getParsedApiError(error));
    } finally {
      setTriggersLoading(false);
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    setNotificationsLoading(true);
    try {
      const response = await alertsApi.listNotifications({ page: 1, pageSize: PAGE_SIZE });
      setNotifications(response.items);
      setNotificationsError(null);
    } catch (error) {
      setNotificationsError(getParsedApiError(error));
    } finally {
      setNotificationsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  useEffect(() => {
    if (!rulesLoaded) return;
    void loadTriggers();
    void loadNotifications();
  }, [loadNotifications, loadTriggers, rulesLoaded]);

  const handleCreateRule = async (payload: AlertRuleCreateRequest) => {
    setCreateLoading(true);
    setCreateError(null);
    setCreateSuccess(null);
    try {
      const created = await alertsApi.createRule(payload);
      setCreateSuccess(text.createdRule(created.name));
      await loadRules(1);
      return true;
    } catch (error) {
      setCreateError(getParsedApiError(error));
      return false;
    } finally {
      setCreateLoading(false);
    }
  };

  const handleToggleEnabled = async (rule: AlertRuleItem) => {
    setBusyRule({ id: rule.id, action: 'toggle' });
    try {
      if (rule.enabled) {
        await alertsApi.disableRule(rule.id);
      } else {
        await alertsApi.enableRule(rule.id);
      }
      await loadRules();
    } catch (error) {
      setRulesError(getParsedApiError(error));
    } finally {
      setBusyRule(null);
    }
  };

  const handleDeleteRule = async (rule: AlertRuleItem) => {
    setBusyRule({ id: rule.id, action: 'delete' });
    try {
      await alertsApi.deleteRule(rule.id);
      await loadRules();
    } catch (error) {
      setRulesError(getParsedApiError(error));
    } finally {
      setBusyRule(null);
    }
  };

  const handleTestRule = async (rule: AlertRuleItem) => {
    setBusyRule({ id: rule.id, action: 'test' });
    setTestResult(null);
    try {
      const result = await alertsApi.testRule(rule.id);
      setTestResult(result);
    } catch (error) {
      setRulesError(getParsedApiError(error));
    } finally {
      setBusyRule(null);
    }
  };

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow={text.eyebrow}
        title={text.title}
        description={text.description}
      />

      {createError ? <ApiErrorAlert error={createError} onDismiss={() => setCreateError(null)} /> : null}
      {createSuccess ? (
        <InlineAlert
          title={text.createSuccess}
          message={createSuccess}
          variant="success"
          action={(
            <button type="button" className="text-sm underline" onClick={() => setCreateSuccess(null)}>
              {text.close}
            </button>
          )}
        />
      ) : null}
      {rulesError ? <ApiErrorAlert error={rulesError} onDismiss={() => setRulesError(null)} /> : null}

      <div className="grid items-stretch gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
        <AlertRuleForm onSubmit={handleCreateRule} isSubmitting={createLoading} />
        <div className="flex h-full min-h-0 flex-col gap-4">
          <AlertRuleList
            className="flex h-full min-h-0 flex-col"
            rules={rules}
            total={rulesTotal}
            page={rulesPage}
            pageSize={PAGE_SIZE}
            isLoading={rulesLoading}
            enabledFilter={enabledFilter}
            alertTypeFilter={alertTypeFilter}
            onEnabledFilterChange={(value) => {
              setEnabledFilter(value);
              setRulesPage(1);
            }}
            onAlertTypeFilterChange={(value) => {
              setAlertTypeFilter(value);
              setRulesPage(1);
            }}
            onPageChange={setRulesPage}
            onToggleEnabled={(rule) => void handleToggleEnabled(rule)}
            onDelete={(rule) => void handleDeleteRule(rule)}
            onTest={(rule) => void handleTestRule(rule)}
            busyRule={busyRule}
          />
          {testResult ? (
            <InlineAlert
              title={text.testResult}
              variant={testVariant(testResult)}
              message={renderTestResultMessage(testResult, language)}
            />
          ) : null}
        </div>
      </div>

      {triggersError ? <ApiErrorAlert error={triggersError} onDismiss={() => setTriggersError(null)} /> : null}
      <AlertTriggerHistory triggers={triggers} isLoading={triggersLoading} />

      {notificationsError ? <ApiErrorAlert error={notificationsError} onDismiss={() => setNotificationsError(null)} /> : null}
      <Card title={text.notificationTitle} subtitle={text.notificationSubtitle} variant="bordered" padding="md">
        {notificationsLoading ? <Loading label={text.loadingNotifications} /> : null}
        {!notificationsLoading && notifications.length === 0 ? (
          <EmptyState
            icon={<BellRing className="h-6 w-6" />}
            title={text.emptyNotifications}
            description={text.emptyNotificationsDescription}
          />
        ) : null}
        {!notificationsLoading && notifications.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                <tr>
                  {text.notificationHeaders.map((header) => <th className="px-3 py-2 font-medium" key={header}>{header}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {notifications.map((notification) => (
                  <tr key={notification.id}>
                    <td className="px-3 py-3">{formatNotificationChannel(notification.channel, language)}</td>
                    <td className="px-3 py-3">{formatNotificationStatus(notification, language)}</td>
                    <td className="px-3 py-3">{notification.errorCode ?? '--'}</td>
                    <td className="px-3 py-3">{notification.latencyMs == null ? '--' : `${notification.latencyMs}ms`}</td>
                    <td className="px-3 py-3">{formatDateTime(notification.createdAt, language)}</td>
                    <td className="px-3 py-3">{notification.diagnostics ?? '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
    </AppPage>
  );
};

export default AlertsPage;
