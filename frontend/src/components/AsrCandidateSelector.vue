<script setup lang="ts">
import { NSelect } from "naive-ui";
import { computed } from "vue";
import type { AsrCandidate } from "../api/client";

const props = defineProps<{
  modelValue: string;
  options: AsrCandidate[];
  loading?: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const selectOptions = computed(() => props.options.map((candidate) => ({
  label: candidate.label + (candidate.dependency_status === "installed" ? "" : "（依赖不可用）"),
  value: candidate.id,
  disabled: candidate.dependency_status !== "installed",
})));
</script>

<template>
  <div class="asr-candidate-selector">
    <n-select
      :value="modelValue || null"
      :options="selectOptions"
      :loading="loading"
      placeholder="选择语音转文字模型"
      @update:value="emit('update:modelValue', String($event || ''))"
    />
    <p>依赖已安装不等于模型已验证。其它候选不使用配置方案中的 Whisper 模型、精度或 beam 参数。</p>
  </div>
</template>

<style scoped>
.asr-candidate-selector { width: 100%; min-width: 0; }
p { margin: 6px 0 0; font-size: 12px; line-height: 1.5; color: var(--n-text-color-3, #888); }
</style>
