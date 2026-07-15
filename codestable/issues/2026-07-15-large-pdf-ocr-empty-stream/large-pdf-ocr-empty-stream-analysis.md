---
doc_type: issue-analysis
issue: 2026-07-15-large-pdf-ocr-empty-stream
status: confirmed
root_cause_type: data-format
related: [large-pdf-ocr-empty-stream-report.md]
tags: [pdf, ocr, codex-api, event-stream, concurrency, memory]
---

# 大型 PDF OCR 空响应根因分析

## 1. 问题定位

| 关键位置 | 说明 |
|---|---|
| `src/codex_lb_client.py:319-332` | 流解析只收集 `response.output_text.delta`，并错误地只从 `response.completed.response.output_text` 读取最终文本；同时无法区分“明确返回空字符串的 output_text”与“响应结构中不存在 output_text”。 |
| `src/codex_lb_client.py:280-301` | 非流式解析已经能够读取原始 Response 的 `output[].content[].text`，但流式完成事件没有复用这套提取逻辑。 |
| `src/reference_utils.py:507-554` | 在发起第一页请求前先渲染整本 PDF，并把所有 PNG 转为 base64 字符串保存在列表中；内存占用随页数线性增长。 |
| `src/reference_utils.py:612-617` | `run_codex_api_pdf_ocr()` 将全部页面 data URL 再包装成任务列表，直到整本 OCR 结束才释放。 |
| `src/ocr_scheduler.py:55-57,85` | `max_concurrency=0` 会把线程池上限设为总页数，且不限制活动请求数。603 页输入理论上可创建 603 个线程和数百个活动流。 |
| `config/settings.yaml:108-110` | 当前实际配置把 OCR 最大并发设为 `0`，每 5 秒持续投递；当单页响应耗时数分钟时，活动请求会持续累积。 |

官方 Responses API 文档明确给出了 `response.output_text.done`、
`response.content_part.done`、`response.output_item.done` 的最终文本字段；原始 Response 的
`output_text` 是 SDK 聚合便利字段，HTTP 原始对象的文本位于 `output` 内容数组。

样例证据：失败 PDF 共 603 页、113,506,056 字节；仅第一页渲染 PNG 就有
1,170,447 字节，转为 base64 后还会进一步膨胀。任务从 18:31:05 运行到 18:37:05，
说明第 2 页请求未快速完成，而默认调度器在这段时间仍可继续投递后续页面。

修复期间对同一 PDF 第 2 页进行了原始流诊断：该页实际是一张空白扫描页；上游正常返回
`response.completed(status=completed)`，并明确包含 `output_text` 内容部件，但
`response.output_text.done.text` 与最终 `message.content[].text` 都是空字符串。因此截图中的
直接错误不是“已有正文但漏解析”，而是客户端把合法空白页误判为响应结构缺失。

## 2. 失败路径还原

**正常路径**：页面上传 PDF → `run_codex_api_pdf_ocr()` 渲染页面 → 调度单页请求 →
上游发送 `response.output_text.delta` → 解析器拼接 delta → 所有页完成后按页码合并 TXT。

**失败路径**：603 页 PDF → 一次性渲染并保留全部页面 data URL → 调度器每 5 秒继续投递且
不限制活动请求 → 第 2 页为空白扫描页，上游正常完成并明确返回空 `output_text` →
解析器既没有完整读取完成事件，也把明确的空文本当成字段缺失 → 抛出
“流中未找到 output_text” → 整本任务失败且不写 TXT。

**直接分叉点**：`src/codex_lb_client.py:327-332` — 上游已用 `completed + output_text=""`
表达“该页无正文”，代码却将其等同于“流中不存在 output_text”。

**规模放大点**：`src/ocr_scheduler.py:55-57,85` 与
`src/reference_utils.py:507-554` — 大 PDF 会同时放大活动流数量和常驻图片内存。

## 3. 根因

**根因类型**：数据格式为主，并发与资源管理为次。

