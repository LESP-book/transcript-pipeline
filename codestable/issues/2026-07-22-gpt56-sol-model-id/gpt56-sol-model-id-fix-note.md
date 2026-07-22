---
doc_type: issue-fix
issue: 2026-07-22-gpt56-sol-model-id
path: fast-track
fix_date: 2026-07-22
tags: [codex-lb, model-id, frontend-settings]
---

# GPT-5.6 Sol 模型 ID 修复记录

## 1. 问题描述

设置页和单阶段运行页将“GPT-5.6 Sol”提交为 `gpt-5.6`。
该 ID 不在当前 codex-lb 的模型列表中，阶段 6 请求因此返回
`invalid_request_error`。

## 2. 根因

`SettingsView.vue` 与 `StageRunnerView.vue` 的模型选项将 Sol 标签映射为
`gpt-5.6`，同时项目配置、Pydantic 默认值和命令示例也使用了同一无效 ID。
当前服务实际暴露的模型 ID 是 `gpt-5.6-sol`。

## 3. 修复方案

将 Sol 的选项值、阶段 6 默认值、测试配置与命令示例统一为
`gpt-5.6-sol`；保留已经正确的 Terra 与 Luna ID 不变。同步更新当前保存的
前端设置，保证下一次新建任务立即使用有效模型。

## 4. 改动文件清单

- `frontend/src/views/SettingsView.vue`
- `frontend/src/views/StageRunnerView.vue`
- `config/settings.yaml`
- `config/setting.yaml`
- `src/schemas.py`
- `tests/helpers.py`
- `tests/test_config.py`
- `README.md`
- `data/jobs/frontend-settings.json`（运行时设置，已被 Git 忽略）

## 5. 验证结果

- 查询当前 codex-lb 的 `/v1/models` 成功，确认存在
  `gpt-5.6-sol`、`gpt-5.6-terra` 与 `gpt-5.6-luna`；三者均支持 `high` 和
  `xhigh` 推理强度。
- `.venv/bin/python -m pytest`：265 项全部通过。
- `npm run build`：Vue 类型检查与 Vite 构建通过。
- 真实加载项目设置后，阶段 6 默认模型和已保存前端设置均为
  `gpt-5.6-sol`；本地页面显示“GPT-5.6 Sol（推荐：阶段 6 精修）”。

## 6. 遗留事项

未发送实际文稿请求，避免为验证产生额外模型调用费用。已生成的历史任务设置
保持为原始快照；新建任务会使用修复后的模型 ID。
