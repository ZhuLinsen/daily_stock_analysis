<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const title = computed(() => {
  switch (route.name) {
    case "reports":
      return "报告中心";
    case "report-detail":
      return "报告详情";
    case "settings":
      return "配置中心";
    default:
      return "运行概览";
  }
});
</script>

<template>
  <header class="sticky top-0 z-20 border-b border-slate-200 bg-white">
    <div class="safe-top px-6">
      <div class="flex items-center justify-between py-4">
        <div>
          <p class="text-xs font-medium text-slate-500">A 股智能分析系统</p>
          <h2 class="text-xl font-semibold text-slate-900 text-balance">{{ title }}</h2>
        </div>
        <div class="flex items-center gap-3">
          <RouterLink
            to="/reports"
            class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700"
          >
            查看报告
          </RouterLink>
          <RouterLink
            to="/settings"
            class="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white"
          >
            配置环境
          </RouterLink>
        </div>
      </div>
      <div class="pb-4 lg:hidden">
        <nav class="grid grid-cols-3 gap-2 text-sm font-medium">
          <RouterLink
            to="/"
            class="rounded-xl border border-slate-200 px-3 py-2 text-center text-slate-600"
            :class="route.path === '/' ? 'bg-indigo-50 text-indigo-700' : 'bg-white'"
          >
            概览
          </RouterLink>
          <RouterLink
            to="/reports"
            class="rounded-xl border border-slate-200 px-3 py-2 text-center text-slate-600"
            :class="route.path.startsWith('/reports') ? 'bg-indigo-50 text-indigo-700' : 'bg-white'"
          >
            报告
          </RouterLink>
          <RouterLink
            to="/settings"
            class="rounded-xl border border-slate-200 px-3 py-2 text-center text-slate-600"
            :class="route.path.startsWith('/settings') ? 'bg-indigo-50 text-indigo-700' : 'bg-white'"
          >
            配置
          </RouterLink>
        </nav>
      </div>
    </div>
  </header>
</template>
