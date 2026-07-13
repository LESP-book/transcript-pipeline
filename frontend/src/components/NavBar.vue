<script setup lang="ts">
import { NMenu, type MenuOption } from "naive-ui";
import { computed, h } from "vue";
import { RouterLink, useRoute } from "vue-router";

const route = useRoute();

// Simple Helper to render premium inline SVG icons
function renderIcon(svgPath: string) {
  return () =>
    h(
      "svg",
      {
        xmlns: "http://www.w3.org/2000/svg",
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        "stroke-width": "2.2",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        style: { width: "18px", height: "18px", transition: "transform 0.3s ease" },
      },
      [h("path", { d: svgPath })]
    );
}

const menuOptions = computed<MenuOption[]>(() => [
  {
    key: "/single-job",
    label: () => h(RouterLink, { to: "/single-job" }, { default: () => "单任务" }),
    icon: renderIcon("M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2zM14 2v6h6"),
  },
  {
    key: "/batch-job",
    label: () => h(RouterLink, { to: "/batch-job" }, { default: () => "批量任务" }),
    icon: renderIcon("M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4 M2 17h2 M2 13h2 M2 9h2"),
  },
  {
    key: "/stage-runner",
    label: () => h(RouterLink, { to: "/stage-runner" }, { default: () => "单阶段" }),
    icon: renderIcon("M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM12 22V12 M12 12L4 7.5 M12 12l8-4.5"),
  },
  {
    key: "/pdf-book-ocr",
    label: () => h(RouterLink, { to: "/pdf-book-ocr" }, { default: () => "PDF OCR" }),
    icon: renderIcon("M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5"),
  },
  {
    key: "/jobs",
    label: () => h(RouterLink, { to: "/jobs" }, { default: () => "任务列表" }),
    icon: renderIcon("M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"),
  },
  {
    key: "/settings",
    label: () => h(RouterLink, { to: "/settings" }, { default: () => "运行设置" }),
    icon: renderIcon("M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"),
  },
]);
</script>

<template>
  <n-menu
    mode="horizontal"
    :value="route.path"
    :options="menuOptions"
    responsive
    class="nav-menu"
  />
</template>

<style scoped>
:deep(.n-menu-item-content) {
  padding: 0 18px !important;
  font-weight: 500 !important;
}

:deep(.n-menu-item-content:hover .n-menu-item-content-header) {
  color: var(--primary) !important;
}

:deep(.n-menu-item-content:hover svg) {
  transform: translateY(-2px);
  color: var(--primary);
}
</style>
