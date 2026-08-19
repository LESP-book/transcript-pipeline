---
doc_type: issue-fix
issue: 2026-08-19-remote-http-artifact-copy
path: fast-track
status: verified-local
fix_date: 2026-08-19
tags: [frontend, clipboard, http, remote-deployment, task-artifacts]
---

# 远端 HTTP 任务产物复制修复记录

## 1. 问题与根因

任务列表中“阶段文字产物”的“复制内容”按钮直接调用
`navigator.clipboard.writeText()`。该 Clipboard API 只在安全上下文中可用；本机
`localhost` 被浏览器视作可信来源，而经普通 HTTP 访问的远端主机/IP 不是安全上下文，
因此 API 不存在或调用被拒绝。原实现也没有捕获异常，用户看不到明确失败提示。

## 2. 实际修复

- `frontend/src/components/JobArtifactsViewer.vue`：安全上下文中优先使用现代 Clipboard
  API；HTTP 页面或 API 被权限策略拒绝时，改用隐藏 `textarea` 加
  `document.execCommand("copy")` 的兼容路径。
- 复制完全失败时显示可操作的权限提示，不再留下未处理的 Promise rejection。

没有修改任务状态、产物 JSON、后端接口或已有任务数据。

## 3. 验证结果

- `.venv/bin/python -m pytest`：`278 passed in 5.15s`。
- `npm --prefix frontend run build`：Vue 类型检查和 Vite 构建通过。
- 浏览器真实页面验证：以 `http://192.168.0.135:5173/jobs` 访问任务列表，确认
  `window.isSecureContext === false` 且 `navigator.clipboard` 不可用；展开一个真实任务的
  文字产物后点击“复制内容”，验证该组件进入 `execCommand("copy")` 兼容分支并显示
  “已复制当前产物内容”。测试仅临时创建本地忽略的任务状态文件，结束后已删除。

## 4. 影响与边界

HTTPS/localhost 继续优先走 `navigator.clipboard.writeText()`；仅在其不可用或被拒绝时
才走兼容路径。旧版浏览器若同时禁止 `execCommand`，页面会明确提示用户检查剪贴板权限。
本次未增加 HTTPS 部署、未改动任何流水线处理阶段，也未改变下载功能。
