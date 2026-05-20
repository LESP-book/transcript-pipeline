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
    return "Manifest 会按文件里的 jobs 列表提交，适合每条任务有不同参考源或输出目录。";
  }
  if (form.mode === "paired-dir") {
    return "目录配对会按视频文件 basename 查找同名 txt、md 或 pdf 参考文件。";
  }
  return "共享参考会把同一个本地文件或 URL 用于视频目录内的所有视频。";
});

const requiredWarning = computed(() => {
  if (form.mode === "manifest" && !form.manifest) {
    return "请先选择 Manifest 文件。";
  }
  if (form.mode !== "manifest" && (!form.videos_dir || !form.output_dir)) {
    return "请先选择视频目录和输出目录。";
  }
  if (form.mode === "paired-dir" && !form.reference_dir) {
    return "目录配对模式还需要参考目录。";
  }
  if (form.mode === "shared-reference" && !form.shared_reference.trim()) {
    return "共享参考模式还需要共享参考源文件或 URL。";
  }
  if (!form.remote_concurrency || form.remote_concurrency < 1) {
    return "远程并发度必须是大于等于 1 的整数。";
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
  },
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
      previewError.value = `视频目录中没有可处理的视频文件，当前支持：${videoExtensions.value.join("、")}`;
      message.warning(previewError.value);
      return false;
    }
    if (missingReferences.length > 0) {
      previewError.value = `有 ${missingReferences.length} 个视频缺少同名参考文件。`;
      message.warning(previewError.value);
      return false;
    }
    if (duplicateReferences.length > 0) {
      previewError.value = `有 ${duplicateReferences.length} 个 basename 匹配到多个参考文件。`;
      message.warning(previewError.value);
      return false;
    }

    message.success("输入目录检查通过。");
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
    message.success(`批量任务已提交：${response.batch_id}`);
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

onBeforeUnmount(stopPolling);
</script>

<template>
  <n-space vertical :size="20">
    <n-alert v-if="error" type="error" :title="error" />
    <n-card title="批量任务提交" class="view-card">
      <n-form label-placement="top">
        <n-space vertical :size="18">
          <n-form-item label="输入模式">
            <n-radio-group v-model:value="form.mode">
              <n-radio-button value="manifest">Manifest</n-radio-button>
              <n-radio-button value="paired-dir">目录配对</n-radio-button>
              <n-radio-button value="shared-reference">共享参考</n-radio-button>
            </n-radio-group>
          </n-form-item>

          <n-alert type="info" :title="modeTip" />
          <n-alert v-if="requiredWarning" type="warning" :title="requiredWarning" />

          <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
            <n-grid-item v-if="form.mode === 'manifest'" span="2">
              <n-form-item label="Manifest 文件">
                <FileBrowser v-model="form.manifest" mode="file" label="Manifest 文件" />
              </n-form-item>
            </n-grid-item>

            <template v-else>
              <n-grid-item span="2 m:1">
                <n-form-item label="视频目录">
                  <FileBrowser v-model="form.videos_dir" mode="dir" label="视频目录" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item v-if="form.mode === 'paired-dir'" span="2 m:1">
                <n-form-item label="参考目录">
                  <FileBrowser v-model="form.reference_dir" mode="dir" label="参考目录" />
                </n-form-item>
              </n-grid-item>
              <n-grid-item v-if="form.mode === 'shared-reference'" span="2 m:1">
                <n-form-item label="共享参考源或 URL">
                  <n-space vertical>
                    <n-input v-model:value="form.shared_reference" placeholder="本地路径或 https://..." />
                    <FileBrowser
                      v-model="form.shared_reference"
                      mode="file"
                      label="共享参考源文件"
                      button-text="浏览本地共享参考源"
                    />
                  </n-space>
                </n-form-item>
              </n-grid-item>
              <n-grid-item span="2 m:1">
                <n-form-item label="输出目录">
                  <FileBrowser v-model="form.output_dir" mode="dir" label="输出目录" />
                </n-form-item>
              </n-grid-item>
            </template>

            <n-grid-item span="2 m:1">
              <n-form-item label="术语词表">
                <FileBrowser v-model="form.glossary_file" mode="file" label="术语词表" button-text="选择术语词表" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item span="2 m:1">
              <n-form-item label="Profile">
                <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item span="2 m:1">
              <n-form-item label="Backend">
                <BackendSelector v-model="form.backend" :options="backends" :loading="loading" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item span="2 m:1">
              <n-form-item label="远程并发度">
                <n-input-number v-model:value="form.remote_concurrency" :min="1" :precision="0" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item span="2 m:1">
              <n-form-item label="书名">
                <n-input v-model:value="form.book_name" placeholder="可选" />
              </n-form-item>
            </n-grid-item>
            <n-grid-item span="2 m:1">
              <n-form-item label="章节">
                <n-input v-model:value="form.chapter" placeholder="可选" />
              </n-form-item>
            </n-grid-item>
          </n-grid>

          <div v-if="form.mode !== 'manifest'" class="batch-preview">
            <n-space align="center" wrap>
              <n-button secondary type="primary" :loading="previewLoading" @click="inspectSources">检查输入目录</n-button>
              <span class="batch-preview__hint">
                支持视频：{{ videoExtensions.join("、") || "-" }}；支持参考：{{ referenceExtensions.join("、") || "-" }}
              </span>
            </n-space>
            <n-alert v-if="previewError" class="batch-preview__alert" type="error" :title="previewError" />
            <div v-if="sourcePreview" class="batch-preview__stats">
              <span>可提交视频：{{ sourcePreview.videoCount }}</span>
              <span v-if="form.mode === 'paired-dir'">参考文件：{{ sourcePreview.referenceCount }}</span>
              <span>目录内非视频文件：{{ sourcePreview.ignoredCount }}</span>
              <span v-if="sourcePreview.missingReferences.length">缺参考：{{ sourcePreview.missingReferences.join("、") }}</span>
              <span v-if="sourcePreview.duplicateReferences.length">
                重复参考：{{ sourcePreview.duplicateReferences.join("、") }}
              </span>
            </div>
          </div>

          <n-space>
            <n-button
              type="primary"
              :loading="submitting"
              :disabled="Boolean(requiredWarning) || previewHasBlockingIssue"
              @click="submit"
            >
              提交批量任务
            </n-button>
          </n-space>
        </n-space>
      </n-form>
    </n-card>

    <n-card v-if="batchState" title="批量任务状态" class="view-card">
      <n-space vertical :size="14">
        <div class="batch-summary">
          <strong>{{ batchState.id }}</strong>
          <span>状态：{{ batchState.status }}</span>
          <span>阶段：{{ batchState.current_stage || "-" }}</span>
          <span>总数：{{ batchState.total ?? "-" }}</span>
          <span>成功：{{ batchState.success ?? "-" }}</span>
          <span>失败：{{ batchState.failed ?? "-" }}</span>
          <span v-if="batchState.output_path">汇总：{{ batchState.output_path }}</span>
        </div>
        <n-alert v-if="batchState.error_message" type="error" :title="batchState.error_message" />
        <div v-if="batchItems.length" class="batch-items">
          <div
            v-for="(item, index) in batchItems"
            :key="String(item.job_id ?? item.video_source ?? index)"
            class="batch-item"
          >
            <div class="batch-item__head">
              <strong>{{ String(item.job_id || `item-${index + 1}`) }}</strong>
              <n-tag :type="itemStatusType(item)" size="small">{{ String(item.status ?? "-") }}</n-tag>
            </div>
            <div class="batch-item-grid">
              <span>模式：{{ String(item.mode ?? "-") }}</span>
              <span>失败阶段：{{ String(item.failed_stage ?? "-") || "-" }}</span>
              <span>视频：{{ String(item.video_source ?? "-") || "-" }}</span>
              <span>参考：{{ String(item.reference_source ?? "-") || "-" }}</span>
              <span>输出：{{ String(item.copied_output_path ?? "-") || "-" }}</span>
              <span v-if="String(item.error_message ?? '')">错误：{{ String(item.error_message) }}</span>
            </div>
          </div>
        </div>
      </n-space>
    </n-card>
  </n-space>
</template>
