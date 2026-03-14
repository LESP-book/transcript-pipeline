# 阶段六安全替换与整篇单次 Codex 校对设计

## 目标

将阶段六从“多块最小编辑 + Markdown 组装”调整为“句级安全替换 + 整篇单次 Codex 校对”，在不把讲解误替换为原文的前提下，尽量降低 Codex 周额度消耗，并减少最终人工校对时间。

## 范围

- 在阶段四对齐结果基础上，引入句级安全替换判定
- 仅对高置信连续引用组直接用参考原文替换
- 生成带 `locked_quote` / `unlocked_text` 标记的预替换全文
- 整篇仅调用一次 Codex 做最终整理
- 将整篇参考文本一并输入 Codex，用于修正未锁定区域
- 保持阶段六主输出 `data/intermediate/refined/*.json` 与 `final_markdown` 主结构兼容

## 非目标

- 不做 OCR
- 不做新一轮 ASR
- 不引入新的多模型路由流程
- 不改变阶段七导出结构
- 不把内部 `locked` / `unlocked` 标记暴露到最终 Markdown
- 不在本轮清理或删除 `prompts.classify_and_correct` 配置项

## 问题判断

现有阶段六成本高的根因不是并发本身，而是每篇文档固定存在多次块级 LLM 调用，并且每个块都要重复携带上下文。对读书会录屏这类“原文朗读与讲解细粒度交错”的材料，按块判断“原文块 / 讲解块 / 混合块”信息增益很低，容易塌缩为大量混合块，无法显著减少高成本调用。

可行的降本方向不是继续做块级路由，而是先用规则和已有对齐证据完成极保守的安全替换，再把整篇文稿和整篇参考文本一起送给 Codex 做一次全局校对。

## 方案

### 1. 句级安全替换

先基于阶段四输出的 `matched_reference_text`、`match_score`、`top_matches` 等证据，将 ASR 文本切分为句级或短句群级单元。每个单元不判断“属于原文还是讲解”，只判断“能否安全直接替换为参考原文”。

单句进入 `safe_replace_candidate` 必须同时满足：

- `matched_reference_text` 非空
- `match_score` 高于高阈值
- `top_matches` 第一名与第二名分差足够大
- ASR 与匹配 reference 的长度比例处于较窄区间
- 额外内容比例足够低
- 差异主要是标点、语气词、同音字、近形字或少量不改变语义主干的漏字/多字
- 不命中明显讲解词、问答词、串场词

### 2. 连续组提交

单句高分不是直接替换的充分条件。只有连续 2 句及以上都满足高置信条件，且 reference 位置连续或近连续，整组才允许提交为 `locked_quote`。连续组必须同时满足：

- 组内每句都属于 `safe_replace_candidate`
- 组内每句额外内容比例都低
- 组内没有明显讲解渗透
- 组内 reference 命中位置单调前进
- 组内不存在“短原文句 + 长讲解句”这种纯度失衡情况

任何一条不满足，整组降级为 `unlocked_text`，不做预替换。

### 3. 高风险场景防御

对“讲一句原文就进行讲解”这种混合极细的情况，默认采取保守策略：

- 即使某句 `match_score` 很高，只要长度明显大于 reference，直接否决替换
- 即使连续两句都命中，只要其中一条出现解释性新增内容，整组不替换
- 孤立高分句默认不替换

结论是第一版采用“高精度、低召回”的安全替换策略，宁可少替换，也不允许把讲解误替换成原文。

### 4. 预替换全文

在完成安全替换后，组装一份“预替换全文”。该文本不直接写入最终产物，而是作为单次 Codex 调用的输入材料。预替换全文中的片段分为两类：

- `locked_quote`
  - 已通过安全替换规则直接替换为参考原文
  - 后续禁止改写实词内容
  - 只允许做标点、分段、引用格式处理
- `unlocked_text`
  - 未通过安全替换规则，保留 ASR 内容
  - 允许 Codex 结合整篇参考文本进一步判断并修正

内部输入协议需要显式标注片段类型，但这些标签不应出现在最终 Markdown 中。

### 5. 单次 Codex 校对

Codex 输入必须同时包含：

- 整篇参考文本
- 预替换全文
- 严格处理规则

这样 Codex 在处理 `unlocked_text` 时可以参考整篇 reference 修复遗漏的原文段，而不是只依据局部上下文猜测；同时 `locked_quote` 受到硬约束，避免已经安全替换好的原文再次被改坏。

Codex 提示词需要明确要求：

- 不得改写 `locked_quote` 的实词内容
- `locked_quote` 只允许微调标点、断句、引用格式
- `unlocked_text` 可参考整篇 reference 判断是否存在尚未替换的原文段
- 若证据不足，不得强行把讲解改写为原文
- 输出仅返回最终 Markdown，不暴露内部标签

## 配置建议

新增一组阶段六安全替换配置，放入 `llm` 或独立的 `refine` 配置段，保持阈值可调：

- `safe_replace_min_score`
- `safe_replace_min_margin`
- `safe_replace_length_ratio_min`
- `safe_replace_length_ratio_max`
- `safe_replace_max_extra_content_ratio`
- `safe_replace_min_run_length`

现有 `block_concurrency` 在该方案下不再是成本控制主轴。即使保留字段，也应允许阶段六主流程在单次 Codex 调用模式下不依赖块级并发。

## 兼容性

- 阶段六输出仍维持 `data/intermediate/refined/*.json`
- `final_markdown` 继续作为主字段
- 可选增加向后兼容的调试字段或统计字段，但不改变现有主结构
- `prompts.final_cleanup` 继续作为整篇整理提示词入口
- `prompts.classify_and_correct` 暂时保留，不在本轮清理其配置结构

## 验证

- 使用 `.venv/bin/python -m pytest`
- 重点新增以下测试：
  - 高置信连续引用组被直接替换
  - 孤立高分句不替换
  - “一句原文 + 一句讲解”不被错误替换
  - 预替换全文正确生成 `locked_quote` / `unlocked_text`
  - 单次 Codex 调用输入同时包含整篇 reference 与预替换全文
  - `locked_quote` 在提示词规则中被明确冻结
- 运行 `.venv/bin/python scripts/06_refine.py` 做真实样例检查
- 核验生成结果是否在人工校对成本与 Codex 调用次数之间达到更优平衡