**根因描述**：当前 SSE 解析器只覆盖了“持续收到非空文本 delta”的一种返回形式，没有覆盖
Responses API 官方定义的最终文本事件和原始完成对象结构，也没有把“明确存在但为空的
output_text”视为有效的空白页结果。因此遇到扫描书籍中的空白页就会整本失败。大型 PDF 又使用默认无限活动请求，
并在开始前把整本页面图片全部常驻内存；页数越多，请求形态差异、上游流容量压力和本机资源
压力被触发的概率越高。

**是否有多个根因**：是。

1. **主因**：流式响应解析不兼容官方完成事件，且无法接受明确的空 output_text，导致空白页被误判失败。
2. **次因**：默认无限 OCR 并发，大文档会无界累积活动请求。
3. **次因**：整本渲染并一次性 base64 化，大文档会无界增长内存占用。

## 4. 影响面

- **影响范围**：所有使用 `CodexLBClient.responses_stream_text()` 的流式 Responses 调用都可能被完成事件格式击中；包含空白页的扫描 PDF 会稳定触发本次误判，大型 PDF 还更容易暴露并发和内存问题。
- **潜在受害模块**：独立 PDF OCR、阶段 3 参考 PDF OCR、阶段 6 Codex API 精修的流式解析。
- **数据完整性风险**：当前实现遇到任一页误判为空会拒绝写整本 TXT，不会静默写缺页文本；因此没有部分结果冒充成功，但会浪费此前已完成页面的 API 成本与时间。
- **严重程度复核**：维持 P1。核心大型书籍场景不可用，但较小 PDF 和其他 OCR 后端仍可绕过。

## 5. 修复方案

### 方案 A：只补齐 Responses 流完成事件解析

- **做什么**：让流解析器复用现有 Response 文本提取逻辑，支持 `output_text.done`、`content_part.done`、`output_item.done` 和 `response.completed` 的嵌套输出，并仅在响应明确包含 output_text 部件时接受空字符串作为空白页结果。
- **优点**：改动小，直接修复截图中的误判错误；阶段 6 同时受益。
- **缺点 / 风险**：603 页仍会一次性占用大量图片内存，并可能创建数百个活动请求；只能解决当前报错，不能保证大型书籍稳定完成。
- **影响面**：`src/codex_lb_client.py` 与对应测试。

### 方案 B：补齐解析 + 有界并发 + 按需渲染（推荐）

- **做什么**：在方案 A 基础上，将 OCR 活动请求改为显式可配置的正整数上限；按单页或小窗口渲染、编码并提交，完成后立即释放该页图片，不再保存整本 data URL。
- **优点**：同时解决截图中的直接错误、603 页无限活动流和整本图片常驻内存三个问题；仍保持逐页请求和按页码合并语义。
- **缺点 / 风险**：涉及调度器、PDF 渲染接口、配置、测试和文档，改动范围比方案 A 大；并发上限需要明确写入配置，处理速度会比无限投递更可控但可能更慢。
- **影响面**：`src/codex_lb_client.py`、`src/reference_utils.py`、`src/ocr_scheduler.py`、配置、测试和 README。

### 方案 C：方案 B + 逐页结果检查点与失败续跑

- **做什么**：在方案 B 基础上，每页成功后立即持久化独立页结果；任务失败或服务重启后只补未完成页，最终再合并整本 TXT。
- **优点**：最适合数百页书籍，单页失败不会浪费此前已完成页面的时间和 API 成本。
- **缺点 / 风险**：新增任务恢复协议、页级状态和清理规则，属于新的持久化能力，明显扩大本次 bug 修复范围。
- **影响面**：除方案 B 文件外，还会修改 Web 任务状态结构和输出目录约定。

### 推荐方案

**推荐方案 B**。方案 A 只能修掉眼前的解析误判，无法保证 603 页书籍不会继续因无限并发或
内存压力失败；方案 C 更稳但已经跨入新功能。方案 B 在不改变最终 TXT 与任务 API 主结构的前提下，
覆盖本次大型 PDF 的三个已证实薄弱点。

用户于 2026-07-15 明确确认：按照方案 B 修复。

用户随后补充既有调度约束：每 10 秒投递一张图片，理论活动请求量保持在 15～20 个可承受范围内；
实现采用 10 秒投递间隔与 20 个同时在途请求上限。
