---
doc_type: issue-report
issue: 2026-07-11-pdf-ocr-pagewise-requests
status: confirmed
severity: P1
summary: 多页扫描 PDF 使用 codex_api OCR 时稳定触发上下文超限
tags: [pdf, ocr, codex-api, context-length]
---

# 多页 PDF OCR 上下文超限 Issue Report

## 1. 问题现象

通过 Web 设置页选择 `codex_api` 后端处理多页扫描 PDF 时，codex-lb
立即返回 `context_length_exceeded`。页面显示的完整错误为：
`Your input exceeds the context window of this model. Please adjust your input and try again.`

## 2. 复现步骤

1. 在 Web 设置页配置 codex-lb，选择 `codex_api` 作为 PDF OCR 后端。
2. 选择模型 `gpt-5.4-mini`。
3. 提交一份多页扫描 PDF 进行 OCR。
4. 观察到：请求立即失败，codex-lb 返回 `context_length_exceeded`，未生成 OCR 结果。

复现频率：稳定复现。

## 3. 期望 vs 实际

**期望行为**：每页图片独立完成 OCR，确认全部页面均成功后，按页码顺序合并为一份连续文本；跨页未结束的段落不应被插入换行。

**实际行为**：多页扫描 PDF 的 OCR 请求立即失败，服务端拒绝请求并返回上下文超限错误，未生成 OCR 结果。

## 4. 环境信息

- 涉及模块 / 功能：Web PDF OCR、`codex_api` 后端与 codex-lb 转发
- 相关文件 / 函数：待定
- 运行环境：本地 Web 设置页（`http://127.0.0.1:5173/settings`）
- 其他上下文：报错模型为 `gpt-5.4-mini`；codex-lb 页面记录的错误码为 `context_length_exceeded`

## 5. 严重程度

**P1** — 多页扫描 PDF 无法使用核心 OCR 流程，但单页或可直接提取文字层的 PDF 可绕过。

## 备注

用户提供两张 codex-lb 截图：一张请求详情截图和一张错误列表截图，均显示
`context_length_exceeded`。
