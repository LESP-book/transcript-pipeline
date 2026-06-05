<script setup lang="ts">
import { NButton, NFlex, NProgress, NTag, useMessage } from "naive-ui";
import { computed, ref } from "vue";

import { uploadFile, type UploadKind, type UploadResponse } from "../api/client";

const props = defineProps<{
  modelValue: string;
  kind: Extract<UploadKind, "video" | "reference">;
  label: string;
  extensions: string[];
  buttonText?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

type FileWithRelativePath = File & { webkitRelativePath?: string };

const message = useMessage();
const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const uploadedCount = ref(0);
const totalCount = ref(0);
const ignoredCount = ref(0);
const uploadedDirectory = ref("");

const accept = computed(() => props.extensions.join(","));
const progressPercentage = computed(() => {
  if (!totalCount.value) {
    return 0;
  }
  return Math.round((uploadedCount.value / totalCount.value) * 100);
});

function openDirectoryPicker() {
  fileInput.value?.click();
}

function extensionOf(file: File): string {
  const dotIndex = file.name.lastIndexOf(".");
  return dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : "";
}

function createUploadGroupId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function handleDirectoryChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const selectedFiles = Array.from(input.files ?? []) as FileWithRelativePath[];
  if (selectedFiles.length === 0) {
    return;
  }

  const allowedExtensions = new Set(props.extensions.map((extension) => extension.toLowerCase()));
  const files = selectedFiles.filter((file) => allowedExtensions.has(extensionOf(file)));
  ignoredCount.value = selectedFiles.length - files.length;
  totalCount.value = files.length;
  uploadedCount.value = 0;
  uploadedDirectory.value = "";

  if (files.length === 0) {
    message.warning(`所选目录中没有可上传的${props.label}文件。`);
    input.value = "";
    return;
  }

  uploading.value = true;
  const groupId = createUploadGroupId();
  let lastResponse: UploadResponse | null = null;
  try {
    for (const file of files) {
      lastResponse = await uploadFile(file, props.kind, {
        groupId,
        relativePath: file.webkitRelativePath || file.name,
      });
      uploadedCount.value += 1;
    }
    if (lastResponse) {
      uploadedDirectory.value = lastResponse.directory;
      emit("update:modelValue", lastResponse.directory);
    }
    const ignoredText = ignoredCount.value ? `，已跳过 ${ignoredCount.value} 个非目标文件` : "";
    message.success(`已上传 ${files.length} 个${props.label}文件${ignoredText}`);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "目录上传失败");
  } finally {
    uploading.value = false;
    input.value = "";
  }
}
</script>

<template>
  <n-flex vertical :size="8" class="remote-directory-upload">
    <n-flex align="center" :size="8" wrap>
      <input
        ref="fileInput"
        type="file"
        :accept="accept"
        multiple
        webkitdirectory
        directory
        class="remote-directory-upload__input"
        @change="handleDirectoryChange"
      />
      <n-button secondary type="primary" :loading="uploading" @click="openDirectoryPicker" class="remote-directory-upload__button">
        {{ buttonText ?? `上传本机${label}目录` }}
      </n-button>
      <n-tag v-if="uploadedDirectory" size="small" type="success" :bordered="false" class="remote-directory-upload__tag">
        {{ uploadedCount }} 个文件
      </n-tag>
      <n-tag v-if="ignoredCount" size="small" type="warning" :bordered="false">
        跳过 {{ ignoredCount }} 个
      </n-tag>
    </n-flex>
    <n-progress
      v-if="uploading"
      type="line"
      :percentage="progressPercentage"
      :height="6"
      :show-indicator="false"
    />
  </n-flex>
</template>

<style scoped>
.remote-directory-upload {
  min-width: 0;
}

.remote-directory-upload__input {
  display: none;
}

.remote-directory-upload__button {
  border-radius: 8px;
}

.remote-directory-upload__tag {
  max-width: min(360px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
