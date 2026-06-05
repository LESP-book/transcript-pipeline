<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NFlex,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  useMessage,
} from "naive-ui";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import { getJob, getRefineDefaultInstruction, type JobState, submitJob } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import JobStatusCard from "../components/JobStatusCard.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import RemoteFileUpload from "../components/RemoteFileUpload.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const { activeProfile, backends, defaultOutputDir, error, loading, profiles, referenceExtensions, videoExtensions } = useConfigOptions();
const jobState = ref<JobState | null>(null);
const submitting = ref(false);
const promptLoading = ref(false);
const defaultRefinePrompt = ref("");
const pollHandle = ref<number | null>(null);

const form = reactive({
  video: "",
  reference: "",
  output_dir: "",
  profile: "",
  backend: "",
  ocr_backend: "",
  book_name: "",
  chapter: "",
  glossary_file: "",
  refine_prompt: "",
});

const ocrBackendOptions = [
  { label: "Codex API", value: "codex_api" },
  { label: "Codex CLI", value: "codex_cli" },
  { label: "Gemini CLI", value: "gemini_cli" },
];
const videoAccept = computed(() => videoExtensions.value.join(","));
const referenceAccept = computed(() => referenceExtensions.value.join(","));
const glossaryAccept = ".txt,.md";

watch(activeProfile, (value) => {
  if (!form.profile && value) {
    form.profile = value;
  }
});

watch(defaultOutputDir, (value) => {
  if (!form.output_dir && value) {
    form.output_dir = value;
  }
});

function stopPolling() {
  if (pollHandle.value !== null) {
    window.clearInterval(pollHandle.value);
    pollHandle.value = null;
  }
}

async function refreshJob(jobId: string) {
  const state = await getJob(jobId);
  jobState.value = state;
  if (state.status === "success" || state.status === "failed") {
    stopPolling();
  }
}

function startPolling(jobId: string) {
  stopPolling();
  pollHandle.value = window.setInterval(() => {
    void refreshJob(jobId).catch((caught) => {
      message.error(caught instanceof Error ? caught.message : "刷新任务状态失败");
      stopPolling();
    });
  }, 2000);
}

function effectiveRefinePrompt(): string | null {
  const currentPrompt = form.refine_prompt.trim();
  if (!currentPrompt || currentPrompt === defaultRefinePrompt.value.trim()) {
    return null;
  }
  return form.refine_prompt;
}

function resetRefinePrompt() {
  form.refine_prompt = defaultRefinePrompt.value;
}

async function loadDefaultRefinePrompt() {
  promptLoading.value = true;
  try {
    const response = await getRefineDefaultInstruction();
    defaultRefinePrompt.value = response.prompt;
    if (!form.refine_prompt.trim()) {
      form.refine_prompt = response.prompt;
    }
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "读取阶段六默认指令失败");
  } finally {
    promptLoading.value = false;
  }
}

async function handleJobRerun(jobId: string) {
  await refreshJob(jobId);
  startPolling(jobId);
}

async function submit() {
  if (!form.video || !form.reference || !form.output_dir) {
    message.warning("视频、参考源和服务器默认输出目录是必填项。");
    return;
  }
  submitting.value = true;
  try {
    const response = await submitJob({
      video: form.video,
      reference: form.reference,
      output_dir: form.output_dir,
      profile: form.profile || null,
      backend: form.backend || null,
      ocr_backend: form.ocr_backend || null,
      book_name: form.book_name || null,
      chapter: form.chapter || null,
      glossary_file: form.glossary_file || null,
      refine_prompt: effectiveRefinePrompt(),
    });
    await refreshJob(response.job_id);
    startPolling(response.job_id);
    message.success(`任务已成功提交：${response.job_id}`);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "提交失败");
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  void loadDefaultRefinePrompt();
});
onBeforeUnmount(stopPolling);
</script>

