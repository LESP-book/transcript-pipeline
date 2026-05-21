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
  NRadioButton,
  NRadioGroup,
  NSpace,
  NTag,
  useMessage,
} from "naive-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";

import { getBatch, listFs, submitBatchJob, type FileItem, type JobState } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import FileBrowser from "../components/FileBrowser.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

type BatchMode = "manifest" | "paired-dir" | "shared-reference";

interface SourcePreview {
  videoCount: number;
  ignoredCount: number;
  referenceCount: number;
  missingReferences: string[];
  duplicateReferences: string[];
}

const message = useMessage();
const { activeProfile, backends, error, loading, profiles, referenceExtensions, videoExtensions } = useConfigOptions();
const batchState = ref<JobState | null>(null);
const submitting = ref(false);
const previewLoading = ref(false);
const previewError = ref("");
const sourcePreview = ref<SourcePreview | null>(null);
const pollHandle = ref<number | null>(null);

const form = reactive<{
  mode: BatchMode;
  manifest: string;
  videos_dir: string;
  reference_dir: string;
  shared_reference: string;
  output_dir: string;
  profile: string;
  backend: string;
  remote_concurrency: number | null;
  book_name: string;
  chapter: string;
  glossary_file: string;
}>({
  mode: "manifest",
  manifest: "",
  videos_dir: "",
  reference_dir: "",
  shared_reference: "",
  output_dir: "",
  profile: "",
  backend: "",
  remote_concurrency: 2,
  book_name: "",
  chapter: "",
  glossary_file: "",
});

const modeTip = computed(() => {
  if (form.mode === "manifest") {
    return "Manifest 模式将按指定的清单 JSON/YAML 提交，适合每条任务有各自独立参考源或输出目录的个性化任务集合。";
  }
  if (form.mode === "paired-dir") {
    return "目录配对模式会自动扫描视频目录下所有视频，并在参考目录中匹配同名（basename）的 .txt、.md 或 .pdf 参考文本。";
  }
  return "共享参考模式会自动扫描视频目录下所有视频，并为它们全部配置同一个共享的参考文本文件或 URL 地址。";
});

const requiredWarning = computed(() => {
  if (form.mode === "manifest" && !form.manifest) {
    return "请选择 Manifest 清单文件。";
  }
  if (form.mode !== "manifest" && (!form.videos_dir || !form.output_dir)) {
    return "请选择视频源目录和成果输出目录。";
  }
  if (form.mode === "paired-dir" && !form.reference_dir) {
    return "目录配对模式下参考源目录是必填项。";
  }
  if (form.mode === "shared-reference" && !form.shared_reference.trim()) {
    return "共享参考模式下需要指定共享的参考源或 URL。";
  }
  if (!form.remote_concurrency || form.remote_concurrency < 1) {
    return "流水线远程并发度必须是大于等于 1 的整数。";
  }
  return "";
});

const previewHasBlockingIssue = computed(() => {
  if (!sourcePreview.value) {
    return false;
  }
  return (
    sourcePreview.value.videoCount === 0 ||
    sourcePreview.value.missingReferences.length > 0 ||
    sourcePreview.value.duplicateReferences.length > 0
  );
});

const batchItems = computed(() => batchState.value?.items ?? []);

watch(activeProfile, (value) => {
  if (!form.profile && value) {
    form.profile = value;
  }
});

watch(
  () => [form.mode, form.videos_dir, form.reference_dir, form.shared_reference, form.output_dir],
  () => {
    sourcePreview.value = null;
    previewError.value = "";
  }
);

function stopPolling() {
  if (pollHandle.value !== null) {
    window.clearInterval(pollHandle.value);
    pollHandle.value = null;
  }
}

async function refreshBatch(batchId: string) {
  const state = await getBatch(batchId);
  batchState.value = state;
  if (state.status === "success" || state.status === "failed") {
    stopPolling();
  }
}

function startPolling(batchId: string) {
  stopPolling();
  pollHandle.value = window.setInterval(() => {
    void refreshBatch(batchId).catch((caught) => {
      message.error(caught instanceof Error ? caught.message : "刷新批量任务状态失败");
      stopPolling();
    });
  }, 2000);
}

function fileStem(name: string): string {
  const dotIndex = name.lastIndexOf(".");
  return dotIndex > 0 ? name.slice(0, dotIndex) : name;
}

function fileSuffix(name: string): string {
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 ? name.slice(dotIndex).toLowerCase() : "";
}

function isAllowedFile(item: FileItem, extensions: string[]): boolean {
  return !item.is_dir && extensions.includes(fileSuffix(item.name));
}

