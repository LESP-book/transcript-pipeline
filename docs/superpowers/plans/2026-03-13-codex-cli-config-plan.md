# Codex CLI Config Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让阶段六 `codex_cli` 显式使用项目配置的模型与推理强度，并把模型名稳定写入产物。

**Architecture:** 保持阶段六主流程不变，只在 `run_codex_cli()` 的命令构造处增加显式参数透传。测试通过命令捕获验证 `--model` 与 `model_reasoning_effort` 是否进入 `codex exec`，同时验证产物级 `model_name` 不再回退成模糊的 `codex_default`。

**Tech Stack:** Python、pytest、Codex CLI、项目内 `.venv`

---

## Chunk 1: Codex 参数透传

### Task 1: 锁定 codex 命令构造行为

**Files:**
- Modify: `tests/test_refine.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: Write the failing test**

新增一个测试，要求 `run_codex_cli()` 在配置存在时：
- 传递 `--model`
- 传递 `-c model_reasoning_effort=...`
- 将配置模型名回填到结果中

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_run_codex_cli_uses_configured_model_and_reasoning_effort -q`

Expected: FAIL，因为当前实现没有传递这些配置。

- [ ] **Step 3: Write minimal implementation**

修改 `src/refine_utils.py` 的 `run_codex_cli()`。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_run_codex_cli_uses_configured_model_and_reasoning_effort -q`

Expected: PASS。

### Task 2: 统一默认配置

**Files:**
- Modify: `config/settings.yaml`
- Modify: `tests/helpers.py`
- Modify: `src/refine_utils.py`

- [ ] **Step 1: Set explicit default model**

将阶段六默认 `llm.model` 改为显式值，避免跨机器漂移。

- [ ] **Step 2: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest`
