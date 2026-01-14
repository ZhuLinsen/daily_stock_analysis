<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const navItems = [
  { name: "概览", path: "/" },
  { name: "报告", path: "/reports" },
  { name: "配置", path: "/settings" },
];

const isActive = (path: string) => {
  if (path === "/") {
    return route.path === "/";
  }
  return route.path.startsWith(path);
};

const activeIndex = computed(() => navItems.findIndex((item) => isActive(item.path)));
</script>

<template>
  <aside class="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:block">
    <div class="flex h-dvh flex-col px-6 py-6">
      <div class="mb-8">
        <p class="text-xs font-medium uppercase text-slate-400">
          Stock Ops
        </p>
        <h1 class="mt-2 text-2xl font-semibold text-slate-900 text-balance">
          A 股智能分析
        </h1>
        <p class="mt-2 text-sm text-slate-500 text-pretty">
          Web 管理台 · 报告与配置一体化
        </p>
      </div>

      <nav class="flex flex-1 flex-col gap-2">
        <RouterLink
          v-for="(item, index) in navItems"
          :key="item.path"
          :to="item.path"
          class="rounded-xl px-4 py-3 text-sm font-medium"
          :class="
            activeIndex === index
              ? 'bg-indigo-50 text-indigo-700'
              : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
          "
        >
          {{ item.name }}
        </RouterLink>
      </nav>

      <div class="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p class="text-xs font-medium text-slate-500">快捷指引</p>
        <p class="mt-2 text-sm text-slate-600 text-pretty">
          先配置关键环境变量，再查看最新的决策仪表盘与日报。
        </p>
      </div>
    </div>
  </aside>
</template>