function countReferencesByStem(items: FileItem[]) {
  const counter = new Map<string, number>();
  for (const item of items) {
    if (!isAllowedFile(item, referenceExtensions.value)) {
      continue;
    }
    const stem = fileStem(item.name);
    counter.set(stem, (counter.get(stem) ?? 0) + 1);
  }
  return counter;
}

async function inspectSources(): Promise<boolean> {
  if (form.mode === "manifest") {
    return true;
  }
  if (requiredWarning.value) {
    message.warning(requiredWarning.value);
    return false;
  }

  previewLoading.value = true;
  previewError.value = "";
  try {
    const videosResponse = await listFs(form.videos_dir, "all", false);
    const videoFiles = videosResponse.items.filter((item) => isAllowedFile(item, videoExtensions.value));
    const ignoredFiles = videosResponse.items.filter((item) => !item.is_dir && !isAllowedFile(item, videoExtensions.value));

    let referenceCount = 0;
    let missingReferences: string[] = [];
    let duplicateReferences: string[] = [];

    if (form.mode === "paired-dir") {
      const referenceResponse = await listFs(form.reference_dir, "all", false);
      const referenceFiles = referenceResponse.items.filter((item) => isAllowedFile(item, referenceExtensions.value));
      referenceCount = referenceFiles.length;
      const referenceCounter = countReferencesByStem(referenceResponse.items);
      missingReferences = videoFiles
        .map((item) => fileStem(item.name))
        .filter((stem) => !referenceCounter.has(stem));
      duplicateReferences = [...referenceCounter.entries()]
        .filter(([, count]) => count > 1)
        .map(([stem]) => stem);
    }

    sourcePreview.value = {
      videoCount: videoFiles.length,
      ignoredCount: ignoredFiles.length,
      referenceCount,
      missingReferences,
      duplicateReferences,
    };

    if (videoFiles.length === 0) {
      previewError.value = `视频目录中没有检测到可处理的视频文件，支持格式：${videoExtensions.value.join("、")}`;
      message.warning(previewError.value);
      return false;
    }
    if (missingReferences.length > 0) {
      previewError.value = `有 ${missingReferences.length} 个视频在参考目录中缺少对应的同名文本文件。`;
      message.warning(previewError.value);
      return false;
    }
    if (duplicateReferences.length > 0) {
      previewError.value = `有 ${duplicateReferences.length} 个基名匹配到重复的参考文本文件。`;
      message.warning(previewError.value);
      return false;
    }

    message.success("输入源目录批量扫描检查通过！");
    return true;
  } catch (caught) {
    previewError.value = caught instanceof Error ? caught.message : "输入目录检查失败";
    message.error(previewError.value);
    return false;
  } finally {
    previewLoading.value = false;
  }
}

function buildPayload(remoteConcurrency: number) {
  return {
    manifest: form.mode === "manifest" ? form.manifest : null,
    videos_dir: form.mode === "manifest" ? null : form.videos_dir,
    reference_dir: form.mode === "paired-dir" ? form.reference_dir : null,
    shared_reference: form.mode === "shared-reference" ? form.shared_reference.trim() : null,
    output_dir: form.mode === "manifest" ? null : form.output_dir,
    profile: form.profile || null,
    backend: form.backend || null,
    remote_concurrency: remoteConcurrency,
    book_name: form.book_name || null,
    chapter: form.chapter || null,
    glossary_file: form.glossary_file || null,
  };
}

async function submit() {
  if (requiredWarning.value) {
    message.warning(requiredWarning.value);
    return;
  }
  const remoteConcurrency = form.remote_concurrency;
  if (!remoteConcurrency || remoteConcurrency < 1) {
    message.warning("远程并发度必须是大于等于 1 的整数。");
    return;
  }

  if (form.mode !== "manifest") {
    const validSources = await inspectSources();
    if (!validSources) {
      return;
    }
  }

  submitting.value = true;
  try {
    const response = await submitBatchJob(buildPayload(remoteConcurrency));
    await refreshBatch(response.batch_id);
    startPolling(response.batch_id);
    message.success(`批量流水线任务已提交：${response.batch_id}`);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "提交失败");
  } finally {
    submitting.value = false;
  }
}

function itemStatusType(item: Record<string, unknown>) {
  const status = String(item.status ?? "");
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "running") {
    return "info";
  }
  return "warning";
}

const statusType = computed(() => {
  const status = String(batchState.value?.status ?? "");
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "running") {
    return "info";
  }
  return "warning";
});

onBeforeUnmount(stopPolling);
</script>

