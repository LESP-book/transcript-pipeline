<script setup lang="ts">
import { NButton, NEmpty, NSpace, useMessage } from "naive-ui";
import { onMounted, ref } from "vue";

import { listJobs, type JobState } from "../api/client";
import JobStatusCard from "../components/JobStatusCard.vue";

const message = useMessage();
const items = ref<JobState[]>([]);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    const response = await listJobs();
    items.value = response.items;
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
    <n-button tertiary type="primary" :loading="loading" @click="load">刷新任务列表</n-button>
    <n-empty v-if="!loading && items.length === 0" description="当前没有可展示的任务状态。" />
    <JobStatusCard
      v-for="item in items"
      :key="item.id"
      :title="`任务 ${item.id}`"
      :state="item"
    />
  </n-space>
</template>
