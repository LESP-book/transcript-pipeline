---
kind: issue
title: "切换 GPT-6 模型选项与默认值"
type: ff
status: closed
created: 2026-09-24
---

# 切换 GPT-6 模型选项与默认值

设置页与单阶段页只提供 GPT-6 Sol / Luna；阶段 6 默认 Sol，PDF OCR 默认 Luna。旧版前端保存的 GPT-5.4/5.5/5.6 默认值在读取时回退到新默认，不覆盖磁盘上的用户设置或历史任务。

- 改动：`frontend/src/views/`、`config/`、`src/schemas.py`、`src/web/frontend_settings.py`、`scripts/`、`README.md` 与相关测试。
- 验证：`.venv/bin/python -m pytest` 280 通过；`npm --prefix frontend run build` 成功；实际加载项目配置与前端设置显示两个 GPT-6 ID；本地 codex-lb 未运行，未进行收费模型请求或 PDF OCR 端到端验证。
- codestable：无现行 spec 可同步；历史修复记录保留原模型 ID，不改写历史证据。
