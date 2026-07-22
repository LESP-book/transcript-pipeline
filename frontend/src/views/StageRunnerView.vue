<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NFlex,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NTag,
  useMessage,
} from "naive-ui";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import {
  getStageFileContract,
  getStageRun,
  listStageRuns,
  stageFileResultUrl,
  submitStageFileRun,
  submitStageRun,
  type JobState,
  type StageFileContract,
  type StageRunPayload,
} from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import JobStatusCard from "../components/JobStatusCard.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import StageFileUpload from "../components/StageFileUpload.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const {
  backends,
  error: configError,
  loading: configLoading,
  profiles,
  defaultOcrBackend,
  defaultOcrMaxConcurrency,
  defaultOcrModel,
  defaultOcrReasoningEffort,
  defaultOcrSubmitIntervalSeconds,
} = useConfigOptions();
const stageState = ref<JobState | null>(null);
const submitting = ref(false);
const historyLoading = ref(false);
const stageRuns = ref<JobState[]>([]);
const pollHandle = ref<number | null>(null);
const runMode = ref<"file" | "directory">("file");
const fileContractLoading = ref(false);
const fileContract = ref<StageFileContract | null>(null);
const fileInputPaths = reactive<Record<string, string>>({});
const fileResultName = ref("");

const form = reactive({
  stage: "extract-audio",
  profile: "",
  backend: "",
  model: "",
  reasoning_effort: "",
  ocr_backend: "",
  ocr_model: "",
  ocr_reasoning_effort: "",
  ocr_max_concurrency: 40 as number | null,
  ocr_submit_interval_seconds: 5 as number | null,
});

interface StageGuide {
  label: string;
  value: string;
  description: string;
  input: string;
  output: string;
  testHint: string;
}

const stageGuides: StageGuide[] = [
  {
    label: "音频提取 (extract-audio)",
    value: "extract-audio",
    description: "从当前视频目录提取统一格式的音频。",
    input: "data/input/videos/",
    output: "data/input/audio/",
    testHint: "适合检查视频扫描、ffmpeg 可用性与音频产物。",
  },
  {
    label: "语音转写 (transcribe)",
    value: "transcribe",
    description: "对当前音频目录执行 ASR 转录。",
    input: "data/input/audio/",
    output: "data/intermediate/asr/",
    testHint: "适合检查 ASR Profile、模型与转录中间结果。",
  },
  {
    label: "准备参考 (prepare-reference)",
    value: "prepare-reference",
    description: "提取当前参考目录中的 TXT、Markdown 或 PDF 原文。",
    input: "data/input/reference/",
    output: "data/intermediate/extracted_text/ 与 data/intermediate/ocr/",
    testHint: "测试 PDF OCR 时，在这里覆盖 OCR 后端、模型和推理强度。",
  },
  {
    label: "文本对齐 (align)",
    value: "align",
    description: "将 ASR 文本与参考原文做块级对齐。",
    input: "data/intermediate/asr/ 与 data/intermediate/extracted_text/",
    output: "data/intermediate/aligned/",
    testHint: "适合验证参考文本与转录是否可作为对齐输入。",
  },
  {
    label: "段落分类 (classify)",
    value: "classify",
    description: "对已对齐文本生成保守候选分类。",
    input: "data/intermediate/aligned/",
    output: "data/intermediate/classified/",
    testHint: "适合检查分类规则与中间 JSON。",
  },
  {
    label: "智能润色 (refine)",
    value: "refine",
    description: "基于 ASR 和参考原文执行阶段 6 精修。",
    input: "data/intermediate/asr/ 与 data/intermediate/extracted_text/",
    output: "data/intermediate/refined/",
    testHint: "测试模型或推理后端时，在这里覆盖推理后端、模型和推理强度。",
  },
  {
    label: "导出文档 (export-markdown)",
    value: "export-markdown",
    description: "将精修结果导出为最终 Markdown 和文本文件。",
    input: "data/intermediate/refined/",
    output: "data/final/",
    testHint: "适合检查最终稿导出和文件命名。",
  },
];

