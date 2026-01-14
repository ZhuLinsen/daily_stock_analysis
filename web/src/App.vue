<script setup lang="ts">
import Sidebar from "./components/Sidebar.vue";
import TopBar from "./components/TopBar.vue";
</script>

<template>
  <div class="min-h-dvh bg-slate-50 text-slate-900">
    <div class="flex min-h-dvh">
      <Sidebar />
      <div class="flex min-h-dvh flex-1 flex-col">
        <TopBar />
        <main class="flex-1 px-6 py-6 text-pretty">
          <RouterView />
        </main>
      </div>
    </div>
  </div>
</template>
