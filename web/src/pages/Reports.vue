<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchReports, type ReportMeta } from "../api";

const loading = ref(true);
const error = ref("");
const reports = ref<ReportMeta[]>([]);
const search = ref("");
const typeFilter = ref("all");

type ReportType = ReportMeta["type"] | "all";
const typeLabels: { [K in ReportType]: string } = {
  all: "全部",
  dashboard: "决策仪表盘",
  daily: "日报",
  review: "复盘",
  other: "其他",
};

const filteredReports = computed(() => {
  const term = search.value.trim().toLowerCase();
  return reports.value.filter((report) => {
    if (typeFilter.value !== "all" && report.type !== typeFilter.value) {
      return false;
    }
    if (!term) {
      return true;
    }
    return report.title.toLowerCase().includes(term) || report.path.toLowerCase().includes(term);
  });
});

const formatSize = (size: number) => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
};

onMounted(async () => {
  try {
    const response = await fetchReports();
    reports.value = response.reports;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="space-y-6">
    <div>
      <h3 class="text-2xl font-semibold text-slate-900 text-balance">报告中心</h3>
      <p class="mt-2 text-sm text-slate-600 text-pretty">
        自动汇总 reports/ 目录中的 Markdown 报告。
      </p>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <label class="rounded-xl border border-slate-200 bg-white p-3">
        <span class="text-xs font-medium text-slate-500">搜索</span>
        <input
          v-model="search"
          type="text"
          placeholder="输入标题或文件名"
          class="mt-2 w-full border-none bg-transparent text-sm text-slate-900 outline-none"
        />
      </label>
      <label class="rounded-xl border border-slate-200 bg-white p-3">
        <span class="text-xs font-medium text-slate-500">类型筛选</span>
        <select
          v-model="typeFilter"
          class="mt-2 w-full border-none bg-transparent text-sm text-slate-900 outline-none"
        >
          <option value="all">全部</option>
          <option value="dashboard">决策仪表盘</option>
          <option value="daily">日报</option>
          <option value="review">复盘</option>
          <option value="other">其他</option>
        </select>
      </label>
    </div>

    <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <div v-if="loading" class="space-y-3">
      <div class="h-20 rounded-2xl border border-slate-200 bg-white"></div>
      <div class="h-20 rounded-2xl border border-slate-200 bg-white"></div>
      <div class="h-20 rounded-2xl border border-slate-200 bg-white"></div>
    </div>

    <div v-else class="space-y-3">
      <div
        v-if="filteredReports.length === 0"
        class="rounded-2xl border border-slate-200 bg-white p-6 text-center"
      >
        <p class="text-sm text-slate-600 text-pretty">没有匹配的报告，请调整筛选条件。</p>
        <RouterLink
          to="/settings"
          class="mt-4 inline-flex rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
        >
          检查配置
        </RouterLink>
      </div>

      <RouterLink
        v-for="report in filteredReports"
        :key="report.path"
        :to="{ name: 'report-detail', query: { path: report.path } }"
        class="block rounded-2xl border border-slate-200 bg-white p-5"
      >
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h4 class="text-lg font-semibold text-slate-900 text-balance">{{ report.title }}</h4>
            <p class="mt-1 text-sm text-slate-500 text-pretty">{{ report.path }}</p>
          </div>
          <div class="flex flex-wrap gap-3 text-sm text-slate-600">
            <span class="rounded-full bg-slate-100 px-3 py-1">{{ typeLabels[report.type] }}</span>
            <span class="tabular-nums">{{ report.date ?? "未标注日期" }}</span>
            <span class="tabular-nums">{{ new Date(report.updated_at).toLocaleString() }}</span>
            <span class="tabular-nums">{{ formatSize(report.size) }}</span>
          </div>
        </div>
      </RouterLink>
    </div>
  </section>
</template>
