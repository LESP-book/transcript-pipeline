---
doc_type: issue-report
issue: 2026-07-15-large-pdf-ocr-empty-stream
status: confirmed
severity: P1
summary: 603 页 PDF 书籍 OCR 在第 2 页收到无 output_text 的响应后整本失败
tags: [pdf, ocr, codex-api, large-document, event-stream]
---

# 大型 PDF OCR 空响应 Issue Report

## 1. 问题现象

在独立 `PDF OCR` Web 页面处理一本页数较多的扫描 PDF 时，任务运行约 6 分钟后失败。
页面显示总计 1、成功 0、失败 1，逐本错误为：

`Codex API OCR 第 2 页失败: 中国古代史（上册） 1975 南京大学历史系中国古代史教研组.pdf | Codex Responses API 流中未找到 output_text。`

同一页面的历史记录中，较小的《欧洲哲学史》PDF 曾成功完成。

## 2. 复现步骤

1. 打开本地 Web 页面 `/pdf-book-ocr`。
2. 选择“单本 PDF”，上传《中国古代史（上册） 1975 南京大学历史系中国古代史教研组.pdf》。
3. OCR 推理强度选择“高”，OCR 模型填写 `gpt-5.4-mini`。
4. 点击“开始识别”。
5. 等待任务结束。
6. 观察到：任务在第 2 页报告 Responses 流中没有 `output_text`，整本 PDF 未生成 TXT。

复现频率：当前大型样例确认出现 1 次；小型 PDF 已有成功记录。

## 3. 期望 vs 实际

**期望行为**：大型 PDF 也应逐页完成 OCR，按页码合并，并在全部页成功后提供整本 TXT 下载。

**实际行为**：任务运行约 6 分钟后因第 2 页响应中未解析到 `output_text` 而失败，成功页数为 0，未生成整本 TXT。

## 4. 环境信息

- 涉及模块 / 功能：独立 PDF 书籍 OCR、Codex Responses 流解析、逐页 OCR 调度
- 相关文件 / 函数：`src/reference_utils.py::run_codex_api_pdf_ocr`、`src/ocr_scheduler.py::run_staggered_page_ocr_tasks`、`src/codex_lb_client.py::extract_event_stream_text`
- 运行环境：本地 Web，任务 ID `pdf-ocr-b3769c0a0cf7443091aa52b75ada0298`
- PDF 元数据：603 页、113,506,056 字节、未加密
- 任务时间：2026-07-15 18:31:05 至 18:37:05（Asia/Shanghai）

## 5. 严重程度

**P1** — 独立 OCR 工具的核心用途是处理 PDF 书籍；大型书籍稳定性不足会使核心场景不可用，但较小 PDF 仍可处理。

## 备注

用户提供了 Web 失败截图；任务状态文件保留了具体失败页与错误文本。
修复调试时确认第 2 页是空白扫描页，上游对该页正常完成并明确返回空字符串 `output_text`。
