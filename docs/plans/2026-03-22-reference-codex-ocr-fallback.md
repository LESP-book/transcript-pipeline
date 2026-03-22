# Reference Codex OCR Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为扫描版 PDF 的 OCR 增加 Codex 保底层，避免 Gemini 失败后直接退回本地 `ocrmypdf`。

**Architecture:** 保持参考原文阶段的主结构不变，只修改 `src/reference_utils.py` 中 PDF OCR 的回退顺序。新增一个 OCR 专用 Codex 执行器与对应配置，链路调整为 `Gemini OCR -> Codex OCR -> ocrmypdf`，并在提示词里强制要求只用模型视觉能力、禁止调用本机 OCR 工具。

**Tech Stack:** Python, pytest, Codex CLI, Gemini CLI, pypdf, ocrmypdf

---

### Task 1: 先写回退链路的失败测试

**Files:**
- Modify: `tests/test_prepare_reference.py`
- Test: `tests/test_prepare_reference.py`

**Step 1: Write the failing test**

补两个测试：
- `Gemini` 失败且 PDF 文字层为空时，优先调用 `run_codex_pdf_ocr()`
- `Codex` 也失败时，才调用 `run_tesseract_pdf_ocr()`

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_prepare_reference.py::test_prepare_reference_file_falls_back_to_codex_ocr_when_gemini_ocr_fails -q`
Expected: FAIL，因为当前实现没有 `run_codex_pdf_ocr()`

**Step 3: Write minimal implementation**

在 `src/reference_utils.py` 添加 Codex OCR 错误类型、提示词构造、CLI 调用与回退链路。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_prepare_reference.py -q`
Expected: PASS

### Task 2: 锁定 Codex OCR 命令与配置

**Files:**
- Modify: `src/schemas.py`
- Modify: `config/settings.yaml`
- Modify: `tests/helpers.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_prepare_reference.py`

**Step 1: Write the failing test**

补测试，要求 Codex OCR：
- 默认模型为 `gpt-5.4-mini`
- 默认推理强度为 `medium`
- 提示词包含“禁止调用本机 OCR 工具，只使用模型视觉能力”

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_prepare_reference.py::test_run_codex_pdf_ocr_uses_configured_model_prompt_and_reasoning_effort -q`
Expected: FAIL，因为当前无对应实现与配置

**Step 3: Write minimal implementation**

仅在 `reference` 配置下新增 OCR 专用 Codex 字段，不复用阶段六主 LLM 模型配置。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_prepare_reference.py tests/test_config.py -q`
Expected: PASS

### Task 3: 完整验证并做真实样例检查

**Files:**
- Reference: `docs/REVIEW_CHECKLIST.md`

**Step 1: Run full relevant tests**

Run: `.venv/bin/python -m pytest`

**Step 2: Run real stage script**

Run: `.venv/bin/python scripts/03_prepare_reference.py`
Expected: 若环境具备 CLI 依赖，则能产生参考文本与 OCR 中间产物；否则记录真实阻塞原因

**Step 3: Inspect outputs**

检查 `data/intermediate/ocr/` 与 `data/intermediate/extracted_text/` 是否出现符合链路的产物与警告信息。