<template>
  <n-space vertical :size="24">
    <!-- Premium Title Banner -->
    <section class="view-hero">
      <div>
        <p class="view-hero__eyebrow">任务控制台</p>
        <h2 class="view-hero__title">批量整理流水线</h2>
        <p class="view-hero__copy">
          支持 Manifest 清单配置、目录智能配对、以及共享单一参考源三种批量模式，为多视频整理提供高效、高并发的一键式流水线处理。
        </p>
      </div>
    </section>

    <n-alert v-if="error" type="error" :title="error" :bordered="false" class="glass-alert" />

    <n-card class="view-card form-panel" :bordered="false">
      <template #header>
        <n-flex align="center" :size="10">
          <div class="panel-header-icon is-batch">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:20px;height:20px"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>
          </div>
          <span>创建批量处理任务</span>
        </n-flex>
      </template>

      <n-form label-placement="top">
        <n-space vertical :size="20">
          <!-- Mode Toggle Selection -->
          <div class="mode-selector-wrapper">
            <span class="mode-label">批量输入模式:</span>
            <n-radio-group v-model:value="form.mode" size="large" class="mode-radio-group">
              <n-radio-button value="manifest" class="mode-radio-btn">Manifest 配置清单</n-radio-button>
              <n-radio-button value="paired-dir" class="mode-radio-btn">目录自动配对</n-radio-button>
              <n-radio-button value="shared-reference" class="mode-radio-btn">目录共享参考</n-radio-button>
            </n-radio-group>
          </div>

          <n-alert type="info" :title="modeTip" :bordered="false" class="mode-alert" />
          <n-alert v-if="requiredWarning" type="warning" :title="requiredWarning" :bordered="false" class="warn-alert" />

          <n-grid :cols="2" :x-gap="20" :y-gap="4" responsive="screen" item-responsive>
            <!-- Left Fields -->
            <n-grid-item span="2 m:1">
              <div class="form-section">
                <h4 class="form-section-title">批量输入输出参数</h4>
                
                <n-form-item v-if="form.mode === 'manifest'" label="Manifest 清单文件" required>
                  <FileBrowser v-model="form.manifest" mode="file" label="Manifest 清单文件" />
                </n-form-item>

                <template v-else>
                  <n-form-item label="视频源目录 (Videos Directory)" required>
                    <FileBrowser v-model="form.videos_dir" mode="dir" label="视频源目录" />
                  </n-form-item>
                  
                  <n-form-item v-if="form.mode === 'paired-dir'" label="参考源目录 (Reference Directory)" required>
                    <FileBrowser v-model="form.reference_dir" mode="dir" label="参考源目录" />
                  </n-form-item>
                  
                  <n-form-item v-if="form.mode === 'shared-reference'" label="共享参考源文件或 URL" required>
                    <n-space vertical class="w-full">
                      <n-input v-model:value="form.shared_reference" placeholder="输入共享的本地路径或 https:// 参考源" />
                      <FileBrowser
                        v-model="form.shared_reference"
                        mode="file"
                        label="共享参考文件"
                        button-text="浏览本地共享参考"
                      />
                    </n-space>
                  </n-form-item>
                  
                  <n-form-item label="成果输出目录 (Output Directory)" required>
                    <FileBrowser v-model="form.output_dir" mode="dir" label="成果输出目录" />
                  </n-form-item>
                </template>
              </div>
            </n-grid-item>

            <!-- Right Fields -->
            <n-grid-item span="2 m:1">
              <div class="form-section">
                <h4 class="form-section-title">批量流水线辅助与模型配置</h4>
                <n-grid :cols="2" :x-gap="12" :y-gap="0">
                  <n-grid-item span="2">
                    <n-form-item label="术语词表 (Glossary File)">
                      <FileBrowser v-model="form.glossary_file" mode="file" label="术语词表" button-text="选择术语词表" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item span="1">
                    <n-form-item label="配置 Profile">
                      <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item span="1">
                    <n-form-item label="推理后端 (Backend)">
                      <BackendSelector v-model="form.backend" :options="backends" :loading="loading" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item span="1">
                    <n-form-item label="批量远程并发度" required>
                      <n-input-number v-model:value="form.remote_concurrency" :min="1" :precision="0" class="w-full" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item span="1">
                    <n-form-item label="书名 (Book Name)">
                      <n-input v-model:value="form.book_name" placeholder="可选" />
                    </n-form-item>
                  </n-grid-item>
                  <n-grid-item span="2">
                    <n-form-item label="章节名称 (Chapter)">
                      <n-input v-model:value="form.chapter" placeholder="可选" />
                    </n-form-item>
                  </n-grid-item>
                </n-grid>
              </div>
            </n-grid-item>
          </n-grid>

          <!-- Input Dir Scanning and Preview Statistics -->
          <div v-if="form.mode !== 'manifest'" class="batch-preview">
            <n-space align="center" justify="space-between" class="w-full" wrap>
              <n-button secondary type="primary" :loading="previewLoading" @click="inspectSources" class="inspect-btn">
                <template #icon>
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                </template>
                智能扫描并预检输入目录
              </n-button>
              <span class="batch-preview__hint">
                允许视频：<span class="ext-tag">{{ videoExtensions.join("、") || "-" }}</span> ；
                参考文本：<span class="ext-tag">{{ referenceExtensions.join("、") || "-" }}</span>
              </span>
            </n-space>

            <n-alert v-if="previewError" class="batch-preview__alert" type="error" :title="previewError" :bordered="false" />
            
            <div v-if="sourcePreview" class="preview-stats-grid">
              <div class="stat-bubble is-success">
                <span class="stat-num">{{ sourcePreview.videoCount }}</span>
                <span class="stat-label">待处理视频</span>
              </div>
              <div v-if="form.mode === 'paired-dir'" class="stat-bubble is-info">
                <span class="stat-num">{{ sourcePreview.referenceCount }}</span>
                <span class="stat-label">检测参考文件</span>
              </div>
              <div class="stat-bubble is-muted">
                <span class="stat-num">{{ sourcePreview.ignoredCount }}</span>
                <span class="stat-label">其他忽略文件</span>
              </div>
              
              <div v-if="sourcePreview.missingReferences.length || sourcePreview.duplicateReferences.length" class="alert-stats-box">
                <div v-if="sourcePreview.missingReferences.length" class="err-stat">
                  ⚠️ 缺少参考：{{ sourcePreview.missingReferences.join("、") }}
                </div>
                <div v-if="sourcePreview.duplicateReferences.length" class="err-stat">
                  ⚠️ 重复匹配：{{ sourcePreview.duplicateReferences.join("、") }}
                </div>
              </div>
            </div>
          </div>

          <!-- Bottom Actions -->
          <n-flex justify="end" class="form-action-area">
            <n-button
              type="primary"
              size="large"
              :loading="submitting"
              :disabled="Boolean(requiredWarning) || previewHasBlockingIssue"
              @click="submit"
              class="submit-btn"
            >
              <template #icon>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              </template>
              开启批量流水线任务
            </n-button>
          </n-flex>
        </n-space>
      </n-form>
    </n-card>

    <!-- Batch Job Running Status Details -->
    <n-card v-slot:default v-if="batchState" title="批量流水线实时运行状态" class="view-card">
      <n-space vertical :size="16">
        <div class="batch-summary-glow">
          <div class="summary-top">
            <strong class="batch-id-text">{{ batchState.id }}</strong>
            <n-tag :type="statusType" round :bordered="false" class="summary-status-badge">
              {{ batchState.status }}
            </n-tag>
          </div>
          
          <div class="summary-counters">
            <div class="counter-item">
              <span class="c-label">当前流水线阶段</span>
              <span class="c-val text-primary font-semibold">{{ batchState.current_stage || "准备中..." }}</span>
            </div>
            <div class="counter-item">
              <span class="c-label">总任务数</span>
              <span class="c-val">{{ batchState.total ?? "-" }}</span>
            </div>
            <div class="counter-item">
              <span class="c-label">执行成功</span>
              <span class="c-val text-success">{{ batchState.success ?? "-" }}</span>
            </div>
            <div class="counter-item">
              <span class="c-label">执行失败</span>
              <span class="c-val text-error">{{ batchState.failed ?? "-" }}</span>
            </div>
          </div>
          
          <div v-if="batchState.output_path" class="summary-path-box">
            <span class="p-title">合并成果汇总结案路径:</span>
            <span class="p-content">{{ batchState.output_path }}</span>
          </div>
        </div>

        <n-alert v-if="batchState.error_message" type="error" :title="batchState.error_message" :bordered="false" class="glass-alert" />
        
        <!-- Batch Sub-jobs List -->
        <div v-if="batchItems.length" class="sub-jobs-section">
          <h4 class="sub-jobs-title">子视频流水线详情 (Sub-jobs List)</h4>
          <div class="batch-items">
            <div
              v-for="(item, index) in batchItems"
              :key="String(item.job_id ?? item.video_source ?? index)"
              class="batch-item-modern"
            >
              <div class="batch-item__head">
                <div class="item-name-box">
                  <span class="sub-index">#{{ index + 1 }}</span>
                  <strong class="sub-id">{{ String(item.job_id || `未分配ID`) }}</strong>
                </div>
                <n-tag :type="itemStatusType(item)" size="small" :bordered="false" round class="sub-badge">
                  {{ String(item.status ?? "-") }}
                </n-tag>
              </div>
              
              <div class="batch-item-grid-modern">
                <div class="grid-cell"><span class="cell-label">配置模式:</span> {{ String(item.mode ?? "-") }}</div>
                <div class="grid-cell"><span class="cell-label">失败阶段:</span> <span :class="{'text-error font-semibold': item.failed_stage}">{{ String(item.failed_stage || "-") }}</span></div>
                <div class="grid-cell span-all"><span class="cell-label">视频路径:</span> <span class="mono-path">{{ String(item.video_source ?? "-") || "-" }}</span></div>
                <div class="grid-cell span-all"><span class="cell-label">参考源:</span> <span class="mono-path">{{ String(item.reference_source ?? "-") || "-" }}</span></div>
                <div class="grid-cell span-all"><span class="cell-label">输出路径:</span> <span class="mono-path is-out">{{ String(item.copied_output_path ?? "-") || "-" }}</span></div>
                <div v-if="String(item.error_message ?? '')" class="grid-cell span-all err-cell">
                  <span class="cell-label">错误详情:</span> {{ String(item.error_message) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </n-space>
    </n-card>
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

.panel-header-icon.is-batch {
  background: rgba(168, 85, 247, 0.1);
  color: #a855f7;
}

.mode-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 16px;
  background: rgba(241, 245, 249, 0.5);
  padding: 10px 18px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.6);
  flex-wrap: wrap;
}

