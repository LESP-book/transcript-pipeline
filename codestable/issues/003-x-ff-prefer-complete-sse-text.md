---
kind: issue
title: "优先使用 SSE 完成事件全文"
type: ff
status: closed
created: 2026-09-29
---

# 优先使用 SSE 完成事件全文

修复阶段 6 已收到完整完成事件，却因增量流缺少前缀而误判 JSON 失败的问题。

- 改动：`src/codex_lb_client.py` 优先取非空完成事件正文，缺失时保留增量文本回退；`tests/test_refine.py` 覆盖缺头增量流。
- 验证：`.venv/bin/python -m pytest`（287 passed）；离线重放真实失败 SSE，解析得到完整 JSON，Markdown 校验原因为空。
- codestable：无现有 spec 需要同步；未改变重试、传输失败或上游产物结构。
