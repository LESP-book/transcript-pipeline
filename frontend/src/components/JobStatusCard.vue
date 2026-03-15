<script setup lang="ts">
import { NAlert, NCard, NDescriptions, NDescriptionsItem, NTag } from "naive-ui";
import { computed } from "vue";

const props = defineProps<{
  title?: string;
  state: Record<string, unknown>;
}>();

const statusType = computed(() => {
  const status = String(props.state.status ?? "");
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
</script>

<template>
  <n-card :title="title ?? String(state.id ?? '任务状态')" size="small" class="status-card">
    <n-descriptions label-placement="top" :column="3" size="small" bordered>
      <n-descriptions-item label="状态">
        <n-tag :type="statusType" round>{{ String(state.status ?? "-") }}</n-tag>
      </n-descriptions-item>
      <n-descriptions-item label="当前阶段">
        {{ String(state.current_stage ?? "-") || "-" }}
      </n-descriptions-item>
      <n-descriptions-item label="输出路径">
        <span class="status-card__path">{{ String(state.output_path ?? "-") || "-" }}</span>
      </n-descriptions-item>
      <n-descriptions-item label="创建时间">
        {{ String(state.created_at ?? "-") || "-" }}
      </n-descriptions-item>
      <n-descriptions-item label="更新时间">
        {{ String(state.updated_at ?? "-") || "-" }}
      </n-descriptions-item>
      <n-descriptions-item label="类型">
        {{ String(state.kind ?? "-") || "-" }}
      </n-descriptions-item>
    </n-descriptions>
    <n-alert
      v-if="String(state.error_message ?? '')"
      class="status-card__error"
      type="error"
      :title="String(state.error_message)"
    />
  </n-card>
</template>
