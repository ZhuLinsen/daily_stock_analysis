<script setup lang="ts">
import { Tab, TabGroup, TabList, TabPanel, TabPanels } from "@headlessui/vue";
import { computed, onMounted, ref } from "vue";
import {
  fetchConfig,
  saveConfig,
  type ConfigResponse,
  type ConfigValue,
  type ConfigValues,
  type StringMap,
} from "../api";

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const success = ref("");
const config = ref<ConfigResponse | null>(null);

const formValues = ref<ConfigValues>({});
const secretState = ref<StringMap<boolean>>({});
const clearSecrets = ref<StringMap<boolean>>({});
const fieldErrors = ref<StringMap<string>>({});
const activeName = ref("");

const hasConfig = computed(() => Boolean(config.value));
const sections = computed(() => config.value?.sections ?? []);
const selectedIndex = computed(() => {
  const index = sections.value.findIndex((section) => section.id === activeName.value);
  return index >= 0 ? index : 0;
});

const loadConfig = async () => {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetchConfig();
    config.value = response;
    if (response.sections.length > 0 && !activeName.value) {
      activeName.value = response.sections[0].id;
    }
    const values: ConfigValues = {};
    const secrets: StringMap<boolean> = {};
    response.sections.forEach((section) => {
      section.items.forEach((item) => {
        const raw = response.values[item.key];
        if (item.type === "secret" && raw && typeof raw === "object") {
          const data = raw as { isSet: boolean; value: string };
          secrets[item.key] = data.isSet;
          values[item.key] = "";
        } else {
          values[item.key] = raw ?? "";
        }
      });
    });
    formValues.value = values;
    secretState.value = secrets;
    clearSecrets.value = {};
    fieldErrors.value = {};
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
};

const validate = () => {
  const errors: StringMap<string> = {};
  if (!config.value) {
    return errors;
  }
  config.value.sections.forEach((section) => {
    section.items.forEach((item) => {
      const value = formValues.value[item.key];
      if (item.required) {
        if (item.type === "secret") {
          const hasExisting = secretState.value[item.key];
          if (!hasExisting && !value) {
            errors[item.key] = "必填项尚未配置";
          }
        } else if (value === "" || value === null || value === undefined) {
          errors[item.key] = "必填项不能为空";
        }
      }
    });
  });
  fieldErrors.value = errors;
  return errors;
};

