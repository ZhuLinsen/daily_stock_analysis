import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BellRing } from 'lucide-react';
import { alertsApi } from '../api/alerts';
import type { ParsedApiError } from '../api/error';
import { createParsedApiError, getParsedApiError } from '../api/error';
import { AlertRuleForm } from '../components/alerts/AlertRuleForm';
import {
  AlertRuleList,
  type AlertRuleBusyAction,
  type AlertRuleEnabledFilter,
  type AlertTypeFilter,
} from '../components/alerts/AlertRuleList';
import { AlertTriggerHistory } from '../components/alerts/AlertTriggerHistory';
import { ApiErrorAlert, AppPage, Card, EmptyState, InlineAlert, Loading, PageHeader } from '../components/common';
import type {
  AlertNotificationItem,
  AlertRuleCreateRequest,
  AlertRuleItem,
  AlertRuleListResponse,
  AlertRuleTargetResult,
  AlertRuleTestResponse,
  AlertTriggerItem,
  AlertType,
} from '../types/alerts';
import { formatDateTime } from '../utils/format';

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

type RuleTestFeedback =
  | { kind: 'error'; error: ParsedApiError }
  | { kind: 'warning'; title: string; message: string };

function isFailedTarget(item: AlertRuleTargetResult): boolean {
  return item.status === 'evaluation_error' || item.recordStatus === 'failed';
}

function isDegradedTarget(item: AlertRuleTargetResult): boolean {
  return item.recordStatus === 'degraded' || (item.status as string) === 'degraded';
}

function isSkippedTarget(item: AlertRuleTargetResult): boolean {
  return item.recordStatus === 'skipped' || (item.status as string) === 'skipped';
}

function formatTargetDiagnostics(items: AlertRuleTargetResult[]): string {
  return items
    .map((item) => `${item.displayTarget ?? item.target}: ${item.message || item.recordStatus || item.status}`)
    .join('；');
}

function buildOutOfOrderTestFeedback(
  rule: AlertRuleItem,
  result: AlertRuleTestResponse,
): RuleTestFeedback | null {
  const targetResults = result.targetResults ?? [];
  const failedTargets = targetResults.filter(isFailedTarget);
  const degradedTargets = targetResults.filter(isDegradedTarget);
  const skippedTargets = targetResults.filter(isSkippedTarget);
  const isTruncated = result.evaluatedCount != null && result.evaluatedCount > targetResults.length;
  const legacyFailedMatch =
    result.failedCount == null && isTruncated
      ? /\b([1-9]\d*)\s+failed\b/i.exec(result.message ?? '')
      : null;
  const failedCount = Math.max(
    result.failedCount ?? (legacyFailedMatch ? Number(legacyFailedMatch[1]) : 0),
    failedTargets.length,
  );
  const degradedCount = Math.max(result.degradedCount ?? 0, degradedTargets.length);
  const skippedCount = Math.max(result.skippedCount ?? 0, skippedTargets.length);
  const isMultiTarget = (result.evaluatedCount ?? targetResults.length) > 1;

  if (result.status === 'evaluation_error') {
    const failedDetails = isMultiTarget ? formatTargetDiagnostics(failedTargets) : '';
    const hiddenFailedCount = isMultiTarget ? Math.max(0, failedCount - failedTargets.length) : 0;
    const hiddenNote = hiddenFailedCount > 0
      ? (failedTargets.length > 0
        ? `另有 ${hiddenFailedCount} 个标的评估失败（超出展示上限未逐条列出）`
        : `共 ${failedCount} 个标的评估失败（超出展示上限未逐条列出）`)
      : '';
    const combinedMessage = [result.message, failedDetails, hiddenNote].filter(Boolean).join('；');
    return {
      kind: 'error',
      error: createParsedApiError({
        title: `规则「${rule.name}」测试失败`,
        message: combinedMessage || '规则测试评估失败',
        rawMessage: combinedMessage || undefined,
        category: 'unknown',
      }),
    };
  }

  if (failedCount > 0) {
    const failedDetails = formatTargetDiagnostics(failedTargets);
    const hiddenFailedCount = isMultiTarget ? Math.max(0, failedCount - failedTargets.length) : 0;
    const hiddenNote = hiddenFailedCount > 0
      ? (failedTargets.length > 0
        ? `另有 ${hiddenFailedCount} 个标的评估失败（超出展示上限未逐条列出）`
        : `共 ${failedCount} 个标的评估失败（超出展示上限未逐条列出）`)
      : '';
    const combinedMessage = [result.message, failedDetails, hiddenNote].filter(Boolean).join('；');
    return {
      kind: 'error',
      error: createParsedApiError({
        title: isMultiTarget ? `规则「${rule.name}」部分标的测试失败` : `规则「${rule.name}」测试失败`,
        message: combinedMessage || failedDetails || '部分标的测试评估失败',
        rawMessage: combinedMessage || undefined,
        category: 'unknown',
      }),
    };
  }

  const topLevelStatus = result.status as string;
  if (degradedCount > 0 || skippedCount > 0 || topLevelStatus === 'skipped' || topLevelStatus === 'degraded') {
    const diagnosticTargets = [...degradedTargets, ...skippedTargets];
    const totalDiagnosticCount = degradedCount + skippedCount;
    if (!isMultiTarget) {
      const baseMessage = result.message?.trim();
      const singleTargetMessage = diagnosticTargets[0]?.message?.trim();
      const messageParts: string[] = [];
      if (baseMessage) {
        messageParts.push(baseMessage);
      }
      if (singleTargetMessage && (!baseMessage || !baseMessage.includes(singleTargetMessage))) {
        messageParts.push(singleTargetMessage);
      }
      const isDegradedOnly =
        (degradedCount > 0 || topLevelStatus === 'degraded')
        && skippedCount === 0
        && topLevelStatus !== 'skipped';
      const fallbackMessage = isDegradedOnly ? '规则测试数据降级，未完成评估' : '规则测试已跳过，未完成评估';
      return {
        kind: 'warning',
        title: isDegradedOnly ? `规则「${rule.name}」测试数据降级` : `规则「${rule.name}」测试未评估`,
        message: messageParts.join('；') || fallbackMessage,
      };
    }

    const diagnosticDetails = formatTargetDiagnostics(diagnosticTargets);
    const hiddenDiagnosticCount = Math.max(0, totalDiagnosticCount - diagnosticTargets.length);
    const hiddenNote = hiddenDiagnosticCount > 0
      ? (diagnosticTargets.length > 0
        ? `另有 ${hiddenDiagnosticCount} 个标的降级或跳过（超出展示上限未逐条列出）`
        : `共 ${totalDiagnosticCount} 个标的降级或跳过（超出展示上限未逐条列出）`)
      : '';
    const combinedMessage = [result.message, diagnosticDetails, hiddenNote].filter(Boolean).join('；');
    return {
      kind: 'warning',
      title: `规则「${rule.name}」部分标的未完成评估`,
      message: combinedMessage || diagnosticDetails || '部分标的未完成评估',
    };
  }

  return null;
}

