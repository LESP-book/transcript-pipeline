<script setup lang="ts">
import { NAlert, NCard, NDescriptions, NDescriptionsItem, NTag, NFlex, NButton, useMessage, useDialog } from "naive-ui";
import { computed, ref } from "vue";
import { deleteJob, deleteBatch, deleteStageRun } from "../api/client";

const props = defineProps<{
  title?: string;
  state: Record<string, unknown>;
}>();

const emit = defineEmits<{
  (e: "deleted"): void;
}>();

const message = useMessage();
const dialog = useDialog();

const isDeleting = ref(false);

const canDelete = computed(() => {
  const status = String(props.state.status ?? "");
  return status !== "running" && status !== "pending";
});

function handleDelete() {
  dialog.warning({
    title: "确认删除",
    content: "确定要物理删除此条历史记录吗？此操作不可逆，将永久删除关联的数据状态与缓存文件！",
    positiveText: "确定删除",
    negativeText: "不删除",
    onPositiveClick: async () => {
      isDeleting.value = true;
      try {
        const id = String(props.state.id ?? "");
        const kind = String(props.state.kind ?? "");
        if (kind === "job") {
          await deleteJob(id);
        } else if (kind === "batch") {
          await deleteBatch(id);
        } else if (kind === "stage-run") {
          await deleteStageRun(id);
        } else {
          throw new Error(`未知的任务类型: ${kind}`);
        }
        message.success("删除成功");
        emit("deleted");
      } catch (caught) {
        message.error(caught instanceof Error ? caught.message : "删除失败");
      } finally {
        isDeleting.value = false;
      }
    }
  });
}

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

const isRunning = computed(() => String(props.state.status ?? "") === "running");

// Pipeline definitions
const PIPELINE_STAGES = [
  { key: "extract-audio", label: "音频提取", index: 1 },
  { key: "transcribe", label: "语音转写", index: 2 },
  { key: "prepare-reference", label: "准备参考", index: 3 },
  { key: "align", label: "文本对齐", index: 4 },
  { key: "classify", label: "段落分类", index: 5 },
  { key: "refine", label: "校对润色", index: 6 },
  { key: "export-markdown", label: "导出文档", index: 7 },
];

// Intelligently calculate state of each step
function getStepState(stageKey: string): "completed" | "active" | "failed" | "pending" {
  const status = String(props.state.status ?? "");
  const currentStage = String(props.state.current_stage ?? props.state.failed_stage ?? "");
  
  const stageIndex = PIPELINE_STAGES.findIndex((s) => s.key === stageKey);
  const currentStageIndex = PIPELINE_STAGES.findIndex((s) => s.key === currentStage);
  
  if (status === "success") {
    return "completed";
  }
  
  if (status === "failed") {
    if (currentStage === stageKey) {
      return "failed";
    }
    if (currentStageIndex !== -1 && stageIndex < currentStageIndex) {
      return "completed";
    }
    // If it failed at a stage but we don't have perfect alignment, show failed on the matching stage
    return "pending";
  }
  
  if (status === "running") {
    if (currentStage === stageKey) {
      return "active";
    }
    if (currentStageIndex !== -1) {
      return stageIndex < currentStageIndex ? "completed" : "pending";
    }
    // Default to first stage active if running but no stage specified yet
    return stageIndex === 0 ? "active" : "pending";
  }
  
  return "pending";
}
</script>