.mode-label {
  font-weight: 700;
  color: var(--text-primary);
  font-size: 14px;
}

.mode-radio-group {
  display: flex;
  gap: 8px;
}

.mode-radio-btn {
  border-radius: 8px !important;
  font-weight: 600;
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

.form-action-area {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.8);
}

.inspect-btn {
  border-radius: 8px;
  font-weight: 600;
}

.ext-tag {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
}

.preview-stats-grid {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.stat-bubble {
  flex: 1;
  min-width: 120px;
  background: #ffffff;
  border-radius: 10px;
  padding: 12px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.01);
}

.stat-bubble.is-success {
  border-left: 4px solid #10b981;
}

.stat-bubble.is-info {
  border-left: 4px solid #3b82f6;
}

.stat-bubble.is-muted {
  border-left: 4px solid #94a3b8;
}

.stat-num {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary);
}

.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-top: 2px;
}

.alert-stats-box {
  width: 100%;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  font-size: 13px;
  font-weight: 600;
  color: #b45309;
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

.batch-summary-glow {
  background: radial-gradient(circle at top right, rgba(99, 102, 241, 0.05) 0%, transparent 60%), #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 14px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.batch-id-text {
  font-size: 18px;
  font-family: monospace;
  font-weight: 700;
  color: var(--text-primary);
}

.summary-status-badge {
  font-weight: 700;
  text-transform: uppercase;
}

.summary-counters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  background: #f8fafc;
  padding: 12px 18px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.5);
}