const stageOptions = stageGuides.map(({ label, value }) => ({ label, value }));
const currentStageGuide = computed(() => stageGuides.find((guide) => guide.value === form.stage) ?? stageGuides[0]);
const isFileMode = computed(() => runMode.value === "file");
const usesOcrOverrides = computed(() => form.stage === "prepare-reference");
const usesRefineOverrides = computed(() => form.stage === "refine");
const ocrBackendOptions = [
  { label: "Codex API", value: "codex_api" },
  { label: "agy（Gemini）", value: "agy" },
  { label: "Codex CLI", value: "codex_cli" },
];
const reasoningOptions = ["low", "medium", "high", "xhigh"].map((value) => ({ label: value, value }));
const modelOptions = [
  { label: "GPT-5.6 Sol", value: "gpt-5.6-sol" },
  { label: "GPT-5.6 Terra", value: "gpt-5.6-terra" },
  { label: "GPT-5.6 Luna", value: "gpt-5.6-luna" },
  { label: "GPT-5.5", value: "gpt-5.5" },
  { label: "GPT-5.4", value: "gpt-5.4" },
  { label: "GPT-5.4 mini", value: "gpt-5.4-mini" },
];

function stopPolling() {
  if (pollHandle.value !== null) {
    window.clearInterval(pollHandle.value);
    pollHandle.value = null;
  }
}

function isActiveStageRun(state: JobState): boolean {
  return state.status === "pending" || state.status === "running";
}

function stageRunStatusType(status: string): "success" | "error" | "warning" {
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  return "warning";
}

async function loadStageRuns() {
  historyLoading.value = true;
  try {
    stageRuns.value = (await listStageRuns()).items;
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "加载单阶段运行历史失败");
  } finally {
    historyLoading.value = false;
  }
}

async function refreshStage(runId: string) {
  const state = await getStageRun(runId);
  stageState.value = state;
  if (state.status === "success" || state.status === "partial" || state.status === "failed") {
    stopPolling();
    void loadStageRuns();
  }
}

function startPolling(runId: string) {
  stopPolling();
  pollHandle.value = window.setInterval(() => {
    void refreshStage(runId).catch((caught) => {
      message.error(caught instanceof Error ? caught.message : "刷新阶段任务状态失败");
      stopPolling();
    });
  }, 2000);
}

async function loadStageRun(runId: string) {
  try {
    await refreshStage(runId);
    if (stageState.value && isActiveStageRun(stageState.value)) {
      startPolling(runId);
    }
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "加载单阶段运行状态失败");
  }
}

function optionalValue(value: string): string | null {
  return value.trim() || null;
}

function buildStageRunPayload(): StageRunPayload {
  const payload: StageRunPayload = {
    profile: optionalValue(form.profile),
  };
  if (usesOcrOverrides.value) {
    payload.ocr_backend = optionalValue(form.ocr_backend);
    payload.ocr_model = optionalValue(form.ocr_model);
    payload.ocr_reasoning_effort = optionalValue(form.ocr_reasoning_effort);
    payload.ocr_max_concurrency = form.ocr_max_concurrency;
    payload.ocr_submit_interval_seconds = form.ocr_submit_interval_seconds;
  }
  if (usesRefineOverrides.value) {
    payload.backend = optionalValue(form.backend);
    payload.model = optionalValue(form.model);
    payload.reasoning_effort = optionalValue(form.reasoning_effort);
  }
  return payload;
}

function clearFileInputs() {
  Object.keys(fileInputPaths).forEach((key) => {
    delete fileInputPaths[key];
  });
}

async function loadFileContract() {
  clearFileInputs();
  fileContract.value = null;
  fileContractLoading.value = true;
  try {
    const response = await getStageFileContract(form.stage);
    fileContract.value = response;
    fileResultName.value = response.default_result_name;
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "加载阶段文件输入要求失败");
  } finally {
    fileContractLoading.value = false;
  }
}

