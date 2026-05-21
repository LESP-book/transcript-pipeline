<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NSelect,
  NSpace,
  useMessage,
} from "naive-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";

import { getStageRun, submitStageRun, type JobState } from "../api/client";
import BackendSelector from "../components/BackendSelector.vue";
import JobStatusCard from "../components/JobStatusCard.vue";
import ProfileSelector from "../components/ProfileSelector.vue";
import { useConfigOptions } from "../composables/useConfigOptions";

const message = useMessage();
const { activeProfile, backends, error, loading, profiles } = useConfigOptions();
const stageState = ref<JobState | null>(null);
const submitting = ref(false);
const pollHandle = ref<number | null>(null);

const form = reactive({
  stage: "extract-audio",
  profile: "",
  backend: "",
});

const stageOptions = [
  { label: "音频提取 (extract-audio)", value: "extract-audio" },
  { label: "语音转写 (transcribe)", value: "transcribe" },
  { label: "准备参考 (prepare-reference)", value: "prepare-reference" },
  { label: "文本对齐 (align)", value: "align" },
  { label: "段落分类 (classify)", value: "classify" },
  { label: "智能润色 (refine)", value: "refine" },
  { label: "导出文档 (export-markdown)", value: "export-markdown" },
];

const refineSelected = computed(() => form.stage === "refine");

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

async function refreshStage(runId: string) {
  const state = await getStageRun(runId);
  stageState.value = state;
  if (state.status === "success" || state.status === "failed") {
    stopPolling();
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

async function submit() {
  submitting.value = true;
  try {
    const response = await submitStageRun(form.stage, {
      profile: form.profile || null,
      backend: refineSelected.value ? form.backend || null : null,
    });
    await refreshStage(response.run_id);
    startPolling(response.run_id);
    message.success(`阶段任务已成功提交：${response.run_id}`);
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
        <h2 class="view-hero__title">单阶段手动触发</h2>
        <p class="view-hero__copy">
          适合高级调试、流程中断恢复或人工干预场景。允许手动指定运行特定的流水线单个节点任务，例如在已提取音频后仅手动触发语音转写。
        </p>
      </div>
    </section>

    <n-alert v-if="error" type="error" :title="error" :bordered="false" class="glass-alert" />
    
    <n-alert type="warning" title="全局目录运行警告" :bordered="false" class="warn-alert">
      该工具是直接对当前系统配置目录下的数据执行对应处理阶段，并不是针对单个临时上传文件起作用。
    </n-alert>

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
          
          <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
            <n-grid-item span="2 m:1">
              <n-form-item label="指定 Profile">
                <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
              </n-form-item>
            </n-grid-item>
            
            <n-grid-item span="2 m:1">
              <n-form-item label="智能润色推理后端 (Backend，仅在 refine 阶段生效)">
                <BackendSelector v-model="form.backend" :options="backends" :loading="loading" :disabled="!refineSelected" />
              </n-form-item>
            </n-grid-item>
          </n-grid>

          <n-flex justify="end" class="form-action-area">
            <n-button type="primary" size="large" :loading="submitting" @click="submit" class="submit-btn is-stage-btn">
              <template #icon>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </template>
              立即运行指定阶段
            </n-button>
          </n-flex>
        </n-space>
      </n-form>
    </n-card>

    <!-- Visual status card for run progress -->
    <JobStatusCard v-if="stageState" title="阶段任务执行状态报告" :state="stageState" />
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

.w-full {
  width: 100%;
}
</style>
