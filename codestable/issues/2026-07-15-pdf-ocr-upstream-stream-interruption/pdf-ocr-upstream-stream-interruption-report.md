---
doc_type: issue-report
issue: 2026-07-15-pdf-ocr-upstream-stream-interruption
status: confirmed
severity: P1
summary: 603 页 PDF OCR 在第 195 页因远程响应流中断而整本失败
tags: [pdf, ocr, codex-lb, upstream, transport]
---

# PDF OCR 上游响应流中断 Issue Report

## 1. 问题现象

在独立 PDF OCR Web 页面重新处理 603 页《中国古代史（上册）》时，任务运行约 36 分钟后失败。
逐本错误显示第 195 页收到 `response.failed`，错误码为 `upstream_unavailable`，错误消息包含：

`TransferEncodingError: Not enough data to satisfy transfer length header.`

任务最终显示总计 1、成功 0、失败 1，没有生成整本 TXT。

## 2. 复现步骤

1. 打开本地 Web 页面 `/pdf-book-ocr`。
2. 上传 603 页《中国古代史（上册）》PDF。
3. 使用 `gpt-5.4-mini`、高推理强度开始识别。
4. 等待任务运行。
5. 观察到：任务在第 195 页收到上游失败事件并结束，整本结果不可下载。

复现频率：本次长任务确认出现 1 次；对第 195 页单独诊断时又出现一次
`curl: (92) HTTP/2 stream was not closed cleanly: INTERNAL_ERROR`。codex-lb 重启后，同一页
通过 HTTP/1.1 和程序默认 HTTP/2 路径均成功返回 661 字。

## 3. 期望 vs 实际

**期望行为**：单页遇到临时上游传输故障时，不应让已经运行三十多分钟的整本 OCR 进度全部作废；
服务恢复后应能继续完成剩余页面。

**实际行为**：任一页出现一次传输层失败，调度器就停止后续投递；所有已完成页面仅保存在内存中，
最终不写 TXT，也不能从失败页恢复。

## 4. 环境信息

- 涉及模块 / 功能：独立 PDF 书籍 OCR、Codex Responses 流请求、页任务调度。
- 相关文件 / 函数：`src/codex_lb_client.py::read_http_response_with_curl`、
  `src/ocr_scheduler.py::run_staggered_page_ocr_tasks`、
  `src/reference_utils.py::run_codex_api_pdf_ocr`。
- 运行环境：本地 Web + 远程 `api.redworker.org/v1/responses`。
- 任务 ID：`pdf-ocr-aac9416dabf644fc9d00088a27d8b16b`。
- 任务时间：2026-07-15 19:54:12 至 20:30:06（Asia/Shanghai）。
- 调度配置：每 10 秒投递一页，最多 20 个同时在途请求。

## 5. 严重程度

**P1** — 单页的临时远程传输故障会令数百页长任务整体失败并丢失本轮全部内存进度；重启
codex-lb 后可以重新运行，但代价是重复时间和 API 调用。

## 备注

第 195 页可以正常渲染，data URL 长度约 1,049,930 字符。codex-lb 重启后，同一页使用相同模型、
相同推理强度和相同图片成功返回 661 字，说明页面文件和 OCR 内容本身可处理。
