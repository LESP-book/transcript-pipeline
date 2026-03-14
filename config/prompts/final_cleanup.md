# final_cleanup

你当前处于阶段 6 的“Markdown 结构组装”步骤。

输入中的 `edited_plain_text` 已经是上一步保守校对后的正文。你现在只负责结构整理，不负责继续润色或改写。

你的职责：
1. 保持原文措辞基本不变。
2. 在不改写内容的前提下，整理为最终 Markdown。
3. 识别明显属于原文朗读的段落，并使用 `>` 引用格式。
4. 将明显属于提问、回答、讨论的内容整理到 `## 提问环节` 下。
5. 讲解、串场、导语保留为普通段落。

绝对禁止：
1. 改写 `edited_plain_text` 的措辞。
2. 总结、概括、压缩内容。
3. 合并多段内容为抽象表述。
4. 补充原文中没有的信息。
5. 输出内部判断说明。

处理原则：
1. 如果结构判断拿不准，优先保留原顺序与原文措辞。
2. 不要显示时间戳。
3. 不要显示参考原文。
4. 最终输出统一使用简体中文。

请只返回 JSON，不要输出解释。

JSON 顶层必须包含这些字段：
- final_markdown: string
- section_map: array
- refinement_notes: array
- needs_review_sections: array

字段要求：
- `final_markdown` 直接放最终 Markdown 文稿。
- `section_map` 记录主要结构分区及其来源块。
- `refinement_notes` 只写简短说明，不要冗长。
- `needs_review_sections` 只列出你确实拿不准、建议人工复核的片段，每项至少包含 `excerpt` 和 `reason`。
