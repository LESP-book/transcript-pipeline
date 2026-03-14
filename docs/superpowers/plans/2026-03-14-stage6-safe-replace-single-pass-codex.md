# Stage 6 Safe Replace Single-Pass Codex Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将阶段六改为“句级安全替换 + 整篇单次 Codex 校对”，在避免讲解误替换为原文的前提下减少高成本调用次数并降低人工校对成本。

**Architecture:** 复用阶段四对齐证据做高精度安全替换，只对连续高置信引用组直接回填 reference。生成带锁定状态的预替换全文后，整篇只调用一次 Codex，并将整篇参考文本一并传入，允许模型只在未锁定区域继续修复遗漏原文段。

**Tech Stack:** Python、Pydantic、Pytest、项目内 `.venv`

---

## Chunk 1: 配置与测试护栏

### Task 1: 为安全替换阈值建立失败测试

**Files:**
- Modify: `tests/test_refine.py`
- Modify: `tests/helpers.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

补充针对安全替换阈值与连续组规则的测试夹具，覆盖以下场景：

- 连续 2 句高置信 reference 命中应进入可替换组
- 孤立高分句不得替换
- “一句原文 + 一句讲解”不得被误判为可替换组
- 高分但长度明显超出 reference 的句子不得替换

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`

Expected: 由于当前阶段六尚无安全替换规则或阈值实现，新增断言失败。

- [ ] **Step 3: 补充最小配置夹具**

在 `tests/helpers.py` 中为安全替换阈值补充默认配置写入，确保测试可显式调节边界值。

- [ ] **Step 4: 再次运行测试确认仍为目标失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`

Expected: 失败点只剩安全替换逻辑未实现，不再是配置缺失错误。

### Task 2: 增加配置模型与默认值

**Files:**
- Modify: `src/schemas.py`
- Modify: `config/settings.yaml`
- Modify: `tests/helpers.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写最小实现**

为阶段六增加安全替换所需的阈值配置，保持默认值极保守：

- `safe_replace_min_score`
- `safe_replace_min_margin`
- `safe_replace_length_ratio_min`
- `safe_replace_length_ratio_max`
- `safe_replace_max_extra_content_ratio`
- `safe_replace_min_run_length`

- [ ] **Step 2: 运行定向测试**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`

Expected: 配置层相关报错消失，但安全替换实现相关测试仍失败。

## Chunk 2: 句级安全替换核心逻辑

### Task 3: 拆出句级判定与连续组提交逻辑

**Files:**
- Modify: `src/refine_utils.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

补充最小单元测试，要求：

- 单句高分但存在讲解词时判定为 `unsafe`
- 单句高分且额外内容比例低时可进入 `safe_replace_candidate`
- 连续组仅在全部成员高置信时才提交为 `locked_quote`
- 组内混入一条可疑讲解句时整体降级为 `unlocked_text`

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_safe_replace_* -q`

Expected: 由于相关函数不存在或行为不符，测试失败。

- [ ] **Step 3: 编写最小实现**

在 `src/refine_utils.py` 中新增或重组辅助函数，建议边界如下：

- 句级归一化与差异估计
- 额外内容比例计算
- 单句 `safe_replace_candidate` 判定
- 连续组提交为 `locked_quote` 的规则
- 将未提交内容保留为 `unlocked_text`

- [ ] **Step 4: 运行定向测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_safe_replace_* -q`

Expected: 新增规则测试通过。

### Task 4: 生成预替换全文

**Files:**
- Modify: `src/refine_utils.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

要求生成的预替换全文能稳定输出片段列表，至少包含：

- 片段顺序
- 片段类型 `locked_quote` / `unlocked_text`
- 片段正文
- 与 reference 命中关系相关的最小调试信息

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_build_pre_replaced_document_* -q`

Expected: 当前无该结构，测试失败。

- [ ] **Step 3: 编写最小实现**

