---
doc_type: issue-analysis
issue: 2026-07-20-stage6-overstrict-delivery-validation
status: confirmed
root_cause_type: overstrict-output-contract
related: [stage6-overstrict-delivery-validation-report.md]
tags: [refine, validation, markdown, retry, codex-api]
---

# 阶段 6 交付校验过严根因分析

## 1. 白盒结论

阶段 6 在进入最终交付校验前已经完成两层结构验证：

1. `extract_json_payload` 要求模型正文能解析为 JSON，且顶层必须是对象。
2. `parse_backend_document_result` 要求 `final_markdown` 非空，否则抛出明确错误。

因此，`validate_final_markdown_contract` 中的“必须有一级标题”和“标题后必须以空行分隔正文”并不承担
JSON 完整性校验，只是在强制一种排版偏好。现场成功响应被这两项拒绝后，又进入了一次本来不需要的
远端请求；第二次请求的上游 WebSocket 中断只是最终失败的直接触发点，不是第一次合法结果被丢弃的
原因。

## 2. 方案判断

用户于 2026-07-20 确认采用对话中的方案 C：缩小最终交付契约，只保留能够确定识别已知坏结果的
检查。

保留：

1. `refinement_strategy == programmatic_markdown_fallback`：这是程序回退的结构化事实，不依赖文案。
2. `final_markdown` 含 Unicode 替换字符 `�`：这是现场出现过的明确文本损坏信号。
3. 首个非空行是明确的 `# source`：这是已知内部占位标题。

移除：

1. `missing_h1_title`。
2. `missing_separated_markdown_body`。

不采用“只搜索 source 判断 fallback”，因为正常正文可能合法包含英文 `source`，而不含该词的程序回退
仍会漏检。程序回退应读取已经存在的结构化 `refinement_strategy`；`# source` 仅作为独立的占位标题
信号。

## 3. 兼容性与风险

- 不改变函数签名、返回类型、refined JSON 主结构或诊断汇总结构。
- 历史诊断中的 `missing_h1_title` / `missing_separated_markdown_body` 仍可照常读取，只是不再产生新记录。
- 已有 `refinement_validation_retry_count` 保持不变；只有确定性坏结果才会消耗这次重试。
- 非空但排版较弱的 Markdown 可能被接受，这是方案 C 的明确取舍；格式质量交给 Prompt 和人工校对，
  不再用脆弱的排版规则把完整正文误判为失败。
- 本次不添加新的长度、超时、截断、重试或静默回退逻辑。

## 4. 传输边界

项目客户端向 redworker 发送的是 HTTP POST，并以 `Accept: text/event-stream` 接收 SSE；监控面板中的
`HTTP / Up WS` 表明（结合现场失败事件推断）redworker 对项目一侧使用 HTTP，而其内部上游使用
WebSocket。本修复不改变任一传输层。