function renderTestResultMessage(result: AlertRuleTestResponse): React.ReactNode {
  const targetResults = result.targetResults ?? [];
  return (
    <div className="space-y-2">
      <div>
        {result.message}
        {' · 状态：'}
        {result.status}
        {' · 触发：'}
        {result.triggered ? '是' : '否'}
        {' · 观察值：'}
        {result.observedValue == null ? '--' : String(result.observedValue)}
      </div>
      {result.evaluatedCount != null && result.evaluatedCount > 1 ? (
        <div className="text-xs">
          评估 {result.evaluatedCount} · 触发 {result.triggeredCount ?? 0} · 降级 {result.degradedCount ?? 0} · 跳过 {result.skippedCount ?? 0}
          {result.failedCount != null ? ` · 失败 ${result.failedCount}` : ''}
        </div>
      ) : null}
      {targetResults.length > 1 ? (
        <div className="grid gap-1 text-xs">
          {targetResults.slice(0, 20).map((item, index) => (
            <div key={`${item.target}-${item.status}-${index}`} className="flex flex-wrap justify-between gap-2">
              <span>{item.displayTarget ?? item.target}</span>
              <span>
                {item.status}
                {item.recordStatus ? ` / ${item.recordStatus}` : ''}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const notificationChannelLabel: Record<string, string> = {
  __cooldown__: '业务冷却',
  __cooldown_read_failed__: '冷却读取失败',
  __noise_suppressed__: '通知降噪',
  __no_channel__: '无可用渠道',
  __dispatch__: '通知调度',
  __context__: '会话渠道',
};

function formatNotificationChannel(channel: string): string {
  return notificationChannelLabel[channel] ?? channel;
}

function formatNotificationStatus(notification: AlertNotificationItem): string {
  if (notification.success) return '成功';
  if (notification.errorCode === 'cooldown_active') return '冷却抑制';
  if (notification.errorCode === 'cooldown_read_failed') return '冷却读取失败';
  if (notification.errorCode === 'noise_suppressed') return '降噪抑制';
  if (notification.errorCode === 'no_channel') return '无渠道';
  return '失败';
}

const AlertsPage: React.FC = () => {
  useEffect(() => {
    document.title = '告警中心 - DSA';
  }, []);

  const [rules, setRules] = useState<AlertRuleItem[]>([]);
  const [rulesTotal, setRulesTotal] = useState(0);
  const [ruleSources, setRuleSources] = useState<AlertRuleListResponse['ruleSources']>(null);
  const [rulesPage, setRulesPage] = useState(1);
  const [enabledFilter, setEnabledFilter] = useState<AlertRuleEnabledFilter>('all');
  const [alertTypeFilter, setAlertTypeFilter] = useState<AlertTypeFilter>('all');
  const [rulesLoading, setRulesLoading] = useState(false);
  const [rulesError, setRulesError] = useState<ParsedApiError | null>(null);
  const [rulesLoaded, setRulesLoaded] = useState(false);
  const [rulesRefreshKey, setRulesRefreshKey] = useState(0);

  const [triggers, setTriggers] = useState<AlertTriggerItem[]>([]);
  const [triggersLoading, setTriggersLoading] = useState(false);
  const [triggersError, setTriggersError] = useState<ParsedApiError | null>(null);

  const [notifications, setNotifications] = useState<AlertNotificationItem[]>([]);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsError, setNotificationsError] = useState<ParsedApiError | null>(null);

  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<ParsedApiError | null>(null);
  const [createSuccess, setCreateSuccess] = useState<string | null>(null);
  const [busyRules, setBusyRules] = useState<Record<number, AlertRuleBusyAction>>({});
  const [testResult, setTestResult] = useState<{ ruleId: number; response: AlertRuleTestResponse } | null>(null);
  const [testFeedback, setTestFeedback] = useState<Record<number, RuleTestFeedback>>({});
  const mountedRef = useRef(true);
  const rulesRequestIdRef = useRef(0);
  const triggersRequestIdRef = useRef(0);
  const notificationsRequestIdRef = useRef(0);
  const testRequestIdRef = useRef(0);
  const activeTestRuleIdRef = useRef<number | null>(null);
  const ruleTestEpochRef = useRef<Record<number, number>>({});
  const createInFlightRef = useRef(false);
  const busyRuleIdsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      rulesRequestIdRef.current += 1;
      triggersRequestIdRef.current += 1;
      notificationsRequestIdRef.current += 1;
      testRequestIdRef.current += 1;
      activeTestRuleIdRef.current = null;
      ruleTestEpochRef.current = {};
      busyRuleIdsRef.current = new Set();
    };
  }, []);

  const setRuleBusy = useCallback((ruleId: number, action: AlertRuleBusyAction) => {
    busyRuleIdsRef.current.add(ruleId);
    setBusyRules((previous) => ({ ...previous, [ruleId]: action }));
  }, []);

  const clearRuleBusy = useCallback((ruleId: number) => {
    busyRuleIdsRef.current.delete(ruleId);
    if (!mountedRef.current) return;
    setBusyRules((previous) => {
      if (!(ruleId in previous)) return previous;
      const next = { ...previous };
      delete next[ruleId];
      return next;
    });
  }, []);

  const loadRules = useCallback(async () => {
    const requestId = rulesRequestIdRef.current + 1;
    rulesRequestIdRef.current = requestId;
    const isLatestRequest = () => mountedRef.current && rulesRequestIdRef.current === requestId;
    const requestedPage = rulesPage;
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
      }
      setRules(response.items);
      setRulesTotal(response.total);
      setRuleSources(response.ruleSources ?? null);
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
    const requestId = triggersRequestIdRef.current + 1;
    triggersRequestIdRef.current = requestId;
    const isLatestRequest = () => mountedRef.current && triggersRequestIdRef.current === requestId;
    setTriggersLoading(true);
    try {
      const response = await alertsApi.listTriggers({ page: 1, pageSize: PAGE_SIZE });
      if (!isLatestRequest()) return;
      setTriggers(response.items);
      setTriggersError(null);
    } catch (error) {
      if (!isLatestRequest()) return;
      setTriggersError(getParsedApiError(error));
    } finally {
      if (isLatestRequest()) {
        setTriggersLoading(false);
      }
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    const requestId = notificationsRequestIdRef.current + 1;
    notificationsRequestIdRef.current = requestId;
    const isLatestRequest = () => mountedRef.current && notificationsRequestIdRef.current === requestId;
    setNotificationsLoading(true);
    try {
      const response = await alertsApi.listNotifications({ page: 1, pageSize: PAGE_SIZE });
      if (!isLatestRequest()) return;
      setNotifications(response.items);
      setNotificationsError(null);
    } catch (error) {
      if (!isLatestRequest()) return;
      setNotificationsError(getParsedApiError(error));
    } finally {
      if (isLatestRequest()) {
        setNotificationsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadRules();
  }, [loadRules, rulesRefreshKey]);

  useEffect(() => {
    if (!rulesLoaded) return;
    void loadTriggers();
    void loadNotifications();
  }, [loadNotifications, loadTriggers, rulesLoaded]);

  const handleCreateRule = async (payload: AlertRuleCreateRequest) => {
    if (createInFlightRef.current) return false;
    createInFlightRef.current = true;
    setCreateLoading(true);
    setCreateError(null);
    setCreateSuccess(null);
    try {
      const created = await alertsApi.createRule(payload);
      if (!mountedRef.current) return false;
      setCreateSuccess(`已创建告警规则「${created.name}」`);
      setRulesPage(1);
      setRulesRefreshKey((value) => value + 1);
      return true;
    } catch (error) {
      if (!mountedRef.current) return false;
      setCreateError(getParsedApiError(error));
      return false;
    } finally {
      createInFlightRef.current = false;
      if (mountedRef.current) {
        setCreateLoading(false);
      }
    }
  };

  const handleToggleEnabled = async (rule: AlertRuleItem) => {
    if (busyRuleIdsRef.current.has(rule.id)) return;
    setRuleBusy(rule.id, 'toggle');
    try {
      if (rule.enabled) {
        await alertsApi.disableRule(rule.id);
      } else {
        await alertsApi.enableRule(rule.id);
      }
      if (!mountedRef.current) return;
      setRulesRefreshKey((value) => value + 1);
    } catch (error) {
      if (!mountedRef.current) return;
      setRulesError(getParsedApiError(error));
    } finally {
      clearRuleBusy(rule.id);
    }
  };

  const handleDeleteRule = async (rule: AlertRuleItem) => {
    if (busyRuleIdsRef.current.has(rule.id)) return;
    setRuleBusy(rule.id, 'delete');
    try {
      await alertsApi.deleteRule(rule.id);
      if (!mountedRef.current) return;
      ruleTestEpochRef.current[rule.id] = (ruleTestEpochRef.current[rule.id] ?? 0) + 1;
      if (activeTestRuleIdRef.current === rule.id) {
        testRequestIdRef.current += 1;
        activeTestRuleIdRef.current = null;
      }
      setTestResult((current) => (current?.ruleId === rule.id ? null : current));
      setTestFeedback((previous) => {
        if (!(rule.id in previous)) return previous;
        const next = { ...previous };
        delete next[rule.id];
        return next;
      });
      setRulesRefreshKey((value) => value + 1);
    } catch (error) {
      if (!mountedRef.current) return;
      setRulesError(getParsedApiError(error));
    } finally {
      clearRuleBusy(rule.id);
    }
  };

  const handleTestRule = async (rule: AlertRuleItem) => {
    if (busyRuleIdsRef.current.has(rule.id)) return;
    const requestId = testRequestIdRef.current + 1;
    testRequestIdRef.current = requestId;
    const ruleEpoch = (ruleTestEpochRef.current[rule.id] ?? 0) + 1;
    ruleTestEpochRef.current[rule.id] = ruleEpoch;
    activeTestRuleIdRef.current = rule.id;
    setRuleBusy(rule.id, 'test');
    setTestResult(null);
    setTestFeedback((previous) => {
      if (!(rule.id in previous)) return previous;
      const next = { ...previous };
      delete next[rule.id];
      return next;
    });
    try {
      const result = await alertsApi.testRule(rule.id);
      if (!mountedRef.current || ruleTestEpochRef.current[rule.id] !== ruleEpoch) {
        return;
      }
      if (testRequestIdRef.current !== requestId) {
        const feedback = buildOutOfOrderTestFeedback(rule, result);
        if (feedback) {
          setTestFeedback((previous) => ({
            ...previous,
            [rule.id]: feedback,
          }));
        }
        return;
      }
      setTestResult({ ruleId: rule.id, response: result });
    } catch (error) {
      if (!mountedRef.current || ruleTestEpochRef.current[rule.id] !== ruleEpoch) return;
      const parsedError = getParsedApiError(error);
      setTestFeedback((previous) => ({
        ...previous,
        [rule.id]: { kind: 'error', error: parsedError },
      }));
    } finally {
      if (testRequestIdRef.current === requestId) {
        activeTestRuleIdRef.current = null;
      }
      clearRuleBusy(rule.id);
    }
  };

  return (
    <AppPage className="space-y-5">
      <PageHeader
        eyebrow="Alert Center"
        title="告警中心"
        description="管理事件告警、日线技术指标、自选股、持仓/账户联动和大盘红绿灯规则，执行一次性测试，并查看后台评估任务记录的触发历史。"
      />

      {createError ? <ApiErrorAlert error={createError} onDismiss={() => setCreateError(null)} /> : null}
      {createSuccess ? (
        <InlineAlert
          title="创建成功"
          message={createSuccess}
          variant="success"
          action={(
            <button type="button" className="text-sm underline" onClick={() => setCreateSuccess(null)}>
              关闭
            </button>
          )}
        />
      ) : null}
      {rulesError ? <ApiErrorAlert error={rulesError} onDismiss={() => setRulesError(null)} /> : null}
      {Object.entries(testFeedback).map(([ruleIdStr, feedback]) => {
        const targetRuleId = Number(ruleIdStr);
        const dismissFeedback = () => {
          setTestFeedback((previous) => {
            if (!(targetRuleId in previous)) return previous;
            const next = { ...previous };
            delete next[targetRuleId];
            return next;
          });
        };
        if (feedback.kind === 'warning') {
          return (
            <InlineAlert
              key={`test-feedback-${ruleIdStr}`}
              title={feedback.title}
              message={feedback.message}
              variant="warning"
              action={(
                <button type="button" className="text-sm underline" onClick={dismissFeedback}>
                  关闭
                </button>
              )}
            />
          );
        }
        return (
          <ApiErrorAlert
            key={`test-feedback-${ruleIdStr}`}
            error={feedback.error}
            onDismiss={dismissFeedback}
          />
        );
      })}
      {!rulesError && ruleSources && ruleSources.legacyConfigured > 0 ? (
        <InlineAlert
          title="存在环境变量告警规则"
          variant="warning"
          message={`环境变量配置了 ${ruleSources.legacyConfigured} 条有效规则，按当前启用的页面规则去重后有 ${ruleSources.legacyEffective} 条可供后台轮询。此数量不受页面筛选影响，也不表示后台轮询已启动。页面仅管理数据库规则；删除或禁用页面规则不会停用环境规则。若需停用，请在部署配置中修改 AGENT_EVENT_ALERT_RULES_JSON 并重新加载配置。`}
        />
      ) : null}

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
            busyRules={busyRules}
          />
          {testResult ? (
            <InlineAlert
              title="测试结果"
              variant={testVariant(testResult.response)}
              message={renderTestResultMessage(testResult.response)}
            />
          ) : null}
        </div>
      </div>

      {triggersError ? <ApiErrorAlert error={triggersError} onDismiss={() => setTriggersError(null)} /> : null}
      <AlertTriggerHistory triggers={triggers} isLoading={triggersLoading} />

      {notificationsError ? <ApiErrorAlert error={notificationsError} onDismiss={() => setNotificationsError(null)} /> : null}
      <Card title="通知尝试记录" subtitle="通知结果" variant="bordered" padding="md">
        {notificationsLoading ? <Loading label="正在加载通知尝试记录" /> : null}
        {!notificationsLoading && notifications.length === 0 ? (
          <EmptyState
            icon={<BellRing className="h-6 w-6" />}
            title="暂无通知尝试记录"
            description="当前没有可展示的通知尝试明细；告警触发仍会按已配置通知渠道发送。"
          />
        ) : null}
        {!notificationsLoading && notifications.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
                <tr>
                  <th className="px-3 py-2 font-medium">渠道</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">错误码</th>
                  <th className="px-3 py-2 font-medium">耗时</th>
                  <th className="px-3 py-2 font-medium">时间</th>
                  <th className="px-3 py-2 font-medium">诊断</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {notifications.map((notification) => (
                  <tr key={notification.id}>
                    <td className="px-3 py-3">{formatNotificationChannel(notification.channel)}</td>
                    <td className="px-3 py-3">{formatNotificationStatus(notification)}</td>
                    <td className="px-3 py-3">{notification.errorCode ?? '--'}</td>
                    <td className="px-3 py-3">{notification.latencyMs == null ? '--' : `${notification.latencyMs}ms`}</td>
                    <td className="px-3 py-3">{formatDateTime(notification.createdAt)}</td>
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
