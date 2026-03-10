# Profile Beam Size Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 ASR `beam_size` 改为按 profile 配置，并为不同精度档设置不同搜索强度。

**Architecture:** 保持最小兼容改动：`profiles.*` 新增 `beam_size`，ASR 调用优先读取活动 profile 的该值，缺失时回退到全局 `asr.beam_size`。同时更新配置测试和 README，确保用户命令与说明一致。

**Tech Stack:** Python, pytest, YAML, Markdown

---

### Task 1: 锁定配置行为

**Files:**
- Modify: `tests/test_config.py`

**Step 1: Write the failing test**

新增断言：
- `local_cpu` 与 `wsl2_gpu` 的 `beam_size == 5`
- `local_cpu_high_accuracy` 与 `wsl2_gpu_high_accuracy` 的 `beam_size == 8`
- `wsl2_gpu_max_accuracy` 的 `beam_size == 10`

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: FAIL，因为 `ProfileSettings` 还没有 `beam_size` 字段，或配置还未按 profile 区分。

### Task 2: 更新实现

**Files:**
- Modify: `src/schemas.py`
- Modify: `src/asr_utils.py`

**Step 1: Write minimal implementation**

最小实现：
- `ProfileSettings` 增加可选 `beam_size`
- `transcribe_audio_file` 优先使用 `active_profile.beam_size`，缺失时回退到 `settings.asr.beam_size`

**Step 2: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_transcribe.py -q`

Expected: PASS

### Task 3: 更新配置与文档

**Files:**
- Modify: `config/settings.yaml`
- Modify: `README.md`

**Step 1: Add per-profile beam sizes**

设置：
- `local_cpu = 5`
- `local_cpu_high_accuracy = 8`
- `wsl2_gpu = 5`
- `wsl2_gpu_high_accuracy = 8`
- `wsl2_gpu_max_accuracy = 10`

**Step 2: Update README wording**

把 `beam_size` 说明改成按 profile 区分，不再写成全局固定值。

### Task 4: 全量验证

**Files:**
- Reference: `docs/REVIEW_CHECKLIST.md`

**Step 1: Run full tests**

Run: `.venv/bin/python -m pytest`

**Step 2: Run CLI help check**

Run: `.venv/bin/python scripts/08_run_job.py --help`

Expected: PASS
