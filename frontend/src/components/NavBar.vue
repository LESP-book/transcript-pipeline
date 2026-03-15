<script setup lang="ts">
import { NMenu, type MenuOption } from "naive-ui";
import { computed, h } from "vue";
import { RouterLink, useRoute } from "vue-router";

const route = useRoute();

const menuOptions = computed<MenuOption[]>(() => [
  {
    key: "/single-job",
    label: () => h(RouterLink, { to: "/single-job" }, { default: () => "单任务" }),
  },
  {
    key: "/batch-job",
    label: () => h(RouterLink, { to: "/batch-job" }, { default: () => "批量任务" }),
  },
  {
    key: "/stage-runner",
    label: () => h(RouterLink, { to: "/stage-runner" }, { default: () => "单阶段" }),
  },
  {
    key: "/jobs",
    label: () => h(RouterLink, { to: "/jobs" }, { default: () => "任务列表" }),
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
