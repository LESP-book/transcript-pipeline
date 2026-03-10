# Large-v3 Profile Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 GPU 环境新增更激进的 `large-v3` 高精度预设，并同步更新命令模板说明。

**Architecture:** 仅调整配置与文档，不改动 ASR 调用链。通过配置测试锁定新 profile 和更高的 `beam_size`，然后更新 `settings.yaml` 与 `README.md`，最后跑完整测试验证。

**Tech Stack:** Python, pytest, YAML, Markdown

---

### Task 1: 锁定配置行为

**Files:**
- Modify: `tests/test_config.py`

**Step 1: Write the failing test**

新增测试，断言：
- `wsl2_gpu_max_accuracy` profile 可加载
- 该 profile 使用 `cuda`、`large-v3`、`float16`
- 全局 `asr.beam_size == 8`

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: 因 profile 尚不存在或 `beam_size` 仍为 5 导致失败。

### Task 2: 更新配置

**Files:**
- Modify: `config/settings.yaml`

**Step 1: Write minimal implementation**

最小修改：
- 新增 `wsl2_gpu_max_accuracy`
- 将 `asr.beam_size` 从 5 调整到 8

**Step 2: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: PASS

### Task 3: 更新命令模板文档

**Files:**
- Modify: `README.md`

**Step 1: Add README examples**

补充：
- `wsl2_gpu_max_accuracy` 的单任务命令模板
- 说明该预设相对 `wsl2_gpu_high_accuracy` 的差异
- 说明 `beam_size` 已调高到 8

### Task 4: 全量验证

**Files:**
- Reference: `docs/REVIEW_CHECKLIST.md`

**Step 1: Run full tests**

Run: `.venv/bin/python -m pytest`

**Step 2: Run a real command help check**

Run: `.venv/bin/python scripts/08_run_job.py --help`

Expected: 能正常输出 CLI 帮助，说明入口未被破坏。