function downloadStageFileResult() {
  const state = stageState.value;
  if (!state || state.run_mode !== "file" || state.status !== "success") {
    return;
  }
  window.location.assign(stageFileResultUrl(state.id));
}

async function submit() {
  if (
    usesOcrOverrides.value
    && (form.ocr_max_concurrency === null || form.ocr_submit_interval_seconds === null)
  ) {
    message.warning("请填写 PDF OCR 投递间隔和最大并发数。");
    return;
  }
  if (isFileMode.value) {
    if (!fileContract.value) {
      message.warning("阶段文件输入要求尚未加载完成。");
      return;
    }
    const missingSlots = fileContract.value.input_slots.filter((slot) => !fileInputPaths[slot.key]);
    if (missingSlots.length > 0) {
      message.warning(`请先选择${missingSlots.map((slot) => slot.label).join("、")}。`);
      return;
    }
    if (!fileResultName.value.trim()) {
      message.warning("请填写结果归档名称。");
      return;
    }
  }

  submitting.value = true;
  try {
    const payload = buildStageRunPayload();
    const response = isFileMode.value && fileContract.value
      ? await submitStageFileRun(form.stage, {
        ...payload,
        input_files: Object.fromEntries(
          fileContract.value.input_slots.map((slot) => [slot.key, fileInputPaths[slot.key]]),
        ),
        result_name: fileResultName.value.trim(),
      })
      : await submitStageRun(form.stage, payload);
    await refreshStage(response.run_id);
    await loadStageRuns();
    if (stageState.value && isActiveStageRun(stageState.value)) {
      startPolling(response.run_id);
    }
    message.success(`阶段任务已成功提交：${response.run_id}`);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "提交失败");
  } finally {
    submitting.value = false;
  }
}

watch(
  () => form.stage,
  () => {
    if (isFileMode.value) {
      void loadFileContract();
    }
  },
);

watch(defaultOcrBackend, (value) => {
  if (!form.ocr_backend && value) {
    form.ocr_backend = value;
  }
});
watch(defaultOcrModel, (value) => {
  if (!form.ocr_model && value) {
    form.ocr_model = value;
  }
});
watch(defaultOcrReasoningEffort, (value) => {
  if (!form.ocr_reasoning_effort && value) {
    form.ocr_reasoning_effort = value;
  }
});
watch(defaultOcrMaxConcurrency, (value) => {
  if (Number.isFinite(value)) {
    form.ocr_max_concurrency = value;
  }
});
watch(defaultOcrSubmitIntervalSeconds, (value) => {
  if (Number.isFinite(value)) {
    form.ocr_submit_interval_seconds = value;
  }
});

async function handleStageRunRetry(runId: string) {
  await refreshStage(runId);
  startPolling(runId);
}

watch(runMode, (mode) => {
  if (mode === "file") {
    void loadFileContract();
  }
});

onMounted(() => {
  void loadStageRuns();
  void loadFileContract();
});

onBeforeUnmount(stopPolling);
</script>

