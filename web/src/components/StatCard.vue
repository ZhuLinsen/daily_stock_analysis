<script setup lang="ts">
defineProps<{ label: string; value: string; subtitle?: string }>();
</script>

<template>
  <div class="rounded-2xl border border-slate-200 bg-white p-5">
    <p class="text-xs font-medium text-slate-500">{{ label }}</p>
    <p class="mt-3 text-2xl font-semibold text-slate-900 tabular-nums">
      {{ value }}
    </p>
    <p v-if="subtitle" class="mt-2 text-sm text-slate-500 text-pretty">
      {{ subtitle }}
    </p>
  </div>
</template>
