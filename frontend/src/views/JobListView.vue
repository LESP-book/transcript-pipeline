<script setup lang="ts">
import { NButton, NEmpty, NSpace, NTabs, NTabPane, useMessage } from "naive-ui";
import { computed, onMounted, ref } from "vue";

import { listBatches, listJobs, listStageRuns, type JobState } from "../api/client";
import JobStatusCard from "../components/JobStatusCard.vue";

const message = useMessage();
const jobs = ref<JobState[]>([]);
const batches = ref<JobState[]>([]);
const stageRuns = ref<JobState[]>([]);
const loading = ref(false);

const totalCount = computed(() => jobs.value.length + batches.value.length + stageRuns.value.length);

async function load() {
  loading.value = true;
  try {
    const [jobResponse, batchResponse, stageRunResponse] = await Promise.all([
      listJobs(),
      listBatches(),
      listStageRuns(),
    ]);
    jobs.value = jobResponse.items;
    batches.value = batchResponse.items;
    stageRuns.value = stageRunResponse.items;
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "加载任务列表失败");
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <n-space vertical :size="20">
    <n-space align="center" justify="space-between">
      <strong>共 {{ totalCount }} 条任务记录</strong>
      <n-button tertiary type="primary" :loading="loading" @click="load">刷新任务列表</n-button>
    </n-space>

    <n-empty v-if="!loading && totalCount === 0" description="当前没有可展示的任务状态。" />

    <n-tabs v-else type="line" animated>
      <n-tab-pane :name="'jobs'" :tab="`单任务 ${jobs.length}`">
        <n-space vertical :size="16">
          <n-empty v-if="jobs.length === 0" description="暂无单任务记录。" />
          <JobStatusCard v-for="item in jobs" :key="item.id" :title="`单任务 ${item.id}`" :state="item" />
        </n-space>
      </n-tab-pane>
      <n-tab-pane :name="'batches'" :tab="`批量任务 ${batches.length}`">
        <n-space vertical :size="16">
          <n-empty v-if="batches.length === 0" description="暂无批量任务记录。" />
          <JobStatusCard v-for="item in batches" :key="item.id" :title="`批量任务 ${item.id}`" :state="item" />
        </n-space>
      </n-tab-pane>
      <n-tab-pane :name="'stage-runs'" :tab="`单阶段 ${stageRuns.length}`">
        <n-space vertical :size="16">
          <n-empty v-if="stageRuns.length === 0" description="暂无单阶段记录。" />
          <JobStatusCard v-for="item in stageRuns" :key="item.id" :title="`单阶段 ${item.id}`" :state="item" />
        </n-space>
      </n-tab-pane>
    </n-tabs>
  </n-space>
</template>
