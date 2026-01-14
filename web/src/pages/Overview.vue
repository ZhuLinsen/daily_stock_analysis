<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import {
  fetchConfig,
  fetchReports,
  runJob,
  type ConfigResponse,
  type ReportMeta,
  type RunMode,
  type RunRecord,
} from "../api";
import StatCard from "../components/StatCard.vue";

const loading = ref(true);
const error = ref("");
const reports = ref<ReportMeta[]>([]);
const config = ref<ConfigResponse | null>(null);
const runError = ref("");
const runMessage = ref("");
const runningMode = ref<RunMode | null>(null);
const runs = ref<RunRecord[]>([]);
const progressOpen = ref(false);
const consoleDialog = ref<HTMLDialogElement | null>(null);
const logContainer = ref<HTMLDivElement | null>(null);
const activeRun = ref<RunRecord | null>(null);
const logLines = ref<{ ts: string; line: string }[]>([]);
let eventSource: EventSource | null = null;

const latestReport = computed(() => reports.value[0]);
const reportCount = computed(() => reports.value.length.toString());

const envStatus = computed(() => {
  if (!config.value) {
    return "未知";
  }
  return config.value.envFileExists ? "已生成" : "未创建";
});

const envUpdatedAt = computed(() => {
  if (!config.value?.envUpdatedAt) {
    return "未记录";
  }
  return new Date(config.value.envUpdatedAt).toLocaleString();
});

onMounted(async () => {
  try {
    const [reportResponse, configResponse] = await Promise.all([
      fetchReports(),
      fetchConfig(),
    ]);
    reports.value = reportResponse.reports;
    config.value = configResponse;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
});

onUnmounted(() => {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
});

const openConsole = async () => {
  if (!consoleDialog.value) return;
  if (!consoleDialog.value.open) {
    consoleDialog.value.showModal();
  }
  await nextTick();
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight;
  }
};

const closeConsole = () => {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  consoleDialog.value?.close();
};

const startStream = async (run: RunRecord) => {
  activeRun.value = run;
  logLines.value = [];
  await openConsole();
  if (eventSource) {
    eventSource.close();
  }
  const url = `/api/run/stream?id=${encodeURIComponent(run.id)}&cursor=0`;
  eventSource = new EventSource(url);
  eventSource.onmessage = async (event) => {
    try {
      const payload = JSON.parse(event.data) as {
        logs: { ts: string; line: string }[];
        cursor: number;
        status: string;
        exitCode?: number;
      };
      if (payload.logs?.length) {
        logLines.value.push(...payload.logs);
        await nextTick();
        if (logContainer.value) {
          logContainer.value.scrollTop = logContainer.value.scrollHeight;
        }
      }
      if (activeRun.value) {
        activeRun.value.status = payload.status;
        activeRun.value.exitCode = payload.exitCode;
      }
      if (payload.logs?.length) {
        const lastLine = payload.logs[payload.logs.length - 1]?.line ?? "";
        runs.value = runs.value.map((run) =>
          run.id === activeRun.value?.id
            ? {
                ...run,
                status: payload.status,
                exitCode: payload.exitCode,
                lastLine,
              }
            : run,
        );
      } else if (activeRun.value) {
        runs.value = runs.value.map((run) =>
          run.id === activeRun.value?.id
            ? {
                ...run,
                status: payload.status,
                exitCode: payload.exitCode,
              }
            : run,
        );
      }
      if (payload.status !== "running" && eventSource) {
        eventSource.close();
        eventSource = null;
      }
    } catch (err) {
      runError.value = err instanceof Error ? err.message : "日志解析失败";
    }
  };
  eventSource.onerror = () => {
    runError.value = "日志连接中断";
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  };
};

const handleRun = async (mode: RunMode) => {
  runError.value = "";
  runMessage.value = "";
  runningMode.value = mode;
  try {
    const response = await runJob(mode);
    runMessage.value = `已触发：${response.run.command} (PID ${response.run.pid})`;
    runs.value = [response.run, ...runs.value.filter((run) => run.id !== response.run.id)];
    await startStream(response.run);
  } catch (err) {
    runError.value = err instanceof Error ? err.message : "运行失败";
  } finally {
    runningMode.value = null;
  }
};

const handleOpenRun = async (run: RunRecord) => {
  runError.value = "";
  await startStream(run);
};
</script>

