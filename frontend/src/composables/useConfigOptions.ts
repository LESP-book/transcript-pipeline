import { onMounted, ref } from "vue";

import { getConfig } from "../api/client";

export function useConfigOptions() {
  const profiles = ref<string[]>([]);
  const backends = ref<string[]>([]);
  const videoExtensions = ref<string[]>([]);
  const referenceExtensions = ref<string[]>([]);
  const activeProfile = ref("");
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
    loading,
    error,
    reload: load,
  };
}
