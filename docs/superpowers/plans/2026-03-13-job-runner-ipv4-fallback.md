# Job Runner IPv4 Fallback Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为网页参考抓取增加最小 IPv4 回退，降低 `Network is unreachable` 导致的任务失败概率。

**Architecture:** 保持现有 `fetch_reference_from_url()` 主流程不变，只在请求层加一个轻量包装。默认先走现有请求；只有检测到网络不可达类错误时，才在局部上下文里将 `socket.getaddrinfo` 过滤为 IPv4 结果并重试一次。

**Tech Stack:** Python、urllib、socket、pytest、项目内 `.venv`

---

## Chunk 1: 抓取回退

### Task 1: 锁定网络不可达后的回退行为

**Files:**
- Modify: `tests/test_job_runner.py`
- Test: `tests/test_job_runner.py`

- [ ] **Step 1: Write the failing test**

新增一个测试，模拟首次 `urlopen()` 因网络不可达失败，第二次在 IPv4 解析上下文中成功返回 HTML。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_fetch_reference_from_url_retries_with_ipv4_when_network_is_unreachable -q`

Expected: FAIL，因为当前实现还没有 IPv4 回退。

- [ ] **Step 3: Write minimal implementation**

在 `src/job_runner.py` 中加入：
- 识别网络不可达类异常的帮助函数
- 局部 IPv4 解析上下文
- 请求包装函数

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py::test_fetch_reference_from_url_retries_with_ipv4_when_network_is_unreachable -q`

Expected: PASS。

### Task 2: 回归验证

**Files:**
- Modify: `src/job_runner.py`
- Modify: `tests/test_job_runner.py`

- [ ] **Step 1: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_job_runner.py -q`

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 3: Try real command**

Run the original `scripts/08_run_job.py` invocation when environment networking allows.