.counter-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.c-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

.c-val {
  font-size: 15px;
  font-weight: 700;
}

.summary-path-box {
  background: #f1f5f9;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
}

.p-title {
  font-weight: 700;
  color: var(--text-secondary);
  margin-right: 6px;
}

.p-content {
  font-family: monospace;
  color: #334155;
  word-break: break-all;
}

.sub-jobs-section {
  margin-top: 18px;
}

.sub-jobs-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-secondary);
  border-left: 3px solid #cbd5e1;
  padding-left: 8px;
}

.batch-item-modern {
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 12px;
  padding: 14px 18px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.batch-item-modern:hover {
  transform: translateY(-1px);
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.02);
}

.item-name-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sub-index {
  font-size: 11px;
  font-weight: 700;
  background: #f1f5f9;
  color: #475569;
  padding: 2px 6px;
  border-radius: 4px;
}

.sub-id {
  font-size: 14px;
  font-family: monospace;
}

.sub-badge {
  font-weight: 700;
}

.batch-item-grid-modern {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 6px 16px;
  font-size: 12px;
  color: var(--text-secondary);
}

.span-all {
  grid-column: 1 / -1;
}

.cell-label {
  font-weight: 700;
  color: var(--text-muted);
  margin-right: 4px;
}

.mono-path {
  font-family: monospace;
  font-size: 11px;
  background: #f8fafc;
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
  display: inline-block;
}

.mono-path.is-out {
  background: #f0fdf4;
  color: #166534;
}

.err-cell {
  background: #fef2f2;
  color: #991b1b;
  padding: 6px 10px;
  border-radius: 6px;
  font-family: monospace;
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
</style>
