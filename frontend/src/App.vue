<script setup lang="ts">
import {
  NConfigProvider,
  NDialogProvider,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NMessageProvider,
  type GlobalThemeOverrides,
} from "naive-ui";

import NavBar from "./components/NavBar.vue";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#1f6feb",
    primaryColorHover: "#387ded",
    primaryColorPressed: "#1957ba",
    borderRadius: "12px",
  },
  Card: {
    borderRadius: "18px",
  },
  Input: {
    borderRadius: "12px",
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius: "12px",
      },
    },
  },
};
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-dialog-provider>
      <n-message-provider>
        <n-layout class="app-shell">
          <n-layout-header bordered class="app-shell__header">
            <div class="app-shell__brand">
              <span class="app-shell__eyebrow">Transcript Pipeline</span>
              <h1 class="app-shell__title">本地任务面板</h1>
            </div>
            <NavBar />
          </n-layout-header>
          <n-layout-content class="app-shell__content">
            <router-view />
          </n-layout-content>
        </n-layout>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>
