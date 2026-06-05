<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NCollapseTransition,
  NDescriptions,
  NDescriptionsItem,
  NFlex,
  NSelect,
  NTag,
  useDialog,
  useMessage,
} from "naive-ui";
import { computed, ref, watch } from "vue";
import {
  batchItemResultUrl,
  batchResultUrl,
  deleteBatch,
  deleteJob,
  deleteStageRun,
  jobResultUrl,
  rerunJob,
  type BatchItemState,
} from "../api/client";
import JobArtifactsViewer from "./JobArtifactsViewer.vue";

const props = defineProps<{
  title?: string;
  state: Record<string, unknown>;
  defaultExpanded?: boolean;
}>();

const emit = defineEmits<{
  (e: "deleted"): void;
  (e: "rerun", jobId: string): void;
}>();

const message = useMessage();
const dialog = useDialog();

const isDeleting = ref(false);
const isRerunning = ref(false);
const rerunStage = ref("refine");
const expanded = ref(props.defaultExpanded ?? false);

const kind = computed(() => String(props.state.kind ?? ""));
const status = computed(() => String(props.state.status ?? ""));
const stateId = computed(() => String(props.state.id ?? ""));
const batchItems = computed<BatchItemState[]>(() => {
  return Array.isArray(props.state.items) ? (props.state.items as BatchItemState[]) : [];
});
const hasBatchItems = computed(() => batchItems.value.length > 0);
const hasBatchOutputs = computed(() => {
  return batchItems.value.some((item) => item.status === "success" && Boolean(item.copied_output_path));
});

watch(
  () => stateId.value,
  () => {
    expanded.value = props.defaultExpanded ?? false;
  },
);

const canDelete = computed(() => {
  return status.value !== "running" && status.value !== "pending";
});

const canRerun = computed(() => {
  return kind.value === "job" && status.value !== "running" && status.value !== "pending";
});

const canViewArtifacts = computed(() => kind.value === "job");
const canDownloadSingleResult = computed(() => kind.value === "job" && status.value === "success" && Boolean(props.state.output_path));
const canDownloadBatchResult = computed(() => kind.value === "batch" && hasBatchOutputs.value);

function openDownload(url: string) {
  window.location.href = url;
}

function handleSingleResultDownload() {
  if (!stateId.value) {
    message.error("缺少任务 ID，无法下载结果。");
    return;
  }
  openDownload(jobResultUrl(stateId.value));
}

function handleBatchResultDownload() {
  if (!stateId.value) {
    message.error("缺少批量任务 ID，无法下载结果。");
    return;
  }
  openDownload(batchResultUrl(stateId.value));
}

function handleBatchItemResultDownload(item: BatchItemState) {
  if (!stateId.value || !item.job_id) {
    message.error("缺少批量子任务 ID，无法下载结果。");
    return;
  }
  openDownload(batchItemResultUrl(stateId.value, item.job_id));
}

function displayFileName(path?: string) {
  const normalized = String(path || "").trim();
  if (!normalized) {
    return "-";
  }
  return normalized.split(/[\\/]/).pop() || normalized;
}

function itemStatusType(rawStatus?: string): "success" | "error" | "info" | "warning" {
  if (rawStatus === "success") {
    return "success";
  }
  if (rawStatus === "failed") {
    return "error";
  }
  if (rawStatus === "running") {
    return "info";
  }
  return "warning";
}

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

const statusType = computed<"success" | "error" | "info" | "warning">(() => {
  if (status.value === "success") {
    return "success";
  }
  if (status.value === "failed") {
    return "error";
  }
  if (status.value === "running") {
    return "info";
  }
  return "warning";
});

const isRunning = computed(() => status.value === "running");

const MAIN_PIPELINE_STAGES = [
  { key: "extract-audio", label: "音频提取", index: 1 },
  { key: "transcribe", label: "语音转写", index: 2 },
  { key: "prepare-reference", label: "准备参考", index: 3 },
  { key: "refine", label: "校对润色", index: 4 },
  { key: "export-markdown", label: "导出文档", index: 5 },
];

const DEBUG_PIPELINE_STAGES = [
  { key: "extract-audio", label: "音频提取", index: 1 },
  { key: "transcribe", label: "语音转写", index: 2 },
  { key: "prepare-reference", label: "准备参考", index: 3 },
  { key: "align", label: "文本对齐", index: 4 },
  { key: "classify", label: "段落分类", index: 5 },
  { key: "refine", label: "校对润色", index: 6 },
  { key: "export-markdown", label: "导出文档", index: 7 },
];

const pipelineStages = computed(() => {
  return kind.value === "stage-run" ? DEBUG_PIPELINE_STAGES : MAIN_PIPELINE_STAGES;
});

