<script setup lang="ts">
import { NSelect } from "naive-ui";
import { computed } from "vue";

const props = defineProps<{
  modelValue: string | null;
  options: string[];
  loading?: boolean;
  placeholder?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string | null];
}>();

const selectOptions = computed(() => props.options.map((value) => ({ label: value, value })));
</script>

<template>
  <n-select
    :value="modelValue"
    :options="selectOptions"
    :loading="loading"
    :placeholder="placeholder ?? '选择 profile'"
    clearable
    @update:value="emit('update:modelValue', $event)"
  />
</template>