<template>
  <n-space vertical :size="24">
    <!-- Premium Title Banner -->
    <section class="view-hero">
      <div>
        <p class="view-hero__eyebrow">任务控制台</p>
        <h2 class="view-hero__title">单任务整理流水线</h2>
        <p class="view-hero__copy">
          在这里提交单个读书会录屏视频，系统将按顺序执行提取音频、语音转写、参考文本提取、智能校对润色及 Markdown 最终稿的导出。
        </p>
      </div>
    </section>

    <n-alert v-if="error" type="error" :title="error" :bordered="false" class="glass-alert" />

    <n-card class="view-card form-panel" :bordered="false">
      <template #header>
        <n-flex align="center" :size="10">
          <div class="panel-header-icon">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:20px;height:20px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
          </div>
          <span>新建流水线任务</span>
        </n-flex>
      </template>

      <n-form label-placement="top">
        <n-grid :cols="2" :x-gap="20" :y-gap="4" responsive="screen" item-responsive>
          <n-grid-item span="2 m:1">
            <div class="form-section">
              <h4 class="form-section-title">核心输入输出参数</h4>
              <n-form-item label="视频文件 (Video Source)" required>
                <n-space vertical class="w-full">
                  <RemoteFileUpload
                    v-model="form.video"
                    kind="video"
                    label="视频文件"
                    :accept="videoAccept"
                    button-text="选择并上传本机视频"
                  />
                  <n-input v-model:value="form.video" readonly placeholder="上传后自动生成服务器路径" />
                </n-space>
              </n-form-item>
              <n-form-item label="参考源文件或 URL (Reference)" required>
                <n-space vertical class="w-full">
                  <n-input v-model:value="form.reference" placeholder="可粘贴 https:// 网址，或上传本机参考文件" />
                  <RemoteFileUpload
                    v-model="form.reference"
                    kind="reference"
                    label="参考源文件"
                    :accept="referenceAccept"
                    button-text="选择并上传本机参考源"
                  />
                </n-space>
              </n-form-item>
              <n-form-item label="成果获取方式" required>
                <n-alert type="info" :bordered="false" class="server-output-note">
                  <div class="server-output-note__body">
                    <span>处理完成后，到任务列表点击“下载结果”获取最终 Markdown。</span>
                    <small>服务器默认保存目录：{{ form.output_dir || "配置加载中..." }}</small>
                  </div>
                </n-alert>
              </n-form-item>
            </div>
          </n-grid-item>

          <n-grid-item span="2 m:1">
            <div class="form-section">
              <h4 class="form-section-title">流水线配置</h4>
              <n-grid :cols="2" :x-gap="12" :y-gap="0" responsive="screen" item-responsive>
                <n-grid-item span="2">
                  <n-form-item label="术语词表 (Glossary File)">
                    <n-space vertical class="w-full">
                      <RemoteFileUpload
                        v-model="form.glossary_file"
                        kind="glossary"
                        label="术语词表"
                        :accept="glossaryAccept"
                        button-text="选择并上传本机词表"
                      />
                      <n-input v-model:value="form.glossary_file" readonly placeholder="可选，上传后自动生成服务器路径" />
                    </n-space>
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="配置 Profile">
                    <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="推理后端 (Backend)">
                    <BackendSelector v-model="form.backend" :options="backends" :loading="loading" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="PDF OCR 后端">
                    <n-select
                      v-model:value="form.ocr_backend"
                      :options="ocrBackendOptions"
                      clearable
                      placeholder="使用默认 OCR 后端"
                    />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="书籍名称 (Book Name)">
                    <n-input v-model:value="form.book_name" placeholder="例如：《Lesp 读书会》" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2">
                  <n-form-item label="章节名称 (Chapter)">
                    <n-input v-model:value="form.chapter" placeholder="例如：第 1 章 导言" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2">
                  <n-form-item label="阶段六指令 (Refine Prompt)">
                    <n-space vertical class="w-full">
                      <n-input
                        v-model:value="form.refine_prompt"
                        type="textarea"
                        :autosize="{ minRows: 10, maxRows: 18 }"
                        :loading="promptLoading"
                        placeholder="读取默认阶段六指令中..."
                      />
                      <n-flex justify="space-between" align="center" :size="12" wrap>
                        <span class="prompt-hint">文本框内为当前默认指令，可直接在此基础上调整；不修改时提交会使用项目默认指令。</span>
                        <n-button size="small" secondary :disabled="!defaultRefinePrompt" @click="resetRefinePrompt">
                          恢复默认指令
                        </n-button>
                      </n-flex>
                    </n-space>
                  </n-form-item>
                </n-grid-item>
              </n-grid>
            </div>
          </n-grid-item>
        </n-grid>

        <n-flex justify="end" class="form-action-area">
          <n-button type="primary" size="large" :loading="submitting" @click="submit" class="submit-btn">
            <template #icon>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </template>
            一键开启整理流水线
          </n-button>
        </n-flex>
      </n-form>
    </n-card>

    <!-- Visual status result -->
    <JobStatusCard v-if="jobState" title="流水线当前实时状态" :state="jobState" default-expanded @rerun="handleJobRerun" />
  </n-space>
</template>

<style scoped>
.form-panel {
  padding: 8px 12px;
}

.panel-header-icon {
  background: var(--primary-alpha-10);
  color: var(--primary);
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.form-section {
  background: rgba(248, 250, 252, 0.4);
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.6);
  height: 100%;
}

.form-section-title {
  margin: 0 0 16px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  border-left: 3px solid var(--primary);
  padding-left: 8px;
}

.server-output-note {
  width: 100%;
  border-radius: 8px;
}

.server-output-note__body {
  display: grid;
  gap: 6px;
}

.server-output-note__body span {
  color: var(--text-primary);
  font-weight: 600;
}

.server-output-note__body small {
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.form-action-area {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
}

.submit-btn {
  border-radius: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  box-shadow: 0 4px 14px 0 rgba(79, 70, 229, 0.35);
  transition: all 0.3s ease;
}
.submit-btn:hover {
  box-shadow: 0 6px 20px 0 rgba(79, 70, 229, 0.45);
  transform: translateY(-1px);
}

.glass-alert {
  backdrop-filter: blur(8px);
  background: rgba(254, 242, 242, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 12px;
}

.w-full {
  width: 100%;
}

.prompt-hint {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}
</style>
