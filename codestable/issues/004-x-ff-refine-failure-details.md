---
kind: issue
title: "阶段 6 根因摘要与待复核候选稿"
type: ff
status: closed
created: 2026-09-29
---

# 阶段 6 根因摘要与待复核候选稿

- 做了什么：在现有 validation/diagnostics JSON 中新增 failure_category、failure_summary、requested_model 和错误证据文件名；最终异常及重试日志显示具体原因。保留原字段与失败判定。
- 候选稿：仅对非程序回退的内容校验失败结果，在 attempt 诊断目录保存 candidate-review.md，标记 needs_review_not_accepted；记录损坏字符总数及最多 10 处位置和上下文，不覆盖 refined/final。
- 改动：src/request_trace.py、src/refine_utils.py、tests/test_refine.py、tests/test_refine_diagnostics.py。
- 验证：.venv/bin/python -m pytest（292 passed）。使用任务 95953038031e 的真实 ASR 和两次 SSE，在本机 HTTP 回放服务上运行 scripts/06_refine.py；分别显示 model_output_json 与 content_validation，后者保存候选稿并报告 2 个损坏字符。输出 /tmp/refine-diagnostic-replay-mtsj6upt；两次 exit=1 是预期拒绝。初次回放配置误启用参考文件导致入口拒绝，改用无参考模式后验证完成。
- codestable：无现有 spec 需要同步。不改变重试次数、校验标准、网络协议；不新增 Web 候选稿下载入口，不自动修复乱码，不声称解决上游疑似串流。历史诊断不自动回填；新字段在新运行时生成。
