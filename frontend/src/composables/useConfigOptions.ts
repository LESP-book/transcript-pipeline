import { onMounted, ref } from "vue";

import { getConfig, getFrontendSettings } from "../api/client";

export function useConfigOptions() {
  const profiles = ref<string[]>([]);
  const backends = ref<string[]>([]);
  const videoExtensions = ref<string[]>([]);
  const referenceExtensions = ref<string[]>([]);
  const activeProfile = ref("");
  const defaultBackend = ref("");
  const defaultOcrBackend = ref("");
  const defaultOcrModel = ref("");
  const defaultOcrReasoningEffort = ref("");
  const defaultOcrMaxConcurrency = ref(40);
  const defaultOcrSubmitIntervalSeconds = ref(5);
  const defaultOutputDir = ref("");
  const uploadDir = ref("");
  const loading = ref(false);
  const error = ref("");

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const config = await getConfig();
      profiles.value = config.profiles;
      backends.value = config.backends;
      videoExtensions.value = config.video_extensions;
      referenceExtensions.value = config.reference_extensions;
      activeProfile.value = config.active_profile;
      defaultBackend.value = config.default_backend || config.configured_backends[0] || "";
      defaultOutputDir.value = config.default_output_dir;
      uploadDir.value = config.upload_dir;

      const settings = await getFrontendSettings();
      defaultOcrBackend.value = config.default_ocr_backend || settings.ocr_backend;
      defaultOcrModel.value = settings.ocr_model;
      defaultOcrReasoningEffort.value = settings.ocr_reasoning_effort;
      defaultOcrMaxConcurrency.value = settings.ocr_max_concurrency;
      defaultOcrSubmitIntervalSeconds.value = settings.ocr_submit_interval_seconds;
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : "加载配置失败";
    } finally {
      loading.value = false;
    }
  }

  onMounted(load);

  return {
    profiles,
    backends,
    videoExtensions,
    referenceExtensions,
    activeProfile,
    defaultBackend,
    defaultOcrBackend,
    defaultOcrModel,
    defaultOcrReasoningEffort,
    defaultOcrMaxConcurrency,
    defaultOcrSubmitIntervalSeconds,
    defaultOutputDir,
    uploadDir,
    loading,
    error,
    reload: load,
  };
}
