# 阶段六 Codex CLI 显式配置设计

## 目标

让阶段六的 `codex_cli` 真正使用项目配置中的显式模型参数，避免不同机器落到各自本机 `~/.codex/config.toml` 默认值上。

## 范围

- 修改 `src/refine_utils.py` 的 `codex exec` 调用参数
- 修改默认配置与测试夹具中的 `llm.model`
- 为 `codex_cli` 配置透传补充测试

## 非目标

- 不修改阶段六提示词内容
- 不增加相似度阈值拒收逻辑
- 不调整多后端比较策略
- 不改动 `gemini_cli` 行为

## 方案

1. 将 `config/settings.yaml` 中 `llm.model` 设为显式默认值
2. 在 `run_codex_cli()` 中：
   - 若 `llm.model` 非空，则传入 `--model`
   - 若 `llm.reasoning_effort` 非空，则通过 `-c model_reasoning_effort=...` 传给 Codex CLI
3. 若 Codex CLI 返回结果里未显式带 `model_name`，则回填为配置中的 `llm.model`，避免继续写 `codex_default`

## 兼容性

- 若用户显式覆盖配置，阶段六会稳定使用项目配置值
- 若用户未来清空 `llm.model`，仍保留回退到本机默认 Codex 配置的能力
- 不影响 `gemini_cli` 和 fallback 路径

## 验证

- `.venv/bin/python -m pytest tests/test_refine.py -q`
- `.venv/bin/python -m pytest`
- 若环境允许，执行真实阶段六样例并检查 `backend_status.codex_cli` 中记录的模型名