<template>
  <n-card :title="title ?? String(state.id ?? '任务状态')" class="status-card" size="medium">
    <template #header-extra>
      <n-flex align="center" :size="12">
        <!-- Breath Dot Pulse -->
        <span
          class="status-pulse"
          :class="{
            'is-running': isRunning,
            'is-success': state.status === 'success',
            'is-error': state.status === 'failed'
          }"
        ></span>
        <n-tag :type="statusType" round size="medium" :bordered="false" class="status-badge">
          {{ String(state.status ?? "-") }}
        </n-tag>
        <n-button
          v-if="canDelete"
          type="error"
          size="small"
          quaternary
          :loading="isDeleting"
          @click.stop="handleDelete"
          class="delete-btn"
        >
          <template #icon>
            <span>🗑</span>
          </template>
          删除历史
        </n-button>
      </n-flex>
    </template>

    <n-flex vertical :size="20">
      <!-- High-Tech Pipeline Step Indicator -->
      <div class="pipeline-section">
        <h4 class="pipeline-title">流水线处理进度 (Pipeline Progress)</h4>
        <div class="pipeline-flow">
          <div
            v-for="stage in PIPELINE_STAGES"
            :key="stage.key"
            class="pipeline-step"
            :class="{
              'is-completed': getStepState(stage.key) === 'completed',
              'is-active': getStepState(stage.key) === 'active',
              'is-failed': getStepState(stage.key) === 'failed'
            }"
          >
            <div class="pipeline-step__circle">
              <!-- Visual Indicator Icons inside Circle -->
              <span v-if="getStepState(stage.key) === 'completed'">✓</span>
              <span v-else-if="getStepState(stage.key) === 'failed'">✕</span>
              <span v-else>{{ stage.index }}</span>
            </div>
            <span class="pipeline-step__label">{{ stage.label }}</span>
          </div>
        </div>
      </div>

      <!-- Compact & Elegant Descriptions Grid -->
      <n-descriptions label-placement="left" :column="2" size="medium" bordered class="status-grid">
        <n-descriptions-item label="当前运行阶段">
          <span class="font-semibold">{{ String(state.current_stage ?? "-") || "-" }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="任务类型 (Kind)">
          <n-tag size="small" :bordered="false" type="info">{{ String(state.kind ?? "-") || "-" }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="输出目录 / 文件" :span="2">
          <span class="status-card__path">{{ String(state.output_path ?? "-") || "-" }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="创建时间">
          <span class="text-muted">{{ String(state.created_at ?? "-") || "-" }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="更新时间">
          <span class="text-muted">{{ String(state.updated_at ?? "-") || "-" }}</span>
        </n-descriptions-item>
        
        <template v-if="state.total !== undefined">
          <n-descriptions-item label="视频总任务数">
            {{ String(state.total ?? "-") || "-" }}
          </n-descriptions-item>
          <n-descriptions-item label="状态统计">
            <n-flex :size="8">
              <n-tag size="small" type="success" :bordered="false">成功 {{ String(state.success ?? 0) }}</n-tag>
              <n-tag size="small" type="error" :bordered="false">失败 {{ String(state.failed ?? 0) }}</n-tag>
            </n-flex>
          </n-descriptions-item>
        </template>
      </n-descriptions>

      <!-- Glassmorphic Elegant Error Block -->
      <n-alert
        v-if="String(state.error_message ?? '')"
        class="status-card__error"
        type="error"
        :title="`流水线执行错误报告`"
        :bordered="false"
      >
        <p class="error-text-content">{{ String(state.error_message) }}</p>
      </n-alert>
    </n-flex>
  </n-card>
</template>

<style scoped>
.status-card {
  transition: all 0.3s ease;
  overflow: visible;
}

.status-badge {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 4px 12px;
}

.pipeline-section {
  background: rgba(248, 250, 252, 0.4);
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.8);
}

.pipeline-title {
  margin: 0 0 16px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.status-grid {
  background: #ffffff;
  border-radius: 12px;
  overflow: hidden;
}

.font-semibold {
  font-weight: 600;
  color: var(--primary);
}

.text-muted {
  font-size: 13px;
  color: var(--text-muted);
}

.status-card__path {
  font-family: monospace;
  font-size: 12px;
  color: #475569;
  word-break: break-all;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid rgba(226, 232, 240, 0.6);
  display: block;
}

.status-card__error {
  backdrop-filter: blur(8px);
  background: rgba(254, 242, 242, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 12px;
}

.error-text-content {
  margin: 4px 0 0;
  font-family: monospace;
  font-size: 12px;
  color: #b91c1c;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.delete-btn {
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.delete-btn:hover {
  transform: translateY(-1px) scale(1.05);
}
.delete-btn:active {
  transform: translateY(0) scale(0.95);
}
</style>
