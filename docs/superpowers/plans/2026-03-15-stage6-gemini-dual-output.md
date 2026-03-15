# Stage 6 Gemini Dual Output Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为阶段六增加 Gemini 单跑、Codex/Gemini 双跑和双结果落盘能力，同时保持现有主目录结构与阶段七消费边界清晰。

**Architecture:** 在不改动阶段六安全替换主流程的前提下，把“后端选择”收敛为命令行和配置两个入口。主 refined JSON 继续作为统一索引文件；单模型模式维持 `final_markdown` 兼容，双模型模式写空主结果并追加 `model_results`，同时额外输出后端独立 JSON。阶段七只消费主 refined JSON，并对双模型结果显式报错。

**Tech Stack:** Python、argparse、Pydantic、Pytest、项目内 `.venv`

---

## Chunk 1: 锁定命令行与产物结构

### Task 1: 先写阶段六双模型输出失败测试

**Files:**
- Modify: `tests/test_refine.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 写失败测试**

补充测试，要求：

- 单模型模式继续写 `final_markdown`
- 双模型模式写 `model_results`
- 双模型模式主文件 `final_markdown` 为空
- 双模型模式额外生成 `basename.codex_cli.json` 与 `basename.gemini_cli.json`

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`
Expected: 当前实现仍只写单一选中结果，新增断言失败。

- [ ] **Step 3: 实现最小代码**

在 `src/refine_utils.py` 中扩展写出逻辑与批处理主流程，不做自动选主结果。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`
Expected: 新增输出结构相关测试通过。

### Task 2: 先写命令行后端选择失败测试

**Files:**
- Modify: `tests/test_refine.py`
- Modify: `scripts/06_refine.py`
- Modify: `scripts/run_pipeline.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 写失败测试**

补充测试，要求命令行能把：

- `codex_cli`
- `gemini_cli`
- `both`

解析为对应的后端列表。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`
Expected: 当前脚本没有该参数或解析逻辑，测试失败。

- [ ] **Step 3: 实现最小代码**

为 `scripts/06_refine.py` 增加 `--backend`，并在 `scripts/run_pipeline.py` 的 `refine` 路径同样支持转发。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`
Expected: 参数解析相关测试通过。

## Chunk 2: 模型默认值与提示词约束

### Task 3: 先写 Gemini 默认模型与提示词差异化失败测试

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_refine.py`
- Test: `tests/test_config.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 写失败测试**

补充测试，要求：

- Gemini 主模型默认值为 `gemini-3.1-pro-preview`
- Gemini fallback 默认为 `gemini-3-flash-preview`
- Codex 提示词包含 “Gemini 和 Claude 审核”
- Gemini 提示词包含 “Codex 和 Claude 审核”

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_refine.py -q`
Expected: 默认值和提示词文本断言失败。

- [ ] **Step 3: 实现最小代码**

修改 `src/schemas.py`、`config/settings.yaml`、`tests/helpers.py` 与 `src/refine_utils.py` 的提示词拼装。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_refine.py -q`
Expected: 默认模型与提示词约束测试通过。

## Chunk 3: 阶段七兼容边界

### Task 4: 先写双模型 refined 导出失败测试

**Files:**
- Modify: `tests/test_export_markdown.py`
- Test: `tests/test_export_markdown.py`

- [ ] **Step 1: 写失败测试**

补充测试，要求：

- 主 refined JSON 缺少 `final_markdown` 且存在 `model_results` 时，阶段七显式报错
- 附加的 `basename.codex_cli.json` / `basename.gemini_cli.json` 不应被当成主 refined 文件导出

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_export_markdown.py -q`
Expected: 当前阶段七会误把附加 JSON 当成主文件或只报通用缺失错误。

- [ ] **Step 3: 实现最小代码**

修改 `src/export_utils.py`，只处理主 refined JSON，并给双模型主索引文件提供明确错误信息。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_export_markdown.py -q`
Expected: 阶段七兼容边界明确，测试通过。

## Chunk 4: 全量验证与真实样例

### Task 5: 按项目要求完成验证

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新文档**

在 `README.md` 中补充：

- `scripts/06_refine.py --backend gemini_cli`
- `scripts/06_refine.py --backend both`
- 双模型模式输出结构说明

- [ ] **Step 2: 跑全量测试**

Run: `.venv/bin/python -m pytest`
Expected: 全部通过。

- [ ] **Step 3: 跑真实样例**

Run: `.venv/bin/python scripts/06_refine.py --backend gemini_cli`
Expected: 成功写出 Gemini 单模型 refined 主文件。

- [ ] **Step 4: 跑双模型真实样例**

Run: `.venv/bin/python scripts/06_refine.py --backend both`
Expected: 成功写出主索引 JSON 与两个独立后端 JSON。
