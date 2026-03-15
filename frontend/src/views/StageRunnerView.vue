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
  "extract-audio",
  "transcribe",
  "prepare-reference",
  "align",
  "classify",
  "refine",
  "export-markdown",
].map((value) => ({ label: value, value }));

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
    void refreshStage(runId);
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
    message.success(`阶段任务已提交：${response.run_id}`);
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
    <n-alert type="warning" title="当前配置目录运行">
      这个页面运行的是当前配置文件绑定的数据目录，不是针对某个临时选择的单文件执行。
    </n-alert>

    <n-card title="单阶段运行" class="view-card">
      <n-form label-placement="top">
        <n-form-item label="阶段名">
          <n-select v-model:value="form.stage" :options="stageOptions" />
        </n-form-item>
        <n-form-item label="Profile">
          <ProfileSelector v-model="form.profile" :options="profiles" :loading="loading" />
        </n-form-item>
        <n-form-item label="Backend（仅 refine 生效）">
          <BackendSelector v-model="form.backend" :options="backends" :loading="loading" :disabled="!refineSelected" />
        </n-form-item>
        <n-button type="primary" :loading="submitting" @click="submit">提交阶段任务</n-button>
      </n-form>
    </n-card>

    <JobStatusCard v-if="stageState" title="阶段任务状态" :state="stageState" />
  </n-space>
</template>
