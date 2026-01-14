<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { onBeforeRouteUpdate, useRoute, useRouter } from "vue-router";
import MarkdownRender from "markstream-vue";
import { fetchReport } from "../api";

import 'markstream-vue/index.css'

const route = useRoute();
const router = useRouter();

const loading = ref(true);
const error = ref("");
const content = ref("");
const reportPath = computed(() => String(route.query.path || ""));
const tocItems = ref<{ id: string; text: string }[]>([]);
const markdownRef = ref<HTMLDivElement | null>(null);

const buildToc = (markdown: string) => {
  const lines = markdown.split("\n");
  const items: { id: string; text: string }[] = [];
  const counts = new Map<string, number>();
  lines.forEach((line) => {
    const match = line.match(/^##\s+(.+)/);
    if (!match) return;
    const raw = match[1].trim();
    const cleaned = raw.replace(/[*_`~]/g, "").trim();
    const base = cleaned || "section";
    let slug = base
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, "");
    if (!slug) {
      slug = "section";
    }
    const current = (counts.get(slug) ?? 0) + 1;
    counts.set(slug, current);
    const unique = current > 1 ? `${slug}-${current}` : slug;
    items.push({ id: unique, text: cleaned || raw });
  });
  return items;
};

const applyAnchors = async () => {
  await nextTick();
  const container = markdownRef.value;
  if (!container) return;
  const headings = Array.from(container.querySelectorAll("h2"));
  headings.forEach((heading, index) => {
    const item = tocItems.value[index];
    if (!item) return;
    heading.setAttribute("id", item.id);
  });
};

const scrollToTop = () => {
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
};

const loadReport = async (pathOverride?: string) => {
  const currentPath = pathOverride ?? reportPath.value;
  if (!currentPath) {
    error.value = "缺少报告路径";
    loading.value = false;
    return;
  }

  loading.value = true;
  error.value = "";
  try {
    const response = await fetchReport(currentPath);
    content.value = response.content;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
};

onMounted(loadReport);
onBeforeRouteUpdate((to) => {
  const nextPath = String(to.query.path || "");
  if (nextPath) {
    loadReport(nextPath);
  }
});

watch(content, async (value) => {
  tocItems.value = buildToc(value);
  await applyAnchors();
});
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-2xl font-semibold text-slate-900 text-balance">报告详情</h3>
        <p class="mt-2 text-sm text-slate-600 text-pretty">{{ reportPath }}</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
          @click="router.back()"
        >
          返回
        </button>
        <RouterLink
          to="/reports"
          class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
        >
          报告列表
        </RouterLink>
      </div>
    </div>

    <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <div v-if="loading && !content" class="rounded-2xl border border-slate-200 bg-white p-6">
      <div class="h-6 w-40 rounded bg-slate-100"></div>
      <div class="mt-4 space-y-3">
        <div class="h-4 w-full rounded bg-slate-100"></div>
        <div class="h-4 w-5/6 rounded bg-slate-100"></div>
        <div class="h-4 w-2/3 rounded bg-slate-100"></div>
      </div>
    </div>

    <div v-else class="grid gap-6 lg:grid-cols-3">
      <div class="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 overflow-x-hidden">
        <div ref="markdownRef">
          <MarkdownRender class="markstream-vue text-pretty break-words" :content="content" custom-id="docs" />
        </div>
      </div>
      <aside class="rounded-2xl border border-slate-200 bg-white p-5 lg:col-span-1">
        <h4 class="text-sm font-semibold text-slate-900">目录</h4>
        <div v-if="tocItems.length === 0" class="mt-4 text-sm text-slate-500">
          暂无目录内容
        </div>
        <ul v-else class="mt-4 space-y-2 text-sm text-slate-600">
          <li v-for="item in tocItems" :key="item.id">
            <a class="text-pretty hover:text-slate-900" :href="`#${item.id}`">
              {{ item.text }}
            </a>
          </li>
        </ul>
      </aside>
    </div>

    <button
      type="button"
      aria-label="返回顶部"
      class="fixed bottom-4 right-4 z-30 flex size-11 items-center justify-center rounded-full border border-slate-900 bg-slate-900 text-sm font-medium text-white shadow-lg"
      style="bottom: calc(env(safe-area-inset-bottom) + 1rem)"
      @click="scrollToTop"
    >
      ↑
    </button>
  </section>
</template>