const rerunStageOptions = computed(() => MAIN_PIPELINE_STAGES.map((stage) => ({
  label: `${stage.label} (${stage.key})`,
  value: stage.key,
})));
const rerunStageKeys = computed(() => new Set(MAIN_PIPELINE_STAGES.map((stage) => stage.key)));

watch(
  () => String(props.state.current_stage ?? ""),
  (currentStage) => {
    if (rerunStageKeys.value.has(currentStage)) {
      rerunStage.value = currentStage;
    }
  },
  { immediate: true },
);

async function handleRerun() {
  const id = String(props.state.id ?? "");
  if (!id) {
    message.error("缺少任务 ID，无法重跑。");
    return;
  }
  isRerunning.value = true;
  try {
    await rerunJob(id, { start_stage: rerunStage.value });
    message.success(`已从 ${rerunStage.value} 重新启动任务`);
    emit("rerun", id);
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : "重跑任务失败");
  } finally {
    isRerunning.value = false;
  }
}

// Intelligently calculate state of each step
function getStepState(stageKey: string): "completed" | "active" | "failed" | "pending" {
  const currentStage = String(props.state.current_stage ?? props.state.failed_stage ?? "");
  
  const stageIndex = pipelineStages.value.findIndex((s) => s.key === stageKey);
  const currentStageIndex = pipelineStages.value.findIndex((s) => s.key === currentStage);
  
  if (status.value === "success") {
    return "completed";
  }
  
  if (status.value === "failed") {
    if (currentStage === stageKey) {
      return "failed";
    }
    if (currentStageIndex !== -1 && stageIndex < currentStageIndex) {
      return "completed";
    }
    return "pending";
  }
  
  if (status.value === "running") {
    if (currentStage === stageKey) {
      return "active";
    }
    if (currentStageIndex !== -1) {
      return stageIndex < currentStageIndex ? "completed" : "pending";
    }
    return stageIndex === 0 ? "active" : "pending";
  }
  
  return "pending";
}
</script>