<template>
  <n-space vertical :size="24">
    <!-- Premium Title Banner -->
    <section class="view-hero">
      <div>
        <p class="view-hero__eyebrow">任务控制台</p>
        <h2 class="view-hero__title">单阶段手动触发</h2>
        <p class="view-hero__copy">
          适合高级调试、流程中断恢复或人工干预场景。允许手动指定运行特定的流水线单个节点任务，例如在已提取音频后仅手动触发语音转写。
        </p>
      </div>
    </section>

    <n-alert v-if="isFileMode" type="info" title="本机文件测试模式" :bordered="false" class="file-mode-alert">
      选择的文件只会复制到本次运行的隔离工作区；完成后以 ZIP 下载，不会写入当前配置目录。
    </n-alert>
    <n-alert v-else type="warning" title="全局目录运行警告" :bordered="false" class="warn-alert">
      目录模式会直接对当前系统配置目录下的数据执行对应处理阶段。
    </n-alert>
    <n-alert v-if="configError" type="error" :title="configError" :bordered="false" class="warn-alert" />

    <n-card class="view-card form-panel" :bordered="false">
      <template #header>
        <n-flex align="center" :size="10">
          <div class="panel-header-icon is-stage">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:20px;height:20px"><polygon points="6 2 18 2 18 6 6 6 6 2"/><rect x="3" y="6" width="18" height="16" rx="2"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
          </div>
          <span>触发单阶段处理</span>
        </n-flex>
      </template>

      <n-form label-placement="top">
        <n-space vertical :size="14">
          <n-form-item label="要运行的指定流水线阶段 (Pipeline Stage)">
            <n-select v-model:value="form.stage" :options="stageOptions" class="w-full select-stage" />
          </n-form-item>

          <section class="run-mode-panel">
            <div>
              <h3>运行方式</h3>
              <p>文件模式用于单个输入测试；目录模式保留原有批处理行为。</p>
            </div>
            <n-radio-group v-model:value="runMode" name="stage-run-mode">
              <n-radio-button value="file">本机文件</n-radio-button>
              <n-radio-button value="directory">当前配置目录</n-radio-button>
            </n-radio-group>
          </section>

          <section class="stage-guide">
            <n-flex justify="space-between" align="center" :size="10" wrap>
              <div>
                <p class="stage-guide__eyebrow">当前测试阶段</p>
                <h3>{{ currentStageGuide.label }}</h3>
              </div>
              <n-tag :type="isFileMode ? 'success' : 'info'" :bordered="false">
                {{ isFileMode ? "隔离工作区" : "当前配置目录" }}
              </n-tag>
            </n-flex>
            <p class="stage-guide__description">
              {{ isFileMode ? "本次运行只处理下方选择的文件，原有全局目录不会参与。" : currentStageGuide.description }}
            </p>
            <div v-if="!isFileMode" class="stage-guide__paths">
              <div>
                <span>输入</span>
                <code>{{ currentStageGuide.input }}</code>
              </div>
              <div>
                <span>输出</span>
                <code>{{ currentStageGuide.output }}</code>
              </div>
            </div>
            <p class="stage-guide__hint">
              {{ isFileMode ? "结果会被打包为 ZIP，由浏览器下载到你选择的本机位置。" : currentStageGuide.testHint }}
            </p>
          </section>

          <section v-if="isFileMode" class="file-input-panel">
            <div class="override-panel__heading">
              <div>
                <h3>本次文件输入与输出</h3>
                <p>按当前阶段选择所需文件；文件仅在本次运行结束前保存在隔离工作区。</p>
              </div>
              <n-tag size="small" :bordered="false" type="success">结果下载</n-tag>
            </div>

            <n-alert v-if="fileContractLoading" type="info" :bordered="false">
              正在读取当前阶段的文件要求…
            </n-alert>
            <n-alert v-else-if="!fileContract" type="error" :bordered="false">
              无法读取文件输入要求，请重新选择阶段或刷新页面。
            </n-alert>
            <n-grid v-else :cols="2" :x-gap="12" :y-gap="0" responsive="screen" item-responsive>
              <n-grid-item v-for="slot in fileContract.input_slots" :key="slot.key" span="2 m:1">
                <n-form-item :label="slot.label" required>
                  <StageFileUpload
                    v-model="fileInputPaths[slot.key]"
                    :stage-name="form.stage"
                    :slot="slot"
                  />
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2">
                <n-form-item label="结果归档名称" required>
                  <n-input v-model:value="fileResultName" placeholder="例如 lesson-asr">
                    <template #suffix>.zip</template>
                  </n-input>
                </n-form-item>
              </n-grid-item>
            </n-grid>
          </section>

          <section class="override-panel">
            <div class="override-panel__heading">
              <div>
                <h3>本次运行覆盖</h3>
                <p>留空即使用设置页中的默认值；本页选择不会保存为全局设置。</p>
              </div>
              <n-tag size="small" :bordered="false" type="success">仅本次生效</n-tag>
            </div>

            <n-grid :cols="2" :x-gap="12" :y-gap="0" responsive="screen" item-responsive>
              <n-grid-item span="2 m:1">
                <n-form-item label="配置 Profile">
                  <ProfileSelector v-model="form.profile" :options="profiles" :loading="configLoading" />
                </n-form-item>
              </n-grid-item>

              <template v-if="usesOcrOverrides">
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
                  <n-form-item label="PDF OCR 模型">
                    <n-select
                      v-model:value="form.ocr_model"
                      :options="modelOptions"
                      clearable
                      placeholder="使用默认 OCR 模型"
                    />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2">
                  <n-form-item label="PDF OCR 推理强度">
                    <n-select
                      v-model:value="form.ocr_reasoning_effort"
                      :options="reasoningOptions"
                      clearable
                      placeholder="使用默认 OCR 推理强度"
                    />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="页面投递间隔（秒）" required>
                    <n-input-number
                      v-model:value="form.ocr_submit_interval_seconds"
                      :min="0"
                      :step="0.5"
                      class="w-full"
                    />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="最大在途请求数" required>
                    <n-input-number
                      v-model:value="form.ocr_max_concurrency"
                      :min="1"
                      :precision="0"
                      class="w-full"
                    />
                  </n-form-item>
                </n-grid-item>
              </template>

              <template v-else-if="usesRefineOverrides">
                <n-grid-item span="2 m:1">
                  <n-form-item label="推理后端">
                    <BackendSelector v-model="form.backend" :options="backends" :loading="configLoading" />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2 m:1">
                  <n-form-item label="阶段 6 模型">
                    <n-select
                      v-model:value="form.model"
                      :options="modelOptions"
                      clearable
                      placeholder="使用默认阶段 6 模型"
                    />
                  </n-form-item>
                </n-grid-item>
                <n-grid-item span="2">
                  <n-form-item label="阶段 6 推理强度">
                    <n-select
                      v-model:value="form.reasoning_effort"
                      :options="reasoningOptions"
                      clearable
                      placeholder="使用默认阶段 6 推理强度"
                    />
                  </n-form-item>
                </n-grid-item>
              </template>
            </n-grid>
          </section>

          <n-flex justify="end" class="form-action-area">
            <n-button type="primary" size="large" :loading="submitting" @click="submit" class="submit-btn is-stage-btn">
              <template #icon>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </template>
              {{ isFileMode ? "运行并生成下载包" : "运行当前目录阶段" }}
            </n-button>
          </n-flex>
        </n-space>
      </n-form>
    </n-card>

    <n-card class="view-card history-panel" :bordered="false">
      <template #header>
        <n-flex justify="space-between" align="center" :size="12" wrap>
          <div>
            <span>单阶段运行历史</span>
            <p class="history-panel__copy">选择任一记录可恢复状态查看；运行中的记录会继续刷新。</p>
          </div>
          <n-button size="small" secondary :loading="historyLoading" @click="loadStageRuns">刷新历史</n-button>
        </n-flex>
      </template>

      <n-empty v-if="!historyLoading && stageRuns.length === 0" description="还没有单阶段运行记录。" />
      <div v-else class="stage-history-list">
        <button
          v-for="run in stageRuns"
          :key="run.id"
          type="button"
          class="stage-history-item"
          :class="{ 'is-selected': stageState?.id === run.id }"
          @click="loadStageRun(run.id)"
        >
          <div class="stage-history-item__main">
            <strong>{{ run.current_stage }}</strong>
            <span>{{ run.id }}</span>
          </div>
          <div class="stage-history-item__meta">
            <n-tag v-if="run.run_mode === 'file'" size="small" type="info" :bordered="false">文件模式</n-tag>
            <n-tag size="small" :type="stageRunStatusType(run.status)" :bordered="false">{{ run.status }}</n-tag>
            <span>{{ run.updated_at }}</span>
          </div>
        </button>
      </div>
    </n-card>

    <n-card
      v-if="stageState?.run_mode === 'file' && stageState.status === 'success' && stageState.download_name"
      class="view-card file-result-panel"
      :bordered="false"
    >
      <n-flex justify="space-between" align="center" :size="12" wrap>
        <div>
          <h3>文件模式结果已就绪</h3>
          <p>{{ stageState.download_name }} 已在本次隔离工作区生成。</p>
        </div>
        <n-button type="primary" @click="downloadStageFileResult">下载结果 ZIP</n-button>
      </n-flex>
    </n-card>

    <!-- Visual status card for run progress -->
    <JobStatusCard
      v-if="stageState"
      title="阶段任务执行状态报告"
      :state="stageState"
      default-expanded
      @rerun="handleStageRunRetry"
    />
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

