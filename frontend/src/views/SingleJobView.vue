<script setup lang="ts">
import {
  NButton,
  NCard,
  NFlex,
  NForm,
  NFormItem,
  NInput,
  NSpace,
  useMessage,
} from "naive-ui";
import { onBeforeUnmount, reactive, ref } from "vue";

import { getJob, type JobState, submitJob } from "../api/client";
import FileBrowser from "../components/FileBrowser.vue";
import JobStatusCard from "../components/JobStatusCard.vue";

const message = useMessage();
const jobState = ref<JobState | null>(null);
const submitting = ref(false);
const pollHandle = ref<number | null>(null);

const form = reactive({
  video: "",
  reference: "",
  output_dir: "",
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

async function handleJobRerun(jobId: string) {
  await refreshJob(jobId);
  startPolling(jobId);
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
          在这里提交单个读书会录屏视频，系统将按顺序执行提取音频、语音转写、参考文本对齐、智能校对润色及 Markdown 最终稿的导出。
        </p>
      </div>
    </section>

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
        <div class="form-section">
          <h4 class="form-section-title">核心输入输出参数</h4>
          <n-form-item label="视频文件 (Video Source)" required>
            <FileBrowser v-model="form.video" mode="file" label="视频文件" />
          </n-form-item>
          <n-form-item label="参考源文件或 URL (Reference)" required>
            <n-space vertical class="w-full">
              <n-input v-model:value="form.reference" placeholder="本地文件路径，或输入 https:// 网址" />
              <FileBrowser v-model="form.reference" mode="file" label="参考源文件" button-text="浏览本地参考源" />
            </n-space>
          </n-form-item>
          <n-form-item label="输出保存目录 (Output Directory)" required>
            <FileBrowser v-model="form.output_dir" mode="dir" label="输出保存目录" />
          </n-form-item>
        </div>

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
    <JobStatusCard v-if="jobState" title="流水线当前实时状态" :state="jobState" @rerun="handleJobRerun" />
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
</style>