<template>
  <section class="space-y-6">
    <div>
      <h3 class="text-2xl font-semibold text-slate-900 text-balance">系统状态</h3>
      <p class="mt-2 text-sm text-slate-600 text-pretty">
        关键配置与最近生成的报告概览。
      </p>
    </div>

    <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <div v-if="loading" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div class="rounded-2xl border border-slate-200 bg-white p-5">
        <div class="h-4 w-20 rounded bg-slate-100"></div>
        <div class="mt-4 h-8 w-32 rounded bg-slate-100"></div>
        <div class="mt-4 h-4 w-40 rounded bg-slate-100"></div>
      </div>
      <div class="rounded-2xl border border-slate-200 bg-white p-5">
        <div class="h-4 w-20 rounded bg-slate-100"></div>
        <div class="mt-4 h-8 w-32 rounded bg-slate-100"></div>
        <div class="mt-4 h-4 w-40 rounded bg-slate-100"></div>
      </div>
      <div class="rounded-2xl border border-slate-200 bg-white p-5">
        <div class="h-4 w-20 rounded bg-slate-100"></div>
        <div class="mt-4 h-8 w-32 rounded bg-slate-100"></div>
        <div class="mt-4 h-4 w-40 rounded bg-slate-100"></div>
      </div>
    </div>

    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <StatCard label="报告总数" :value="reportCount" subtitle="reports/ 目录内的 Markdown" />
      <StatCard label="配置文件" :value="envStatus" :subtitle="`最近更新：${envUpdatedAt}`" />
      <StatCard
        label="最新报告"
        :value="latestReport?.title ?? '暂无'"
        :subtitle="latestReport?.updated_at ? `更新时间：${new Date(latestReport.updated_at).toLocaleString()}` : '等待生成'"
      />
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="rounded-2xl border border-slate-200 bg-white p-6">
        <h4 class="text-lg font-semibold text-slate-900 text-balance">下一步</h4>
        <p class="mt-2 text-sm text-slate-600 text-pretty">
          先配置 API Key 与推送渠道，再查看决策仪表盘或日报内容。
        </p>
        <div class="mt-4 flex flex-wrap gap-2">
          <RouterLink
            to="/settings"
            class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
          >
            打开配置中心
          </RouterLink>
          <RouterLink
            to="/reports"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
          >
            浏览报告
          </RouterLink>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200 bg-white p-6">
        <h4 class="text-lg font-semibold text-slate-900 text-balance">报告类型说明</h4>
        <ul class="mt-3 space-y-2 text-sm text-slate-600 text-pretty">
          <li>决策仪表盘：个股行动建议与买卖点位。</li>
          <li>日报：每日的分析摘要与关键指标。</li>
          <li>大盘复盘：市场概览与板块动态。</li>
        </ul>
      </div>
    </div>

    <div class="rounded-2xl border border-slate-200 bg-white p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 class="text-lg font-semibold text-slate-900 text-balance">运行任务</h4>
          <p class="mt-2 text-sm text-slate-600 text-pretty">
            对应 README 的三种运行方式：完整分析、仅大盘复盘、定时任务模式。
          </p>
        </div>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
          :disabled="runningMode === 'full'"
          @click="handleRun('full')"
        >
          {{ runningMode === "full" ? "运行中..." : "完整分析" }}
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
          :disabled="runningMode === 'market-review'"
          @click="handleRun('market-review')"
        >
          {{ runningMode === "market-review" ? "运行中..." : "仅大盘复盘" }}
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
          :disabled="runningMode === 'schedule'"
          @click="handleRun('schedule')"
        >
          {{ runningMode === "schedule" ? "运行中..." : "定时任务模式" }}
        </button>
        <button
          type="button"
          v-if="runs.length > 0"
          class="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white"
          @click="progressOpen = !progressOpen"
        >
          {{ progressOpen ? "收起进度" : "进度查看" }}
        </button>
      </div>
      <p v-if="runMessage" class="mt-3 text-sm text-indigo-700">{{ runMessage }}</p>
      <p v-if="runError" class="mt-3 text-sm text-rose-600">{{ runError }}</p>

      <div v-if="progressOpen" class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-center justify-between">
          <p class="text-sm font-medium text-slate-700">最近运行</p>
          <span class="text-xs text-slate-500">仅显示本次会话</span>
        </div>
        <div v-if="runs.length === 0" class="mt-3 text-sm text-slate-500">
          暂无运行记录。
        </div>
        <div v-else class="mt-3 space-y-2">
          <button
            v-for="run in runs"
            :key="run.id"
            type="button"
            class="w-full rounded-xl border border-slate-200 bg-white p-3 text-left"
            @click="handleOpenRun(run)"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p class="text-sm font-medium text-slate-800">{{ run.command }}</p>
                <p class="mt-1 text-xs text-slate-500 tabular-nums">
                  {{ new Date(run.startedAt).toLocaleString() }}
                </p>
              </div>
              <div class="text-xs text-slate-600">
                <span class="rounded-full bg-slate-100 px-3 py-1">
                  {{ run.status === "running" ? "运行中" : "已结束" }}
                </span>
              </div>
            </div>
            <p v-if="run.lastLine" class="mt-2 text-xs text-slate-500 text-pretty">
              {{ run.lastLine }}
            </p>
          </button>
        </div>
      </div>
    </div>

    <dialog
      ref="consoleDialog"
      class="console-dialog w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-0 text-slate-100"
    >
      <div class="flex h-dvh flex-col lg:h-auto">
        <div class="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3">
          <div class="flex items-center gap-2">
            <span class="size-3 rounded-full bg-rose-400"></span>
            <span class="size-3 rounded-full bg-amber-400"></span>
            <span class="size-3 rounded-full bg-indigo-400"></span>
          </div>
          <div class="text-xs text-slate-400">任务控制台</div>
          <button
            type="button"
            class="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-200"
            @click="closeConsole"
          >
            关闭
          </button>
        </div>
        <div class="border-b border-slate-800 bg-slate-900 px-4 py-2 text-xs text-slate-400">
          <span v-if="activeRun" class="tabular-nums">
            {{ activeRun.command }} · {{ activeRun.status }} · PID {{ activeRun.pid }}
          </span>
          <span v-else>暂无运行任务</span>
        </div>
        <div ref="logContainer" class="h-[80vh] overflow-y-auto bg-slate-950 px-4 py-3 font-mono text-xs text-slate-200">
          <div v-if="logLines.length === 0" class="text-slate-500">等待日志输出...</div>
          <div v-for="(line, index) in logLines" :key="`${line.ts}-${index}`" class="whitespace-pre-wrap">
            <span class="text-slate-500">[{{ new Date(line.ts).toLocaleTimeString() }}]</span>
            <span class="ml-2">{{ line.line }}</span>
          </div>
        </div>
        <div class="flex items-center justify-between border-t border-slate-800 bg-slate-900 px-4 py-3 text-xs text-slate-400">
          <span>实时日志</span>
          <span v-if="activeRun?.exitCode !== undefined">退出码：{{ activeRun.exitCode }}</span>
        </div>
      </div>
    </dialog>
  </section>
</template>
