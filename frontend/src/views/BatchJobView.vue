<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSpace,
  useMessage,
} from "naive-ui";
import { onBeforeUnmount, reactive, ref, watch } from "vue";

import { getBatch, submitBatchJob, type JobState } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import FileBrowser from "../components/FileBrowser.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const { activeProfile, backends, error, loading, profiles } = useConfigOptions();
const batchState = ref<JobState | null>(null);
const submitting = ref(false);
const pollHandle = ref<number | null>(null);

const form = reactive({
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

watch(activeProfile, (value) => {
  if (!form.profile && value) {
    form.profile = value;
  }
});

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
    void refreshBatch(batchId);
  }, 2000);
}

function buildPayload() {
  return {
    manifest: form.mode === "manifest" ? form.manifest : null,
    videos_dir: form.mode === "manifest" ? null : form.videos_dir,
    reference_dir: form.mode === "paired-dir" ? form.reference_dir : null,
    shared_reference: form.mode === "shared-reference" ? form.shared_reference : null,
    output_dir: form.mode === "manifest" ? null : form.output_dir,
    profile: form.profile || null,
    backend: form.backend || null,
    remote_concurrency: form.remote_concurrency,
    book_name: form.book_name || null,
    chapter: form.chapter || null,
    glossary_file: form.glossary_file || null,
  };
}

async function submit() {
  if (form.mode === "manifest" && !form.manifest) {
    message.warning("Manifest 模式需要选择 manifest 文件。");
    return;
  }
  if (form.mode !== "manifest" && (!form.videos_dir || !form.output_dir)) {
    message.warning("当前模式至少需要视频目录和输出目录。");
    return;
  }
  if (form.mode === "paired-dir" && !form.reference_dir) {
    message.warning("目录配对模式需要参考目录。");
    return;
  }
  if (form.mode === "shared-reference" && !form.shared_reference) {
    message.warning("共享参考模式需要共享参考源。");
    return;
  }

  submitting.value = true;
  try {
    const response = await submitBatchJob(buildPayload());
    await refreshBatch(response.batch_id);
    startPolling(response.batch_id);
    message.success(`批量任务已提交：${response.batch_id}`);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "提交失败");
  } finally {
    submitting.value = false;
  }
}

onBeforeUnmount(stopPolling);
</script>

<template>
  <n-space vertical :size="20">
    <n-alert v-if="error" type="error" :title="error" />
    <n-card title="批量任务提交" class="view-card">
      <n-form label-placement="top">
        <n-form-item label="输入模式">
          <n-radio-group v-model:value="form.mode">
            <n-radio-button value="manifest">Manifest</n-radio-button>
            <n-radio-button value="paired-dir">目录配对</n-radio-button>
            <n-radio-button value="shared-reference">共享参考</n-radio-button>
          </n-radio-group>
        </n-form-item>

        <n-form-item v-if="form.mode === 'manifest'" label="Manifest 文件">
          <FileBrowser v-model="form.manifest" mode="file" label="Manifest 文件" />
        </n-form-item>

        <template v-else>
          <n-form-item label="视频目录">
            <FileBrowser v-model="form.videos_dir" mode="dir" label="视频目录" />
          </n-form-item>
          <n-form-item v-if="form.mode === 'paired-dir'" label="参考目录">
            <FileBrowser v-model="form.reference_dir" mode="dir" label="参考目录" />
          </n-form-item>
          <n-form-item v-if="form.mode === 'shared-reference'" label="共享参考源或 URL">
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
          <n-form-item label="输出目录">
            <FileBrowser v-model="form.output_dir" mode="dir" label="输出目录" />
          </n-form-item>
        </template>

        <n-form-item label="术语词表">
          <FileBrowser v-model="form.glossary_file" mode="file" label="术语词表" button-text="选择术语词表" />
        </n-form-item>
        <n-form-item label="Profile">
          <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
        </n-form-item>
        <n-form-item label="Backend">
          <BackendSelector v-model="form.backend" :options="backends" :loading="loading" />
        </n-form-item>
        <n-form-item label="远程并发度">
          <n-input-number v-model:value="form.remote_concurrency" :min="1" />
        </n-form-item>
        <n-form-item label="书名">
          <n-input v-model:value="form.book_name" placeholder="可选" />
        </n-form-item>
        <n-form-item label="章节">
          <n-input v-model:value="form.chapter" placeholder="可选" />
        </n-form-item>
        <n-button type="primary" :loading="submitting" @click="submit">提交批量任务</n-button>
      </n-form>
    </n-card>

    <n-card v-if="batchState" title="批量任务状态" class="view-card">
      <n-space vertical :size="14">
        <div class="batch-summary">
          <strong>{{ batchState.id }}</strong>
          <span>状态：{{ batchState.status }}</span>
          <span>阶段：{{ batchState.current_stage || "-" }}</span>
        </div>
        <div class="batch-summary">
          <span>总数：{{ batchState.total ?? "-" }}</span>
          <span>成功：{{ batchState.success ?? "-" }}</span>
          <span>失败：{{ batchState.failed ?? "-" }}</span>
        </div>
        <n-card
          v-for="(item, index) in batchState.items ?? []"
          :key="String(item.job_id ?? index)"
          size="small"
          :title="String(item.job_id ?? `item-${index}`)"
        >
          <div class="batch-item-grid">
            <span>状态：{{ String(item.status ?? "-") }}</span>
            <span>模式：{{ String(item.mode ?? "-") }}</span>
            <span>失败阶段：{{ String(item.failed_stage ?? "-") || "-" }}</span>
            <span>输出：{{ String(item.copied_output_path ?? "-") || "-" }}</span>
          </div>
        </n-card>
      </n-space>
    </n-card>
  </n-space>
</template>