const handleSave = async () => {
  success.value = "";
  const errors = validate();
  if (Object.keys(errors).length > 0) {
    return;
  }
  saving.value = true;
  try {
    const clears = Object.keys(clearSecrets.value).filter((key) => clearSecrets.value[key]);
    await saveConfig(formValues.value, clears);
    success.value = "配置已保存";
    await loadConfig();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
};

const handleTabChange = (index: number) => {
  const next = sections.value[index];
  if (next) {
    activeName.value = next.id;
  }
};

const handleTabClick = (sectionId: string, _event: Event) => {
  activeName.value = sectionId;
};

onMounted(loadConfig);
</script>

<template>
  <section class="space-y-6">
    <div>
      <h3 class="text-2xl font-semibold text-slate-900 text-balance">配置中心</h3>
      <p class="mt-2 text-sm text-slate-600 text-pretty">
        管理所有环境变量配置，敏感字段默认隐藏。
      </p>
    </div>

    <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
      {{ error }}
    </div>

    <div v-if="success" class="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-700">
      {{ success }}
    </div>

    <div
      v-if="config"
      class="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600"
    >
      <div class="flex flex-wrap gap-6">
        <div>
          <p class="text-xs font-medium text-slate-500">.env 文件</p>
          <p class="mt-2 text-slate-900">
            {{ config.envFileExists ? "已存在" : "未创建" }}
          </p>
        </div>
        <div>
          <p class="text-xs font-medium text-slate-500">最近更新</p>
          <p class="mt-2 text-slate-900 tabular-nums">
            {{ config.envUpdatedAt ? new Date(config.envUpdatedAt).toLocaleString() : "未记录" }}
          </p>
        </div>
      </div>
    </div>

    <div v-if="loading" class="rounded-2xl border border-slate-200 bg-white p-6">
      <div class="h-6 w-40 rounded bg-slate-100"></div>
      <div class="mt-6 space-y-4">
        <div class="h-20 rounded bg-slate-100"></div>
        <div class="h-20 rounded bg-slate-100"></div>
        <div class="h-20 rounded bg-slate-100"></div>
      </div>
    </div>

    <div v-else-if="hasConfig">
      <TabGroup :selectedIndex="selectedIndex" @change="handleTabChange">
        <div class="border border-slate-200 bg-white">
          <TabList class="flex gap-2 overflow-x-auto border-b border-slate-200 bg-slate-50 px-3 py-2">
            <Tab v-for="section in sections" :key="section.id" as="template" v-slot="{ selected }">
              <button
                type="button"
                class="whitespace-nowrap rounded-xl border px-4 py-2 text-sm font-medium"
                :class="
                  selected
                    ? 'border-slate-200 bg-white text-slate-900 -mb-px'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                "
                @click="handleTabClick(section.id, $event)"
              >
                {{ section.title }}
              </button>
            </Tab>
          </TabList>

          <TabPanels class="p-6">
            <TabPanel v-for="section in sections" :key="section.id">
            <div class="flex flex-col gap-1">
              <h4 class="text-lg font-semibold text-slate-900 text-balance">{{ section.title }}</h4>
              <p v-if="section.description" class="text-sm text-slate-600 text-pretty">
                {{ section.description }}
              </p>
            </div>

            <div class="mt-6 space-y-5">
              <div v-for="item in section.items" :key="item.key" class="space-y-2">
                <div class="flex items-center justify-between">
                  <label class="text-sm font-medium text-slate-800" :for="item.key">
                    {{ item.label }}
                    <span v-if="item.required" class="text-rose-500">*</span>
                  </label>
                  <span
                    v-if="item.type === 'secret' && secretState[item.key]"
                    class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600"
                  >
                    已配置
                  </span>
                </div>

            <input
              v-if="item.type === 'string' || item.type === 'path'"
              :id="item.key"
              :value="String(formValues[item.key] ?? '')"
              @input="formValues[item.key] = ($event.target as HTMLInputElement).value"
              type="text"
              class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900"
            />

            <textarea
              v-else-if="item.type === 'list'"
              :id="item.key"
              :value="String(formValues[item.key] ?? '')"
              @input="formValues[item.key] = ($event.target as HTMLTextAreaElement).value"
              rows="2"
              class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900"
            ></textarea>

                <input
                  v-else-if="item.type === 'number'"
                  :id="item.key"
                  v-model.number="formValues[item.key]"
                  type="number"
                  class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 tabular-nums"
                />

                <div v-else-if="item.type === 'bool'" class="flex items-center gap-3">
                  <input
                    :id="item.key"
                    v-model="formValues[item.key]"
                    type="checkbox"
                    class="size-4 rounded border border-slate-300"
                  />
                  <label :for="item.key" class="text-sm text-slate-600">启用</label>
                </div>

                <div v-else-if="item.type === 'secret'" class="space-y-2">
                  <input
                    :id="item.key"
                    v-model="formValues[item.key]"
                    type="password"
                    autocomplete="new-password"
                    class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900"
                    :placeholder="secretState[item.key] ? '保持现有值，留空即可' : '请输入密钥'"
                  />
                  <div class="flex items-center gap-2">
                    <input
                      :id="`${item.key}-clear`"
                      v-model="clearSecrets[item.key]"
                      type="checkbox"
                      class="size-4 rounded border border-slate-300"
                    />
                    <label :for="`${item.key}-clear`" class="text-xs text-slate-600">清空该密钥</label>
                  </div>
                </div>

                <p v-if="item.help" class="text-xs text-slate-500 text-pretty">
                  {{ item.help }}
                </p>
                <p v-if="fieldErrors[item.key]" class="text-xs text-rose-600">
                  {{ fieldErrors[item.key] }}
                </p>
              </div>
            </div>
            </TabPanel>
          </TabPanels>
        </div>
      </TabGroup>
    </div>

    <div v-if="hasConfig" class="flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
        :disabled="saving"
        @click="handleSave"
      >
        {{ saving ? "保存中..." : "保存配置" }}
      </button>
      <button
        type="button"
        class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"
        :disabled="saving"
        @click="loadConfig"
      >
        重新加载
      </button>
    </div>
  </section>
</template>
