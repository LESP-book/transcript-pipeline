---
doc_type: issue-analysis
issue: 2026-07-19-stage6-refine-failure-observability
status: confirmed
root_cause_type: missing-observability
related: [stage6-refine-failure-observability-report.md]
tags: [refine, codex-lb, sse, diagnostics, artifacts]
---

# 阶段 6 校对失败不可观测根因分析

## 1. 问题定位

| 关键位置 | 当前行为 | 丢失的证据 |
|---|---|---|
| `src/codex_lb_client.py::read_http_response_with_curl` | curl 完整结束后只返回正文；非零退出直接抛异常 | curl 退出码、stderr、HTTP 状态、远端 IP、耗时和已接收的部分正文 |
| `src/codex_lb_client.py::extract_event_stream_text` | 从完整字符串抽取文本；失败事件转为异常 | 原始 SSE、最后事件、`response_id`、是否看到 `response.completed` |
| `src/refine_utils.py::run_codex_api_payload` | 直接把模型正文提取为 JSON | 原始模型正文与 JSON 解析错误 |
| `src/refine_utils.py::run_single_pass_backend_refinement` | 捕获 `CLIBackendError` 后返回程序回退稿 | 触发回退的真实异常；锁定引用变化与后端失败无法区分 |
| `src/refine_utils.py::run_validated_single_pass_backend_refinement` | 只把成功重试的校验原因写入最终 refined JSON | 最终失败时没有 refined JSON，因此所有校验原因一起丢失 |

## 2. 白盒失败路径

1. 阶段 6 构造整篇 Prompt，并调用远端 Codex Responses SSE。
2. curl 通过当前进程代理环境连接远端；响应在内存中累积，进程结束后才进入 SSE 解析。
3. 任一传输、SSE 或 JSON 错误被逐层包装成 `CLIBackendError`。
4. 单次校对函数捕获该异常，生成 `programmatic_markdown_fallback`，但不保留异常对象。
5. 交付校验拒绝程序回退稿并执行配置中已有的一次重试。
6. 若重试仍失败，任务只保留概括性退出码；若重试成功，最终 JSON 只能说明曾经失败，不能说明为何失败。

真正的矛盾不是“异常没有被捕获”，而是异常已经被捕获后只改变控制流，没有形成可持久化、可关联的
证据。监控面板的服务端状态与项目客户端状态属于两个观测点，当前没有 `response_id` 把两者连接起来。

## 3. 方案比较

### 方案 A：只扩充控制台日志

- 优点：改动最小。
- 缺点：当前日志只写终端，服务重启或终端关闭后即丢失；大段原始 SSE 不适合控制台；无法作为任务
  产物读取。
- 结论：不采用。

### 方案 B：每次调用落完整证据包，并生成稳定汇总产物（采用）

- 在 `paths.logs_dir/refine/` 下按文件、后端、运行批次和尝试次数建立独立目录。
- 保存脱敏请求元数据、传输记录、完整原始 SSE、SSE 事件摘要、提取正文、解析结果、后端错误和校验结果。
- 汇总文件 `paths.logs_dir/refine/diagnostics.json` 只保存索引、原因和请求编号，并通过现有任务产物 API
  暴露；完整 SSE 仍留在任务目录，不扩大 Web 下载面。
- 不保存 Authorization 或 API Key；Prompt 只保存字符数、UTF-8 字节数和 SHA-256，不重复保存正文。
- 优点：能区分客户端断流、上游失败事件、JSON 解析、锁定引用与 Markdown 校验；失败后仍可读取。
- 代价：完整 SSE 会增加磁盘占用。本次不添加无依据的截断、自动清理或保留天数。

### 方案 C：把所有调用写入数据库并新增完整诊断 UI

- 优点：集中查询体验最好。
- 缺点：需要新表、迁移、访问控制和前端页面，明显超出本轮定位阶段 6 故障的最小范围。
- 结论：暂不采用；方案 B 的汇总 JSON 已为以后 UI 提供稳定输入。

## 4. 采用方案与边界

用户于 2026-07-19 明确要求先实现一个版本再进行真实测试，采用方案 B。

本轮不会修改：模型、Prompt 业务内容、超时、重试次数、并发数、输出校验规则、程序回退规则或
`NO_PROXY`。诊断写盘是旁路：若磁盘权限或空间导致诊断文件无法写入，必须输出明确 warning，但不能
把原本合法的模型响应改判为失败。

## 5. 验收标准

1. 传输失败时仍保留部分响应、curl 退出码、stderr 和网络指标。
2. 服务端返回 `OK` 但模型正文无效时，保留完整 SSE、提取正文和 JSON 解析错误。
3. 锁定引用或 Markdown 校验失败时，汇总文件记录精确原因和尝试编号。
4. 成功重试时可以看到“第一次拒绝、第二次接受”的两条记录。
5. 诊断文件不出现测试 API Key 或 Authorization 值。
6. 原有 refined JSON 和最终 Markdown 主结构保持兼容。
