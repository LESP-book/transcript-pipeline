<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  NConfigProvider,
  NDialogProvider,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NMessageProvider,
  NButton,
  darkTheme,
  type GlobalThemeOverrides,
} from "naive-ui";

import NavBar from "./components/NavBar.vue";

// Theme state with localStorage persistence
const isDark = ref(localStorage.getItem("transcript-pipeline:theme") === "dark");

function toggleTheme() {
  isDark.value = !isDark.value;
  localStorage.setItem("transcript-pipeline:theme", isDark.value ? "dark" : "light");
  updateClass();
}

function updateClass() {
  if (isDark.value) {
    document.documentElement.classList.add("dark-mode");
  } else {
    document.documentElement.classList.remove("dark-mode");
  }
}

onMounted(updateClass);

// Ultra-premium modern Indigo theme overrides for Naive UI, dynamically adapted for dark/light modes
const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const dark = isDark.value;
  return {
    common: {
      primaryColor: dark ? "#6366f1" : "#4f46e5",
      primaryColorHover: dark ? "#818cf8" : "#6366f1",
      primaryColorPressed: dark ? "#4f46e5" : "#3730a3",
      primaryColorSuppl: dark ? "rgba(99, 102, 241, 0.15)" : "rgba(79, 70, 229, 0.15)",
      
      infoColor: "#3b82f6",
      infoColorHover: "#60a5fa",
      successColor: "#10b981",
      successColorHover: "#34d399",
      warningColor: "#f59e0b",
      warningColorHover: "#fbbf24",
      errorColor: "#ef4444",
      errorColorHover: "#f87171",
      
      borderRadius: "12px",
      fontFamily: '"Outfit", "Inter", "Noto Sans SC", sans-serif',
    },
    Card: {
      borderRadius: "16px",
      titleFontSizeMedium: "18px",
      titleFontWeight: "700",
      boxShadow: dark
        ? "0 8px 32px 0 rgba(0, 0, 0, 0.35)"
        : "0 8px 32px 0 rgba(31, 38, 135, 0.04)",
    },
    Button: {
      borderRadiusMedium: "10px",
      fontWeight: "600",
      textColorGhost: dark ? "#818cf8" : "#4f46e5",
      textColorGhostHover: dark ? "#a5b4fc" : "#6366f1",
      textColorGhostPressed: dark ? "#6366f1" : "#3730a3",
    },
    Input: {
      borderRadius: "10px",
      borderFocus: dark ? "1px solid #6366f1" : "1px solid #4f46e5",
      boxShadowFocus: dark ? "0 0 0 3px rgba(99, 102, 241, 0.15)" : "0 0 0 3px rgba(79, 70, 229, 0.15)",
    },
    Select: {
      peers: {
        InternalSelection: {
          borderRadius: "10px",
          borderFocus: dark ? "1px solid #6366f1" : "1px solid #4f46e5",
          boxShadowFocus: dark ? "0 0 0 3px rgba(99, 102, 241, 0.15)" : "0 0 0 3px rgba(79, 70, 229, 0.15)",
        },
      },
    },
    Dialog: {
      borderRadius: "16px",
    },
  };
});
</script>

<template>
  <n-config-provider :theme="isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <n-dialog-provider>
      <n-message-provider>
        <!-- Fluid Ambient Floating Glow Background -->
        <div class="bg-glow-container">
          <div class="glow-orb glow-orb-1"></div>
          <div class="glow-orb glow-orb-2"></div>
          <div class="glow-orb glow-orb-3"></div>
        </div>

        <n-layout class="app-shell">
          <n-layout-header class="app-shell__header">
            <div class="app-shell__brand">
              <span class="app-shell__eyebrow">Transcript Pipeline</span>
              <h1 class="app-shell__title">任务整理面板</h1>
            </div>
            <NavBar />
            
            <n-button
              quaternary
              circle
              @click="toggleTheme"
              class="theme-toggle-btn"
              title="切换主题"
            >
              <template #icon>
                <svg v-if="isDark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="theme-btn-icon">
                  <circle cx="12" cy="12" r="4"/>
                  <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="theme-btn-icon">
                  <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
                </svg>
              </template>
            </n-button>
          </n-layout-header>
          <n-layout-content class="app-shell__content">
            <router-view />
          </n-layout-content>
        </n-layout>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>
