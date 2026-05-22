<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NTag,
  useMessage,
} from "naive-ui";
import { computed, onMounted, reactive, ref } from "vue";

import { getFrontendSettings, saveFrontendSettings, type FrontendSettings } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import FileBrowser from "../components/FileBrowser.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const { backends, loading: configLoading, profiles } = useConfigOptions();
const loading = ref(false);
const saving = ref(false);
const loadedSettings = ref<FrontendSettings | null>(null);

const form = reactive({
  codex_lb_base_url: "",
  codex_lb_api_key: "",
  clear_codex_lb_api_key: false,
  profile: "",
  backend: "",
  remote_concurrency: 2,
  book_name: "",
  chapter: "",
  glossary_file: "",
  model: "",
  reasoning_effort: "high",
  ocr_backend: "codex_api",
  ocr_model: "",
  ocr_reasoning_effort: "high",
});

const reasoningOptions = ["low", "medium", "high", "xhigh"].map((value) => ({
  label: value,
  value,
}));

const ocrBackendOptions = [
  { label: "Codex API", value: "codex_api" },
  { label: "Codex CLI", value: "codex_cli" },
  { label: "Gemini CLI", value: "gemini_cli" },
];

const apiKeyStatus = computed(() => {
  if (form.codex_lb_api_key.trim()) {
    return "本次会写入新 API key";
  }
  if (form.clear_codex_lb_api_key) {
    return "保存后会清除已保存 API key";
  }
  if (loadedSettings.value?.has_codex_lb_api_key) {
    return "已保存或已通过环境变量提供";
  }
  return "尚未配置";
});

function applySettings(settings: FrontendSettings) {
  loadedSettings.value = settings;
  form.codex_lb_base_url = settings.codex_lb_base_url;
  form.codex_lb_api_key = "";
  form.clear_codex_lb_api_key = false;
  form.profile = settings.profile;
  form.backend = settings.backend;
  form.remote_concurrency = settings.remote_concurrency || 2;
  form.book_name = settings.book_name;
  form.chapter = settings.chapter;
  form.glossary_file = settings.glossary_file;
  form.model = settings.model;
  form.reasoning_effort = settings.reasoning_effort;
  form.ocr_backend = settings.ocr_backend || "codex_api";
  form.ocr_model = settings.ocr_model;
  form.ocr_reasoning_effort = settings.ocr_reasoning_effort;
}

async function loadSettings() {
  loading.value = true;
  try {
    applySettings(await getFrontendSettings());
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "加载设置失败");
  } finally {
    loading.value = false;
  }
}

async function saveSettings() {
  saving.value = true;
  try {
    const settings = await saveFrontendSettings({
      codex_lb_base_url: form.codex_lb_base_url,
      codex_lb_api_key: form.codex_lb_api_key || null,
      clear_codex_lb_api_key: form.clear_codex_lb_api_key,
      profile: form.profile || null,
      backend: form.backend || null,
      remote_concurrency: form.remote_concurrency,
      book_name: form.book_name || null,
      chapter: form.chapter || null,
      glossary_file: form.glossary_file || null,
      model: form.model,
      reasoning_effort: form.reasoning_effort,
      ocr_backend: form.ocr_backend,
      ocr_model: form.ocr_model,
      ocr_reasoning_effort: form.ocr_reasoning_effort,
    });
    applySettings(settings);
    message.success("设置已保存");
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "保存设置失败");
  } finally {
    saving.value = false;
  }
}

onMounted(loadSettings);
</script>

