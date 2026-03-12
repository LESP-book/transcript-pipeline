# 阶段六默认后端切换为 codex_cli 设计

## 目标

将阶段六 LLM 精修的默认工具配置统一收敛为仅使用 `codex_cli`。

## 范围

- 修改代码级默认值
- 修改默认配置文件
- 修改依赖默认值的测试夹具与断言

## 非目标

- 不删除 `gemini_cli` 相关实现
- 不改变显式配置下可同时启用多个后端的能力
- 不调整阶段六输出 JSON 主结构
- 不推进阶段六之外的功能

## 方案

采用最小一致性修改：

1. 将 `src/schemas.py` 中 `LLMSettings.backends` 的默认值改为 `["codex_cli"]`
2. 将 `config/settings.yaml` 中 `llm.backends` 默认值改为仅包含 `codex_cli`
3. 将 `tests/helpers.py` 中最小配置默认值改为仅包含 `codex_cli`
4. 调整依赖默认行为的测试断言，确保默认路径只记录 `codex_cli`

## 兼容性

- 显式在配置中写入 `gemini_cli` 时，现有逻辑仍可运行
- 阶段六输出结构保持不变，仅默认 `refinement_backends` 集合变化

## 验证

- 使用 `.venv/bin/python -m pytest`
- 运行 `.venv/bin/python scripts/06_refine.py`
- 检查 `data/intermediate/refined/` 输出中的 `refinement_backends` 与 `backend_status`
