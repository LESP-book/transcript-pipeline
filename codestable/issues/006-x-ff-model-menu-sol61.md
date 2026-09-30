---
kind: issue
title: "隐藏其他 ASR 候选并切换 GPT-6.1 Sol"
type: ff
status: closed
created: 2026-10-01
---

# 隐藏其他 ASR 候选并切换 GPT-6.1 Sol

按用户要求，Web ASR 选择器只展示 Whisper、Qwen 1.7B、Qwen 0.6B；Paraformer 和 Nano 仅隐藏，保留 CLI、显式 API 请求和任务快照兼容。读取隐藏的 Web 保存默认时不再使用该默认；页面采用可见配置默认，配置候选也隐藏时展示 Whisper。不删除 SDK、模型缓存或历史任务。

GPT-6 Sol 的页面选项、配置/schema 默认、CLI 示例和文档改为 `gpt-6.1-sol`（GPT-6.1 Sol），Luna 保持 `gpt-6-luna`。旧 Web 保存的 `gpt-6-sol` 在读取时映射到新 ID（精修/OCR 字段均支持），不改写磁盘设置或历史快照。

- 改动：`src/asr/registry.py`、`src/web/frontend_settings.py`、`src/schemas.py`、两个 `config/` YAML、设置/单阶段 Vue 页面、四个 CLI 帮助、`README.md`、`docs/ASR_BACKENDS.md` 与相关测试。仅选项内容变化，无布局重构。
- 验证：`.venv/bin/python -m pytest` **350 passed / 6.77 秒**；前端类型检查/Vite build 和 `git diff --check` 通过。实际项目配置及本地 ASGI API 检查确认三项 ASR、有效 Qwen 1.7B 默认、`gpt-6.1-sol` 精修默认与不变的 Luna 默认；证据 `data/output/logs/model-menu-20261001/api-check.json`。真实 CLI `06_refine.py --help` 显示新 ID。首次新增测试误用 helper 参数，已修正后全量通过。
- 边界：未发起收费模型推理，不宣称上游已验证该模型 ID；未重跑录音/旧任务、未重启用户服务、未部署镜像或 commit/push。按 REVIEW_CHECKLIST 自评为批准范围内、主结构兼容、没有上游产物修改。
- codestable：无现行 Project Spec 可同步；历史 `001` 保留当时 GPT-6 切换证据，本记录说明当前覆盖关系；`005` 多后端实现 issue 保持 open，不因界面暂时隐藏而关闭。