<template>
  <n-space vertical :size="20" class="settings-view">
    <section class="view-hero">
      <div>
        <p class="view-hero__eyebrow">运行设置</p>
        <h2 class="view-hero__title">运行默认值</h2>
        <p class="view-hero__copy">任务页只填写输入输出；Profile、后端、OCR、术语表等默认项在这里统一维护。</p>
      </div>
      <n-button type="primary" ghost :loading="loading" @click="loadSettings">刷新</n-button>
    </section>

    <n-alert type="info" title="API key 存储位置">
      API key 会保存到 {{ loadedSettings?.settings_path || "data/jobs/frontend-settings.json" }}。该目录已被 .gitignore 忽略。
    </n-alert>

    <n-grid :cols="2" :x-gap="18" :y-gap="18" responsive="screen" item-responsive>
      <n-grid-item span="2 m:1">
        <n-card title="codex-lb 连接" class="view-card settings-card">
          <n-form label-placement="top">
            <n-form-item label="Base URL">
              <n-input
                v-model:value="form.codex_lb_base_url"
                placeholder="http://127.0.0.1:2455 或 https://你的反代域名"
              />
            </n-form-item>
            <n-form-item label="API Key">
              <n-input
                v-model:value="form.codex_lb_api_key"
                type="password"
                show-password-on="click"
                placeholder="留空则保持现有 key"
              />
            </n-form-item>
            <div class="settings-card__meta">
              <n-tag :type="loadedSettings?.has_codex_lb_api_key ? 'success' : 'warning'" round>
                {{ apiKeyStatus }}
              </n-tag>
              <n-button text type="error" @click="form.clear_codex_lb_api_key = !form.clear_codex_lb_api_key">
                {{ form.clear_codex_lb_api_key ? "取消清除" : "清除已保存 key" }}
              </n-button>
            </div>
          </n-form>
        </n-card>
      </n-grid-item>

      <n-grid-item span="2 m:1">
        <n-card title="流水线默认值" class="view-card settings-card">
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="12" responsive="screen" item-responsive>
              <n-grid-item span="2 m:1">
                <n-form-item label="配置 Profile">
                  <ProfileSelector v-model="form.profile" :options="profiles" :loading="configLoading" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2 m:1">
                <n-form-item label="推理后端">
                  <BackendSelector v-model="form.backend" :options="backends" :loading="configLoading" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2 m:1">
                <n-form-item label="批量远程并发度">
                  <n-input-number v-model:value="form.remote_concurrency" :min="1" :precision="0" class="w-full" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2">
                <n-form-item label="术语词表">
                  <FileBrowser v-model="form.glossary_file" mode="file" label="术语词表" button-text="选择术语词表" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2 m:1">
                <n-form-item label="书籍名称">
                  <n-input v-model:value="form.book_name" placeholder="可选，用于最终文件名和 ASR 提示词" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2 m:1">
                <n-form-item label="章节名称">
                  <n-input v-model:value="form.chapter" placeholder="可选，用于最终文件名和 ASR 提示词" />
                </n-form-item>
              </n-grid-item>
            </n-grid>
          </n-form>
        </n-card>
      </n-grid-item>

      <n-grid-item span="2 m:1">
        <n-card title="模型默认值" class="view-card settings-card">
          <n-form label-placement="top">
            <n-form-item label="阶段 6 模型">
              <n-input v-model:value="form.model" placeholder="gpt-5.5" />
            </n-form-item>
            <n-form-item label="阶段 6 推理模式">
              <n-select v-model:value="form.reasoning_effort" :options="reasoningOptions" />
            </n-form-item>
            <n-form-item label="PDF OCR 模型">
              <n-input v-model:value="form.ocr_model" placeholder="gpt-5.4-mini" />
            </n-form-item>
            <n-form-item label="PDF OCR 后端">
              <n-select v-model:value="form.ocr_backend" :options="ocrBackendOptions" />
            </n-form-item>
            <n-form-item label="PDF OCR 推理模式">
              <n-select v-model:value="form.ocr_reasoning_effort" :options="reasoningOptions" />
            </n-form-item>
          </n-form>
        </n-card>
      </n-grid-item>
    </n-grid>

    <div class="settings-actions">
      <n-button type="primary" size="large" :loading="saving" @click="saveSettings">保存设置</n-button>
    </div>
  </n-space>
</template>

<style scoped>
.w-full {
  width: 100%;
}
</style>
