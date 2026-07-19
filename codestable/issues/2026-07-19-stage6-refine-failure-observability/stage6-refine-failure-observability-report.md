---
doc_type: issue-report
issue: 2026-07-19-stage6-refine-failure-observability
status: confirmed
severity: P1
summary: 阶段 6 失败时监控面板显示请求完成，但项目未保留原始响应和具体拒绝原因
tags: [refine, codex-lb, sse, diagnostics, observability]
---

# 阶段 6 校对失败不可观测 Issue Report

## 1. 问题现象

阶段 6 在单任务和批量任务中会间歇性失败。历史版本可能产出包含 `�`、`# source` 或缺少正常
Markdown 结构的程序回退稿；加入结果校验后，损坏结果会被拒绝，但失败任务不再生成 refined JSON。

与此同时，`api.redworker.org` 监控面板可能把对应请求显示为 `OK` 并记录大量输出 tokens。项目任务
状态只保留 `stage=refine exit_code=1`，无法从现有产物判断客户端是否完整收到 SSE、模型输出能否解析
为 JSON、锁定原文是否被修改，或者最终 Markdown 触发了哪项校验。

## 2. 复现步骤

1. 在局域网 Web 页面提交三个视频及对应参考 PDF 的批量读书会整理任务。
2. 使用 `codex_api`、`gpt-5.6-terra` 执行阶段 6。
3. 等待批量任务结束并查看任务状态与 `stt-zj` 请求面板。
4. 观察到：部分阶段 6 请求在面板中显示 `OK`，但对应任务失败且没有 refined JSON；失败原始输出
   与具体校验原因均不存在。

复现频率：间歇性，批量任务更明显。2026-07-19 批次 `7acb237de094` 中，三个视频有一个完成、
一个阶段 6 失败、一个在参考 OCR 阶段因上游传输中断进入待补页。

## 3. 期望 vs 实际

**期望行为**：每次阶段 6 调用均能与监控面板请求编号关联；失败后可以读取传输、SSE、模型正文、
JSON 解析与最终校验的完整证据，且诊断记录不得泄露 API Key。

**实际行为**：监控面板只证明服务端请求状态，项目仅记录概括性异常；失败响应和错误分层在进程内
丢失，服务重启后无法追溯。

## 4. 环境信息

- 涉及模块 / 功能：阶段 6 单次整篇校对、Codex Responses SSE 客户端、批量任务产物。
- 相关文件 / 函数：`src/codex_lb_client.py::read_http_response_with_curl`、
  `src/codex_lb_client.py::extract_event_stream_text`、
  `src/refine_utils.py::run_codex_api_payload`、
  `src/refine_utils.py::run_validated_single_pass_backend_refinement`。
- 运行环境：另一台电脑的 WSL2 mirrored networking；项目通过局域网访问；WSL 项目进程继承
  `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:10808`；Windows v2rayN TUN 同时开启。
- API：`https://api.redworker.org`，API Key 名称 `stt-zj`。
- 现场批次：`7acb237de094`；阶段 6 失败子任务 `8ba861b918d2`。

## 5. 严重程度

**P1** — 阶段 6 是核心交付环节，失败会阻断最终稿；现有自动重试会产生额外 API 成本，却不留下
足以区分网络、协议、模型和校验问题的证据。

## 备注

同一现场批次的 OCR 第 7 页另有明确 `upstream_unavailable / TransferEncodingError`，该问题已有
`2026-07-15-pdf-ocr-upstream-stream-interruption` 检查点与补页恢复机制。本 issue 只解决阶段 6
调用证据丢失，不改变 OCR 恢复语义。