<template>
  <n-card :title="title ?? String(state.id ?? '任务状态')" class="status-card" size="medium">
    <template #header-extra>
      <n-flex align="center" :size="10" wrap>
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
          v-if="canDownloadSingleResult"
          type="success"
          size="small"
          secondary
          @click.stop="handleSingleResultDownload"
        >
          下载结果
        </n-button>
        <n-button
          v-if="canDownloadBatchResult"
          type="success"
          size="small"
          secondary
          @click.stop="handleBatchResultDownload"
        >
          下载全部结果
        </n-button>
        <n-button size="small" secondary @click.stop="expanded = !expanded">
          {{ expanded ? "收起详情" : "展开详情" }}
        </n-button>
        <n-button
          v-if="canDelete"
          type="error"
          size="small"
          quaternary
          :loading="isDeleting"
          @click.stop="handleDelete"
          class="delete-btn"
        >
          删除
        </n-button>
      </n-flex>
    </template>

    <n-flex vertical :size="16">
      <div class="status-summary">
        <div class="summary-cell">
          <span class="summary-label">当前阶段</span>
          <strong>{{ String(state.current_stage ?? "-") || "-" }}</strong>
        </div>
        <div class="summary-cell">
          <span class="summary-label">任务类型</span>
          <strong>{{ String(state.kind ?? "-") || "-" }}</strong>
        </div>
        <div class="summary-cell">
          <span class="summary-label">更新时间</span>
          <strong>{{ String(state.updated_at ?? "-") || "-" }}</strong>
        </div>
        <div v-if="state.total !== undefined" class="summary-cell is-wide">
          <span class="summary-label">批量进度</span>
          <n-flex :size="8" align="center" wrap>
            <n-tag size="small" type="info" :bordered="false">总数 {{ String(state.total ?? 0) }}</n-tag>
            <n-tag size="small" type="success" :bordered="false">成功 {{ String(state.success ?? 0) }}</n-tag>
            <n-tag size="small" type="error" :bordered="false">失败 {{ String(state.failed ?? 0) }}</n-tag>
          </n-flex>
        </div>
      </div>

      <n-alert
        v-if="canDownloadSingleResult"
        type="success"
        :bordered="false"
        class="result-hint"
      >
        结果已保存在服务器，局域网使用者可直接点击“下载结果”获取最终 Markdown。
      </n-alert>
      <n-alert
        v-else-if="canDownloadBatchResult"
        type="success"
        :bordered="false"
        class="result-hint"
      >
        批量任务已产生可下载结果，可下载全部成功产物，也可展开后按子任务分别下载。
      </n-alert>

      <n-collapse-transition :show="expanded">
        <n-flex vertical :size="20" class="status-detail">
          <div class="pipeline-section">
            <h4 class="pipeline-title">流水线处理进度 (Pipeline Progress)</h4>
            <div class="pipeline-flow">
              <div
                v-for="stage in pipelineStages"
                :key="stage.key"
                class="pipeline-step"
                :class="{
                  'is-completed': getStepState(stage.key) === 'completed',
                  'is-active': getStepState(stage.key) === 'active',
                  'is-failed': getStepState(stage.key) === 'failed'
                }"
              >
                <div class="pipeline-step__circle">
                  <span v-if="getStepState(stage.key) === 'completed'">✓</span>
                  <span v-else-if="getStepState(stage.key) === 'failed'">✕</span>
                  <span v-else>{{ stage.index }}</span>
                </div>
                <span class="pipeline-step__label">{{ stage.label }}</span>
              </div>
            </div>
          </div>

          <div v-if="canRerun" class="rerun-section">
            <div>
              <h4 class="rerun-title">从指定阶段重新运行</h4>
              <p class="rerun-copy">复用当前任务的输入、中间目录和生成配置，只从所选阶段继续执行后续流水线。</p>
            </div>
            <n-flex align="center" :size="10" wrap>
              <n-select
                v-model:value="rerunStage"
                :options="rerunStageOptions"
                class="rerun-select"
              />
              <n-button
                type="primary"
                secondary
                :loading="isRerunning"
                @click="handleRerun"
              >
                从该阶段重跑
              </n-button>
            </n-flex>
          </div>

          <JobArtifactsViewer
            v-if="canViewArtifacts"
            :job-id="String(state.id ?? '')"
          />

          <div v-if="hasBatchItems" class="batch-items-section">
            <div class="batch-items-section__head">
              <h4 class="batch-items-title">批量子任务列表</h4>
              <span class="batch-items-count">{{ batchItems.length }} 个子任务</span>
            </div>
            <div class="batch-items-list">
              <div
                v-for="(item, index) in batchItems"
                :key="item.job_id || index"
                class="batch-item-row"
              >
                <div class="batch-item-main">
                  <strong>{{ item.job_id || `子任务 ${index + 1}` }}</strong>
                  <span>{{ displayFileName(item.video_source) }}</span>
                  <span v-if="item.failed_stage" class="batch-item-muted">失败阶段：{{ item.failed_stage }}</span>
                  <p v-if="item.error_message" class="batch-item-error">{{ item.error_message }}</p>
                </div>
                <n-flex align="center" :size="8" wrap>
                  <n-tag size="small" :type="itemStatusType(item.status)" :bordered="false">
                    {{ item.status || "-" }}
                  </n-tag>
                  <n-button
                    size="small"
                    type="primary"
                    secondary
                    :disabled="item.status !== 'success' || !item.copied_output_path"
                    @click="handleBatchItemResultDownload(item)"
                  >
                    下载结果
                  </n-button>
                </n-flex>
              </div>
            </div>
          </div>

          <n-descriptions label-placement="left" :column="2" size="medium" bordered class="status-grid">
            <n-descriptions-item label="当前运行阶段">
              <span class="font-semibold">{{ String(state.current_stage ?? "-") || "-" }}</span>
            </n-descriptions-item>
            <n-descriptions-item label="任务类型 (Kind)">
              <n-tag size="small" :bordered="false" type="info">{{ String(state.kind ?? "-") || "-" }}</n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="服务器保存路径" :span="2">
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
      </n-collapse-transition>
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

.status-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.summary-cell {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(226, 232, 240, 0.78);
  border-radius: 8px;
  background: #f8fafc;
}

.summary-cell.is-wide {
  grid-column: 1 / -1;
}

.summary-cell strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.summary-label {
  color: var(--text-muted);
  font-size: 12px;
}

.result-hint {
  border-radius: 8px;
}

.status-detail {
  padding-top: 4px;
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

.rerun-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border: 1px solid rgba(79, 70, 229, 0.16);
  border-radius: 12px;
  background: rgba(79, 70, 229, 0.06);
}

.rerun-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.rerun-copy {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.rerun-select {
  min-width: 260px;
}

.batch-items-section {
  padding: 16px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 12px;
  background: #ffffff;
}

.batch-items-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.batch-items-title {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
}

.batch-items-count {
  color: var(--text-muted);
  font-size: 12px;
}

.batch-items-list {
  display: grid;
  gap: 10px;
}

.batch-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 8px;
  background: #f8fafc;
}

.batch-item-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.batch-item-main strong {
  color: var(--text-primary);
  font-size: 13px;
}

.batch-item-main span {
  color: var(--text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.batch-item-muted {
  color: #b45309 !important;
}

.batch-item-error {
  margin: 2px 0 0;
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
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

@media (max-width: 760px) {
  .status-summary {
    grid-template-columns: 1fr;
  }

  .rerun-section {
    align-items: stretch;
    flex-direction: column;
  }

  .rerun-select {
    min-width: 100%;
  }

  .batch-items-section__head,
  .batch-item-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
