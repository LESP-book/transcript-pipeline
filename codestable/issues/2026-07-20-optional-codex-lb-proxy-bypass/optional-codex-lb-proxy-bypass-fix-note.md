---
doc_type: issue-fix
issue: 2026-07-20-optional-codex-lb-proxy-bypass
status: implemented
path: fast-track
fix_date: 2026-07-20
tags: [codex-lb, proxy, no-proxy, wsl, frontend-settings]
---

# Codex API 可选直连开关修复记录

## 1. 问题描述

WSL Web 服务会继承启动终端中的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`。现场三视频批量校对在
不经过本机代理时全部成功，但用户不希望项目无条件强制 redworker 直连，需要一个可持久化、可随时
关闭的选择。

## 2. 根因

原有 Web 设置只能保存 codex-lb Base URL 和 API Key；任务环境上下文会临时应用这两个字段，但没有
代理路由选项。因此只要启动进程继承了代理变量，所有新任务都会继续使用该代理，除非人工重启并提前
设置 `NO_PROXY`。

## 3. 修复方案

1. 新增持久化布尔设置 `codex_lb_bypass_proxy`，默认 `false`，旧设置文件自动保持关闭。
2. 设置页增加“API 直连（绕过代理）”开关，保存后对新任务生效，不要求重启 Web 服务。
3. 开启时从当前 codex-lb Base URL 解析主机名，只把该主机临时合并进 `NO_PROXY` / `no_proxy`；不删除
   或修改 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`，其他域名继续使用原代理。
4. 任务上下文结束或抛错时恢复原始环境变量；关闭开关时完全不触碰代理绕过列表。

## 4. 改动文件清单

- `src/web/frontend_settings.py`：新增设置字段、持久化响应和任务级代理绕过上下文。
- `frontend/src/api/client.ts`：补充前后端设置类型。
- `frontend/src/views/SettingsView.vue`：新增默认关闭的 Naive UI 开关及作用范围说明。
- `tests/test_frontend_settings.py`：覆盖旧设置兼容、开启/关闭行为、环境恢复和已有列表保留。
- `tests/test_api_server.py`：覆盖开关开启、关闭和 JSON 持久化往返。
- `README.md`：补充开关入口、默认行为和生效时机。

## 5. 验证结果

- 定向测试：`58 passed in 2.23s`。
- 全量测试：`.venv/bin/python -m pytest`，`265 passed in 4.72s`。
- 前端检查：`npm run build` 通过，包含 `vue-tsc --noEmit` 与 Vite 生产构建；只有项目既有的大包体积提示。
- 浏览器检查：设置页显示唯一“API 直连（绕过代理）”开关；初始状态关闭，可切换为开启并恢复关闭；
  页面无新增应用错误。验证过程没有点击“保存设置”，未改变本机真实配置。
- 静态检查：`py_compile` 和 `git diff --check` 通过。

## 6. 遗留事项

本地验证没有调用付费远端 API。部署到 WSL 后，用户需要在“运行设置”中开启并保存，然后新建或重跑
一组任务；诊断中的 `remote_ip` 应不再是本机代理地址。已经运行中的任务不会中途改变网络路由。