.panel-header-icon.is-stage {
  background: rgba(45, 212, 191, 0.1);
  color: #0d9488;
}

.form-action-area {
  margin-top: 14px;
  padding-top: 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
}

.select-stage :deep(.n-base-selection) {
  font-weight: 700;
  color: var(--primary) !important;
}

.stage-guide,
.override-panel,
.run-mode-panel,
.file-input-panel,
.file-result-panel {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 16px;
  background: rgba(248, 250, 252, 0.72);
}

.run-mode-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.run-mode-panel h3,
.file-input-panel h3,
.file-result-panel h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 16px;
}

.run-mode-panel p,
.file-input-panel p,
.file-result-panel p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.history-panel__copy {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 400;
}

.stage-history-list {
  display: grid;
  gap: 8px;
}

.stage-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.72);
  color: inherit;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.stage-history-item:hover,
.stage-history-item.is-selected {
  border-color: var(--primary);
  background: var(--primary-alpha-10);
}

.stage-history-item__main,
.stage-history-item__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.stage-history-item__main strong {
  color: var(--text-primary);
}

.stage-history-item__main span,
.stage-history-item__meta span {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-guide__eyebrow {
  margin: 0 0 4px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.stage-guide h3,
.override-panel h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 16px;
}

.stage-guide__description,
.stage-guide__hint,
.override-panel p {
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.stage-guide__paths {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.stage-guide__paths > div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.7);
}

.stage-guide__paths span {
  color: var(--text-muted);
  font-size: 12px;
}

.stage-guide__paths code {
  color: var(--primary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.stage-guide__hint {
  color: #0f766e;
}

.override-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.submit-btn {
  border-radius: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  box-shadow: 0 4px 14px 0 rgba(79, 70, 229, 0.35);
  transition: all 0.3s ease;
}

.submit-btn.is-stage-btn {
  box-shadow: 0 4px 14px 0 rgba(13, 148, 136, 0.3);
  background-color: #0d9488;
}
.submit-btn.is-stage-btn:hover {
  box-shadow: 0 6px 20px 0 rgba(13, 148, 136, 0.45);
  background-color: #0f766e;
  transform: translateY(-1px);
}

.glass-alert {
  backdrop-filter: blur(8px);
  background: rgba(254, 242, 242, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 12px;
}

.warn-alert {
  background: rgba(254, 243, 199, 0.6);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 12px;
}

.file-mode-alert {
  background: rgba(236, 253, 245, 0.7);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 12px;
}

.w-full {
  width: 100%;
}

@media (max-width: 640px) {
  .stage-guide__paths {
    grid-template-columns: 1fr;
  }

  .stage-history-item {
    align-items: flex-start;
    flex-direction: column;
  }

  .run-mode-panel {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
