# Stage 6 Codex Default Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将阶段六默认 LLM 后端统一改为仅使用 `codex_cli`，同时保留显式配置启用 `gemini_cli` 的能力。

**Architecture:** 本次改动只触达默认值定义层和依赖默认值的测试层，不修改阶段六主流程。配置模型、默认 YAML 和测试夹具保持一致，避免不同入口出现分叉默认行为。

**Tech Stack:** Python、Pydantic、Pytest、项目内 `.venv`

---

## Chunk 1: 默认值与测试收缩

### Task 1: 锁定默认后端行为

**Files:**
- Modify: `tests/test_refine.py`
- Modify: `tests/test_export_markdown.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

补充或调整断言，要求默认配置下阶段六仅出现 `codex_cli`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py tests/test_export_markdown.py -q`

Expected: 由于当前默认值仍包含 `gemini_cli`，出现断言失败。

- [ ] **Step 3: 编写最小实现**

修改 `src/schemas.py`、`config/settings.yaml`、`tests/helpers.py` 中的默认 `backends` 为 `["codex_cli"]`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py tests/test_export_markdown.py -q`

Expected: 默认值相关断言通过。

### Task 2: 完整验证阶段六

**Files:**
- Modify: `src/schemas.py`
- Modify: `config/settings.yaml`
- Modify: `tests/helpers.py`
- Modify: `tests/test_refine.py`
- Modify: `tests/test_export_markdown.py`

- [ ] **Step 1: 运行全量测试**

Run: `.venv/bin/python -m pytest`

Expected: 全部通过。

- [ ] **Step 2: 运行阶段六真实样例**

Run: `.venv/bin/python scripts/06_refine.py`

Expected: 成功写出或更新 `data/intermediate/refined/*.json`。

- [ ] **Step 3: 检查真实输出**

确认输出中的 `refinement_backends` 默认只包含 `codex_cli`，且 `backend_status` 不再默认出现 `gemini_cli`。
