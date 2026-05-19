export type AlertType = 'price_cross' | 'price_change_percent' | 'volume_spike';
export type AlertSeverity = 'info' | 'warning' | 'critical';
export type AlertTargetScope = 'single_symbol';
export type AlertDirection = 'above' | 'below' | 'up' | 'down';
export type AlertDryRunStatus = 'triggered' | 'not_triggered' | 'evaluation_error';
export type AlertTriggerStatus = 'triggered' | 'skipped' | 'degraded' | 'failed';

export interface AlertRuleParameters {
  direction?: AlertDirection;
  price?: number;
  changePct?: number;
  multiplier?: number;
}

export interface AlertRuleItem {
  id: number;
  name: string;
  targetScope: AlertTargetScope;
  target: string;
  alertType: AlertType;
  parameters: AlertRuleParameters;
  severity: AlertSeverity;
  enabled: boolean;
  source: string;
  cooldownPolicy?: Record<string, unknown> | null;
  notificationPolicy?: Record<string, unknown> | null;
  lastTriggeredAt?: string | null;
  cooldownUntil?: string | null;
  cooldownActive?: boolean | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface AlertRuleListResponse {
  items: AlertRuleItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface AlertRuleCreateRequest {
  name?: string;
  targetScope?: AlertTargetScope;
  target: string;
  alertType: AlertType;
  parameters: AlertRuleParameters;
  severity: AlertSeverity;
  enabled?: boolean;
}

export interface AlertDeleteResponse {
  deleted: number;
}

export interface AlertRuleTestResponse {
  ruleId: number;
  status: AlertDryRunStatus;
  triggered: boolean;
  observedValue?: unknown;
  message: string;
}

export interface AlertTriggerItem {
  id: number;
  ruleId?: number | null;
  target: string;
  observedValue?: number | null;
  threshold?: number | null;
  reason?: string | null;
  dataSource?: string | null;
  dataTimestamp?: string | null;
  triggeredAt?: string | null;
  status: AlertTriggerStatus | string;
  diagnostics?: string | null;
}

export interface AlertTriggerListResponse {
  items: AlertTriggerItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface AlertNotificationItem {
  id: number;
  triggerId?: number | null;
  channel: string;
  attempt: number;
  success: boolean;
  errorCode?: string | null;
  retryable: boolean;
  latencyMs?: number | null;
  diagnostics?: string | null;
  createdAt?: string | null;
}

export interface AlertNotificationListResponse {
  items: AlertNotificationItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface AlertRuleListQuery {
  enabled?: boolean;
  alertType?: AlertType;
  targetScope?: AlertTargetScope;
  target?: string;
  source?: string;
  page?: number;
  pageSize?: number;
}

export interface AlertTriggerListQuery {
  ruleId?: number;
  target?: string;
  status?: string;
  page?: number;
  pageSize?: number;
}

export interface AlertNotificationListQuery {
  triggerId?: number;
  channel?: string;
  success?: boolean;
  page?: number;
  pageSize?: number;
}
