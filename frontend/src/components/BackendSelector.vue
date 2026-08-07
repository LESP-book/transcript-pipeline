<script setup lang="ts">
import { NSelect } from "naive-ui";
import { computed } from "vue";

const props = defineProps<{
  modelValue: string | null;
  options: string[];
  loading?: boolean;
  placeholder?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string | null];
}>();

const codexApiBackend = "codex_api";
const selectOptions = computed(() =>
  props.options
    .filter((value) => value === codexApiBackend)
    .map((value) => ({ label: "Codex API", value })),
);
</script>

<template>
  <n-select
    :value="modelValue"
    :options="selectOptions"
    :loading="loading"
    :placeholder="placeholder ?? '选择推理服务'"
    :disabled="disabled"
    clearable
    @update:value="emit('update:modelValue', $event)"
  />
</template>
