import type React from 'react';
import { ChevronDown, RefreshCw, Workflow } from 'lucide-react';
import { Badge, Button, Card, StatusDot, Tooltip } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import type { TaskInfo } from '../../types/analysis';
import { getRequestedPhaseLabel } from '../../utils/marketPhase';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

/**
 * 任务项组件属性
 */
interface TaskItemProps {
  task: TaskInfo;
  onOpenRunFlow?: (task: TaskInfo) => void;
}

/**
 * 单个任务项
 */
const TaskItem: React.FC<TaskItemProps> = ({ task, onOpenRunFlow }) => {
  const { language, t } = useUiLanguage();
  const isPending = task.status === 'pending';
  const isProcessing = task.status === 'processing';
  const isCancelRequested = task.status === 'cancel_requested';
  const isCancelled = task.status === 'cancelled';
  const statusLabel = isCancelRequested
    ? t('taskPanel.cancelRequested')
    : isCancelled
      ? t('taskPanel.cancelled')
      : isProcessing ? t('taskPanel.processing') : t('taskPanel.pending');
  const statusVariant = isCancelRequested ? 'warning' : isProcessing ? 'info' : 'default';
  const statusTone = isCancelRequested ? 'warning' : isProcessing ? 'info' : 'neutral';
  const progress = Math.max(0, Math.min(100, task.progress || 0));
  const traceId = (task.traceId || '').trim();
  const requestedPhaseLabel = getRequestedPhaseLabel(task.analysisPhase, language);
  const requestedPhaseVariant = task.analysisPhase === 'auto' ? 'default' : 'info';

  return (
    <div className="home-subpanel flex items-center gap-3 px-3 py-2.5">
      {/* 状态图标 */}
      <div className="shrink-0">
        {isProcessing ? (
          <StatusDot tone="info" pulse className="h-2.5 w-2.5" aria-label={t('taskPanel.processingAria')} />
        ) : isCancelRequested ? (
          <StatusDot tone="warning" pulse className="h-2.5 w-2.5" aria-label={t('taskPanel.cancelRequestedAria')} />
        ) : isPending ? (
          <StatusDot tone="neutral" className="h-2.5 w-2.5" aria-label={t('taskPanel.pendingAria')} />
        ) : null}
      </div>

      {/* 任务信息 */}
      <div className="min-w-0 flex-1 overflow-hidden">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground truncate">
            {task.stockName || task.stockCode}
          </span>
          <span className="text-xs text-muted-text">
            {task.stockCode}
          </span>
        </div>
        {task.message && (
          <p className="text-xs text-secondary-text truncate mt-0.5">
            {task.message}
          </p>
        )}
        {requestedPhaseLabel ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant={requestedPhaseVariant} className="shrink-0 shadow-none" aria-label={requestedPhaseLabel}>
              {requestedPhaseLabel}
            </Badge>
          </div>
        ) : null}
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
            <div
              className="h-full rounded-full bg-cyan transition-[width] duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="shrink-0 text-[11px] text-muted-text tabular-nums">
            {progress}%
          </span>
        </div>
        {traceId ? (
          <details className="group/task mt-2 text-xs">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-text">
              <span>{t('taskPanel.diagnostics')}</span>
              <span className="font-mono text-[11px] text-secondary-text">
                {traceId.length > 18 ? `${traceId.slice(0, 10)}...` : traceId}
              </span>
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open/task:rotate-180" aria-hidden="true" />
            </summary>
            <div className="mt-1 rounded-lg border border-subtle bg-base/50 px-2 py-1.5 text-muted-text">
              <span className="mr-1">Trace:</span>
              <code className="break-all font-mono text-[11px] text-secondary-text">
                {traceId}
              </code>
            </div>
          </details>
        ) : null}
      </div>

      {/* 状态标签 */}
      <div className="relative z-10 flex flex-shrink-0 items-center gap-2">
        {onOpenRunFlow ? (
          <Tooltip content={t('taskPanel.openRunFlow')}>
            <span className="inline-flex">
              <Button
                type="button"
                variant="ghost"
                size="xsm"
                className="h-8 w-8 px-0"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenRunFlow(task);
                }}
                aria-label={t('taskPanel.openRunFlowAria', {
                  stock: task.stockName || task.stockCode,
                })}
              >
                <Workflow className="h-4 w-4" aria-hidden="true" />
              </Button>
            </span>
          </Tooltip>
        ) : null}
        <Badge
          variant={statusVariant}
          className="min-w-[4.75rem] justify-center gap-1.5 shadow-none"
          aria-label={t('taskPanel.statusAria', { status: statusLabel })}
        >
          <StatusDot tone={statusTone} pulse={isProcessing || isCancelRequested} className="h-1.5 w-1.5" />
          {statusLabel}
        </Badge>
      </div>
    </div>
  );
};

/**
 * 任务面板属性
 */
interface TaskPanelProps {
  /** 任务列表 */
  tasks: TaskInfo[];
  /** 是否显示 */
  visible?: boolean;
  /** 标题 */
  title?: string;
  /** 自定义类名 */
  className?: string;
  /** 打开运行流面板 */
  onOpenRunFlow?: (task: TaskInfo) => void;
}

/**
 * 任务面板组件
 * 显示进行中的分析任务列表
 */
export const TaskPanel: React.FC<TaskPanelProps> = ({
  tasks,
  visible = true,
  title,
  className = '',
  onOpenRunFlow,
}) => {
  const { t } = useUiLanguage();
  // 筛选活跃任务（pending / processing / cancel requested）
  const activeTasks = tasks.filter(
    (t) => t.status === 'pending' || t.status === 'processing' || t.status === 'cancel_requested'
  );

  // 无任务或不可见时不渲染
  if (!visible || activeTasks.length === 0) {
    return null;
  }

  const pendingCount = activeTasks.filter((t) => t.status === 'pending').length;
  const processingCount = activeTasks.filter((t) => t.status === 'processing').length;

  return (
    <Card
      variant="bordered"
      padding="none"
      className={`home-panel-card overflow-hidden ${className}`}
    >
      <div className="border-b border-subtle px-3 py-3">
        <DashboardPanelHeader
          className="mb-0"
          title={title ?? t('taskPanel.title')}
          titleClassName="text-sm font-medium"
          leading={(
            <RefreshCw className="h-4 w-4 text-cyan" aria-hidden="true" />
          )}
          headingClassName="items-center"
          actions={(
            <div className="flex items-center gap-2 text-xs text-muted-text">
              {processingCount > 0 && (
                <span className="flex items-center gap-1">
                  <StatusDot tone="info" pulse className="h-1.5 w-1.5" aria-label="进行中任务" />
                  {t('taskPanel.processingTasks', { count: processingCount })}
                </span>
              )}
              {pendingCount > 0 ? (
                <span className="flex items-center gap-1">
                  <StatusDot tone="neutral" className="h-1.5 w-1.5" aria-label="等待中任务" />
                  {t('taskPanel.pendingTasks', { count: pendingCount })}
                </span>
              ) : null}
            </div>
          )}
        />
      </div>

      <div className="max-h-64 overflow-y-auto p-2">
        <div className="space-y-2">
          {activeTasks.map((task) => (
            <TaskItem key={task.taskId} task={task} onOpenRunFlow={onOpenRunFlow} />
          ))}
        </div>
      </div>
    </Card>
  );
};

export default TaskPanel;
