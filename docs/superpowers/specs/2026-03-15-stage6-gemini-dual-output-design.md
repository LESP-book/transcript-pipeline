# 阶段六 Gemini 选项与双模型并行输出设计

## 目标

在阶段六保留现有单篇精修主流程的前提下，新增 Gemini 单跑能力、Codex/Gemini 双跑能力，以及双结果并行落盘能力，降低长期仅依赖 Codex 的额度消耗。

## 范围

- 为阶段六增加命令行级后端选择开关
- 将 Gemini 主模型切换为 `gemini-3.1-pro-preview`
- 支持单跑 `codex_cli`
- 支持单跑 `gemini_cli`
- 支持同时运行 `codex_cli` 与 `gemini_cli`
- 在双跑模式下同时输出主索引 JSON 与两个后端独立 JSON
- 在提示词中增加“结果会被其他模型审核”的质量约束
- 保持现有 `data/intermediate/refined/` 主目录结构不变

## 非目标

- 不实现真实的 Claude / Gemini / Codex 自动审核流程
- 不引入新的外部服务 SDK
- 不改变阶段六安全替换主逻辑
- 不改成自动选择单一最佳结果
- 不新增新的最终稿拼装阶段

## 设计决策

### 1. 后端选择

阶段六新增 `--backend` 参数，支持：

- `codex_cli`
- `gemini_cli`
- `both`

命令行参数优先级高于配置文件。未传入时，仍从 `llm.backends` 读取默认后端列表。

### 2. Gemini 模型顺序

- `gemini_model` 默认改为 `gemini-3.1-pro-preview`
- `gemini_fallback_model` 默认改为 `gemini-3-flash-preview`

含义是先尽量拿更强模型输出，容量或调用失败时再降级。

### 3. 主 refined JSON

主文件路径保持为：

- `data/intermediate/refined/<basename>.json`

单模型模式下继续保留兼容字段：

- `final_markdown`
- `selected_backend`

双模型模式下：

- `final_markdown` 置空
- `selected_backend` 置空
- `comparison_summary` 写 `manual_selection_required`
- 新增 `model_results`，同时保存 `codex_cli` / `gemini_cli` 的完整结果

### 4. 独立后端产物

双模型模式额外输出：

- `data/intermediate/refined/<basename>.codex_cli.json`
- `data/intermediate/refined/<basename>.gemini_cli.json`

这两个文件仅作为人工对照和单独查看入口，不作为阶段七默认主输入。

### 5. 阶段七兼容

阶段七保持只消费主 refined JSON。

当主 refined JSON 中：

- `final_markdown` 非空：按现有逻辑导出
- `final_markdown` 为空且存在 `model_results`：显式报错，提示用户当前为双模型结果，需先指定导出模型或重新以单模型模式运行

这样可以避免阶段七默默导出空 Markdown。

### 6. 提示词约束

在阶段六整篇提示词拼装时追加后端差异化约束：

- Codex 提示词中写明：结果会交给 Gemini 和 Claude 审核
- Gemini 提示词中写明：结果会交给 Codex 和 Claude 审核

该约束只作为提示词文本增强，不引入实际审核执行链路。

## 兼容性

- `data/intermediate/refined/*.json` 主入口不变
- 单模型模式继续保留 `final_markdown`
- 双模型模式通过新增字段扩展，不回改上游产物结构
- 阶段七仅增加显式错误提示，不新增自动选模逻辑

## 验证

- `.venv/bin/python -m pytest`
- 定向验证 `tests/test_refine.py`
- 定向验证 `tests/test_export_markdown.py`
- 真实运行 `.venv/bin/python scripts/06_refine.py --backend gemini_cli`
- 真实运行 `.venv/bin/python scripts/06_refine.py --backend both`
- 检查 `data/intermediate/refined/` 是否同时生成主索引文件和独立后端文件
