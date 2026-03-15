<script setup lang="ts">
import {
  NButton,
  NCard,
  NCheckbox,
  NEmpty,
  NFlex,
  NInput,
  NModal,
  NSpin,
  NTag,
  useMessage,
} from "naive-ui";
import { computed, ref, watch } from "vue";

import { listFs, type FileItem } from "../api/client";

const props = defineProps<{
  modelValue: string;
  mode: "file" | "dir";
  label: string;
  buttonText?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const message = useMessage();
const visible = ref(false);
const loading = ref(false);
const currentPath = ref("");
const parentPath = ref<string | null>(null);
const selectedPath = ref("");
const showHidden = ref(false);
const items = ref<FileItem[]>([]);

const storageKey = computed(() => `transcript-pipeline:file-browser:${props.label}`);

const segments = computed(() => {
  if (!currentPath.value) {
    return [];
  }
  const parts = currentPath.value.split("/").filter(Boolean);
  if (currentPath.value === "/") {
    return [{ label: "/", path: "/" }];
  }
  const mapped = parts.map((part, index) => ({
    label: part,
    path: `/${parts.slice(0, index + 1).join("/")}`,
  }));
  return [{ label: "/", path: "/" }, ...mapped];
});

const confirmDisabled = computed(() => {
  if (!selectedPath.value) {
    return true;
  }
  const selectedItem = items.value.find((item) => item.path === selectedPath.value);
  if (!selectedItem) {
    return false;
  }
  return props.mode === "dir" ? !selectedItem.is_dir : selectedItem.is_dir;
});

async function loadEntries(targetPath: string | null) {
  loading.value = true;
  try {
    const response = await listFs(targetPath, "all", showHidden.value);
    currentPath.value = response.current_path;
    parentPath.value = response.parent_path;
    items.value = response.items;
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "目录读取失败");
  } finally {
    loading.value = false;
  }
}

function open() {
  visible.value = true;
  selectedPath.value = props.modelValue;
  const rememberedPath = localStorage.getItem(storageKey.value);
  void loadEntries(props.modelValue || rememberedPath);
}

function close() {
  visible.value = false;
}

function selectItem(item: FileItem) {
  if (props.mode === "dir" && !item.is_dir) {
    return;
  }
  selectedPath.value = item.path;
}

function activateItem(item: FileItem) {
  if (item.is_dir) {
    void loadEntries(item.path);
    return;
  }
  if (props.mode === "file") {
    selectedPath.value = item.path;
    confirmSelection();
  }
}

function confirmSelection() {
  if (confirmDisabled.value) {
    return;
  }
  emit("update:modelValue", selectedPath.value || currentPath.value);
  localStorage.setItem(storageKey.value, selectedPath.value || currentPath.value);
  close();
}

watch(showHidden, () => {
  if (!visible.value) {
    return;
  }
  void loadEntries(currentPath.value);
});
</script>

<template>
  <div class="file-browser-field">
    <n-input :value="modelValue" :placeholder="`${label} 路径`" readonly />
    <n-button tertiary type="primary" @click="open">
      {{ buttonText ?? `选择${label}` }}
    </n-button>
  </div>

  <n-modal v-model:show="visible" preset="card" :style="{ width: 'min(960px, 92vw)' }">
    <n-card :title="`选择${label}`" closable @close="close">
      <n-flex vertical :size="16">
        <n-flex justify="space-between" align="center" wrap>
          <n-flex align="center" wrap>
            <n-button quaternary @click="parentPath && loadEntries(parentPath)">上一级</n-button>
            <n-button
              v-for="segment in segments"
              :key="segment.path"
              text
              class="file-browser__crumb"
              @click="loadEntries(segment.path)"
            >
              {{ segment.label }}
            </n-button>
          </n-flex>
          <n-checkbox v-model:checked="showHidden">显示隐藏文件</n-checkbox>
        </n-flex>

        <n-input :value="currentPath" readonly />

        <n-spin :show="loading">
          <div class="file-browser__list">
            <n-empty v-if="items.length === 0" description="当前目录为空" />
            <button
              v-for="item in items"
              :key="item.path"
              type="button"
              class="file-browser__item"
              :class="{ 'is-selected': selectedPath === item.path, 'is-disabled': mode === 'dir' && !item.is_dir }"
              @click="selectItem(item)"
              @dblclick="activateItem(item)"
            >
              <div>
                <strong>{{ item.name }}</strong>
                <div class="file-browser__path">{{ item.path }}</div>
              </div>
              <n-tag :type="item.is_dir ? 'info' : 'default'" size="small">
                {{ item.is_dir ? "目录" : "文件" }}
              </n-tag>
            </button>
          </div>
        </n-spin>

        <n-flex justify="space-between" align="center">
          <span class="file-browser__hint">
            {{ mode === "dir" ? "目录模式下不会确认文件。" : "双击文件可直接确认。" }}
          </span>
          <n-flex>
            <n-button @click="close">取消</n-button>
            <n-button type="primary" :disabled="confirmDisabled" @click="confirmSelection">
              确认选择
            </n-button>
          </n-flex>
        </n-flex>
      </n-flex>
    </n-card>
  </n-modal>
</template>