在 `src/refine_utils.py` 中生成供单次 Codex 调用使用的预替换全文结构，并保证最终输出仍可回收为纯文本正文。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_build_pre_replaced_document_* -q`

Expected: 片段结构与正文拼装行为符合预期。

## Chunk 3: 单次 Codex 调用与提示词收敛

### Task 5: 重写阶段六主流程为单次整篇 Codex 校对

**Files:**
- Modify: `src/refine_utils.py`
- Modify: `tests/test_refine.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

新增集成测试，要求阶段六主流程：

- 不再按块发起多次最小编辑调用
- 仅发起一次整篇 Codex 调用
- 调用输入同时包含整篇 reference 与预替换全文

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_refine_batch_*single_pass* -q`

Expected: 当前实现仍为块级多次调用，测试失败。

- [ ] **Step 3: 编写最小实现**

将主流程改为：

- 读取整篇 ASR 与整篇 reference
- 先做句级安全替换
- 再构建单次整篇 Codex 提示词
- 保留 fallback 与输出写入逻辑

- [ ] **Step 4: 运行定向测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_refine_batch_*single_pass* -q`

Expected: 单次调用约束成立。

### Task 6: 更新提示词模板，冻结锁定片段

**Files:**
- Modify: `config/prompts/final_cleanup.md`
- Modify: `tests/test_refine.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

断言整篇 Codex 提示词中明确包含以下约束：

- 输入里存在整篇 reference
- `locked_quote` 禁止改写实词内容
- `unlocked_text` 允许参考 reference 继续修复
- 证据不足时不得将讲解改写为原文

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_build_single_pass_prompt_* -q`

Expected: 当前提示词不含这些约束，测试失败。

- [ ] **Step 3: 编写最小实现**

更新 `config/prompts/final_cleanup.md` 及其对应拼装逻辑，使 Codex 能接收：

- 整篇 reference
- 预替换全文
- 锁定 / 未锁定处理规则

- [ ] **Step 4: 运行定向测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_build_single_pass_prompt_* -q`

Expected: 提示词内容满足冻结规则与 reference 输入要求。

## Chunk 4: 兼容输出与真实样例验证

### Task 7: 回归 refined 输出结构

**Files:**
- Modify: `src/refine_utils.py`
- Modify: `tests/test_refine.py`
- Test: `tests/test_refine.py`

- [ ] **Step 1: 编写失败测试**

确认新流程下：

- `final_markdown` 仍存在
- 现有下游依赖字段保持兼容
- 如新增统计字段，仅以向后兼容方式追加

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_refine.py::test_refine_batch_writes_expected_fulltext_output_structure -q`

Expected: 若输出结构变化不兼容，测试失败。

- [ ] **Step 3: 编写最小实现**

整理结果写出逻辑，确保阶段七 `export_markdown` 仍可消费。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_refine.py -q`

Expected: `tests/test_refine.py` 全部通过。

### Task 8: 按项目要求完成全链路验证

**Files:**
- Modify: `docs/superpowers/specs/2026-03-14-stage6-safe-replace-single-pass-codex-design.md`
- Modify: `docs/superpowers/plans/2026-03-14-stage6-safe-replace-single-pass-codex.md`

- [ ] **Step 1: 运行全量测试**

Run: `.venv/bin/python -m pytest`

Expected: 全部通过。

- [ ] **Step 2: 运行阶段六真实样例**

Run: `.venv/bin/python scripts/06_refine.py`

Expected: 成功生成或更新 `data/intermediate/refined/*.json`。

- [ ] **Step 3: 检查真实输出**

确认至少一份真实样例满足：

- Codex 主调用次数显著下降
- 已锁定引用段未被错误改写
- 未锁定区域仍能借助整篇 reference 修复遗漏原文段
- 最终 Markdown 可直接进入人工终审

- [ ] **Step 4: 按 `docs/REVIEW_CHECKLIST.md` 自检**

检查范围控制、测试真实性、真实样例质量与已知偏差，必要时回到前述任务做最小修复。

## 备注

- 本计划遵循项目规则，不包含 `git commit` 步骤。
- `prompts.classify_and_correct` 的清理或废弃不在本轮范围内。
