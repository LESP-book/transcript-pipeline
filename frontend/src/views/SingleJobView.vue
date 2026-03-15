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
  NSpace,
  useMessage,
} from "naive-ui";
import { onBeforeUnmount, reactive, ref, watch } from "vue";

import { getJob, type JobState, submitJob } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import FileBrowser from "../components/FileBrowser.vue";
import JobStatusCard from "../components/JobStatusCard.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const { activeProfile, backends, error, loading, profiles } = useConfigOptions();
const jobState = ref<JobState | null>(null);
const submitting = ref(false);
const pollHandle = ref<number | null>(null);

const form = reactive({
  video: "",
  reference: "",
  output_dir: "",
  profile: "",
  backend: "",
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
    void refreshJob(jobId);
  }, 2000);
}

async function submit() {
  if (!form.video || !form.reference || !form.output_dir) {
    message.warning("视频、参考源和输出目录是必填项。");
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
      book_name: form.book_name || null,
      chapter: form.chapter || null,
      glossary_file: form.glossary_file || null,
    });
    await refreshJob(response.job_id);
    startPolling(response.job_id);
    message.success(`任务已提交：${response.job_id}`);
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
    <n-card title="单任务提交" class="view-card">
      <n-form label-placement="top">
        <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
          <n-grid-item span="2 m:1">
            <n-form-item label="视频文件">
              <FileBrowser v-model="form.video" mode="file" label="视频文件" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item span="2 m:1">
            <n-form-item label="参考源文件或 URL">
              <n-space vertical>
                <n-input v-model:value="form.reference" placeholder="本地路径或 https://..." />
                <FileBrowser v-model="form.reference" mode="file" label="参考源文件" button-text="浏览本地参考源" />
              </n-space>
            </n-form-item>
          </n-grid-item>
          <n-grid-item span="2 m:1">
            <n-form-item label="输出目录">
              <FileBrowser v-model="form.output_dir" mode="dir" label="输出目录" />
            </n-form-item>
          </n-grid-item>
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
        <n-button type="primary" :loading="submitting" @click="submit">提交单任务</n-button>
      </n-form>
    </n-card>

    <JobStatusCard v-if="jobState" title="当前任务状态" :state="jobState" />
  </n-space>
</template>
