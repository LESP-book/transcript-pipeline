# Batch Pipeline Streaming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将批处理从整批分阶段推进改为按 job 流水推进，让已完成转写的 job 立即进入远程链路。

**Architecture:** 保持阶段内部实现不变，只改 `src/job_runner.py` 的批处理编排。主线程顺序执行 `extract-audio` 与 `transcribe`，远程线程池串起单个 job 的 `prepare-reference -> refine -> export-markdown`，并继续使用现有 `remote_concurrency` 作为远程链路并发上限。

**Tech Stack:** Python、pytest、ThreadPoolExecutor

---

### Task 1: 写流水推进回归测试

**Files:**
- Modify: `tests/test_job_runner.py`
- Test: `tests/test_job_runner.py`

**Step 1: Write the failing test**

新增一个测试，验证 `job-a` 的 `prepare-reference` 会在 `job-b` 的 `transcribe` 尚未结束时启动。

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_run_batch_jobs_starts_remote_pipeline_before_later_jobs_finish_transcribe -v`

Expected: FAIL，因为当前实现仍是整批按阶段推进。

**Step 3: Write minimal implementation**

只修改 `src/job_runner.py` 的批处理调度逻辑，不改阶段实现。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_run_batch_jobs_starts_remote_pipeline_before_later_jobs_finish_transcribe -v`

Expected: PASS

### Task 2: 保持失败隔离与输出复制行为

**Files:**
- Modify: `src/job_runner.py`
- Test: `tests/test_job_runner.py`

**Step 1: Re-run existing regression test**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_run_batch_jobs_marks_failed_stage_skips_later_stages_and_records_output -v`

Expected: 若实现破坏旧语义则 FAIL。

**Step 2: Adjust implementation minimally**

保证：

- `prepare-reference` 失败后不进入 `refine`
- `export-markdown` 成功后仍复制最终产物
- summary 统计与现有结构兼容

**Step 3: Re-run both tests**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_run_batch_jobs_starts_remote_pipeline_before_later_jobs_finish_transcribe tests/test_job_runner.py::test_run_batch_jobs_marks_failed_stage_skips_later_stages_and_records_output -v`

Expected: PASS

### Task 3: 完整验证

**Files:**
- Modify: `src/job_runner.py`
- Modify: `tests/test_job_runner.py`
- Reference: `docs/REVIEW_CHECKLIST.md`

**Step 1: Run targeted batch tests**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py -v`

Expected: PASS

**Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest`

Expected: PASS

**Step 3: Manual review**

检查以下点：

- 未新增并发参数
- `remote_concurrency` 仍是唯一远程并发控制
- 未改动 `prepare-reference` / `refine` / `export-markdown` 内部逻辑
- 前面的 job 可陆续产出最终 Markdown
