---
doc_type: issue-report
issue: 2026-07-20-stage6-overstrict-delivery-validation
status: confirmed
related: [../2026-07-19-stage6-refine-failure-observability/stage6-refine-failure-observability-fix-note.md]
tags: [refine, validation, markdown, retry, codex-api]
---

# 阶段 6 交付校验过严问题报告

## 1. 现场现象

阶段 6 的一次真实请求已经得到 `HTTP 200` 和 `response.completed`，模型返回的 JSON 可解析，
`final_markdown` 非空且正文内容完整，但首个非空行是普通正文而不是一级标题。该结果只因
`missing_h1_title` 被拒绝，随后触发的第二次付费请求又遇到 redworker 上游 WebSocket
`stream_incomplete`，最终整个任务失败。

## 2. 复现条件

1. 阶段 6 后端返回合法 JSON 对象和非空 `final_markdown`。
2. `final_markdown` 不以 `# 标题` 开头，或者标题与正文之间没有空行。
3. 原实现把排版形式视为失败，并按已有配置自动重跑。

## 3. 期望行为

- JSON 无效或 `final_markdown` 为空时仍明确失败。
- 程序回退稿、Unicode 替换字符 `�` 和明确的 `# source` 占位标题仍应拒绝。
- 不应仅因缺少一级标题或固定空行样式，丢弃已经可交付的正文并制造一次不必要的远端重跑。

## 4. 范围

本问题只调整阶段 6 的最终交付校验，不修改模型、业务 Prompt 主体、网络传输、超时、重试次数、
中间 JSON 主结构或后续导出阶段。
